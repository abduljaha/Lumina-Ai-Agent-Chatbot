"""Chat service - orchestrates the LangGraph agent for conversations."""
from __future__ import annotations

import logging
import time
from typing import Any, AsyncIterator
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.graph import AgentGraph
from app.agents.state import INTENT_UNKNOWN
from app.core.background import track as track_background
from app.db.models import Message, MessageRole
from app.memory.extraction import extract_personal_info
from app.memory.manager import MemoryManager
from app.repositories import MessageRepository
from app.schemas.chat import ChatRequest
from app.services.user import UserService

logger = logging.getLogger("app")


def _make_human_message(content: str, message_id: str | None = None) -> object:
    """Create a HumanMessage compatible object with optional langchain_core."""
    try:
        from langchain_core.messages import HumanMessage

        return HumanMessage(content=content, id=message_id)
    except ImportError:
        class HumanMessage:
            def __init__(self, content: str, id: str | None = None) -> None:
                self.content = content
                self.id = id

            def __repr__(self) -> str:
                return f"HumanMessage(content={self.content!r})"

        return HumanMessage(content=content, id=message_id)


def _make_ai_message(content: str, message_id: str | None = None) -> object:
    """Create an AIMessage-compatible object with optional langchain_core.

    Mirrors `_make_human_message` - kept separate (not a `role` parameter on
    one function) so each stays a simple, direct match for the LangChain
    message class it stands in for.
    """
    try:
        from langchain_core.messages import AIMessage

        return AIMessage(content=content, id=message_id)
    except ImportError:
        class AIMessage:
            def __init__(self, content: str, id: str | None = None) -> None:
                self.content = content
                self.id = id

            def __repr__(self) -> str:
                return f"AIMessage(content={self.content!r})"

        return AIMessage(content=content, id=message_id)


class ChatService:
    """Business logic for chat interactions."""

    # How many of a thread's most recent messages are replayed into the
    # agent's context each turn. See `_load_history_messages`.
    HISTORY_WINDOW = 40

    def __init__(
        self,
        db: AsyncSession,
        agent_graph: AgentGraph,
        memory_manager: MemoryManager,
    ) -> None:
        self._db = db
        self._graph = agent_graph
        self._memory = memory_manager
        self._message_repo = MessageRepository(db)
        self._user_service = UserService(db)

    async def _load_history_messages(self, thread_id: str, before: Any = None) -> list[Any]:
        """Rebuild a thread's conversation history as LangChain messages, from the database.

        The agent graph's checkpointer (`MemorySaver`) only lives in this
        server process's memory - it doesn't survive a restart/redeploy and
        isn't shared across multiple backend workers, so a thread's actual
        conversational memory can't be trusted to still be there. The
        `messages` table is the durable, cross-device source of truth, so
        history is reconstructed from it on every turn instead.

        Each message keeps its DB row's id as its LangChain message id.
        LangGraph's `add_messages` reducer merges by id (replacing a match,
        appending anything new) - so when the checkpointer's in-memory state
        IS still warm from earlier in this process's life, replaying the
        same ids just replaces those entries in place rather than
        duplicating them.
        """
        rows = await self._message_repo.list_recent_for_thread(
            thread_id, limit=self.HISTORY_WINDOW, before=before
        )
        history: list[Any] = []
        for row in rows:
            if row.role == MessageRole.USER:
                history.append(_make_human_message(row.content, message_id=str(row.id)))
            elif row.role == MessageRole.ASSISTANT and row.content:
                # Failed-turn placeholders (see `_persist_failed_turn`) are
                # intentionally still replayed - they're real "assistant said
                # this" history the model should stay consistent with.
                history.append(_make_ai_message(row.content, message_id=str(row.id)))
        return history

    async def _remember_personal_info(self, user_id: str, message: str) -> None:
        """Extract and persist any personal facts disclosed in this message.

        Written as ENTITY/USER_PREFERENCE memory, which is retrieved by
        user_id (not thread_id) - so a fact learned in one conversation is
        available to every other conversation this user has, not just this
        thread.
        """
        for fact in extract_personal_info(message):
            if fact.kind == "entity" and fact.key:
                await self._memory.upsert_entity(user_id, fact.key, fact.value)
            elif fact.kind == "preference":
                await self._memory.add_preference_if_new(user_id, fact.value)

    def _schedule_llm_profile_update(self, user_id: str, user_message: str, assistant_message: str) -> None:
        """Fire the LLM-driven profile pass without making the user wait for it.

        The regex pass above already catches common phrasings inline (fast,
        zero extra latency); this is the "LLM determines it should be saved"
        half of the requirement, covering corrections and phrasings regex
        can't anticipate - it runs after the response is already on its way
        back, using its own DB session since the request-scoped one may be
        gone by the time this actually executes.
        """
        if not assistant_message:
            return

        async def _run() -> None:
            from app.db.session import async_session_factory
            from app.memory.llm_extraction import llm_extract_profile_updates

            try:
                async with async_session_factory() as session:
                    memory = MemoryManager(session)
                    bundle = await memory.retrieve_for_context(user_id)
                    existing = {
                        k: v.split(": ", 1)[-1] if ": " in v else v
                        for k, v in bundle.get("entities", {}).items()
                    }
                    conversation = f"User: {user_message}\nAssistant: {assistant_message}"
                    updates, deletions = await llm_extract_profile_updates(
                        self._graph.model_router, conversation, existing
                    )
                    for update in updates:
                        await memory.upsert_entity(user_id, update["key"], update["value"])
                    for key in deletions:
                        await memory.delete_entity_by_key(user_id, key)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Background LLM profile update failed for user %s: %s", user_id, exc)

        track_background(_run())

    async def process_message(
        self,
        user_id: str,
        thread_id: str,
        request: ChatRequest,
    ) -> dict[str, Any]:
        """Process a user message and return the assistant's response."""
        # Persist the user message
        user_message = Message(
            thread_id=thread_id,
            role=MessageRole.USER,
            content=request.message,
            attachments=[a.model_dump() for a in request.attachments],
            images=request.images,
            metadata_=request.metadata_,
        )
        await self._message_repo.create(user_message)
        await self._remember_personal_info(user_id, request.message)

        # Build the graph state - `history` already includes the user message
        # just created above (it's flushed, so visible to this query).
        user_settings = await self._user_service.get_settings(user_id)
        history = await self._load_history_messages(thread_id)
        state = self._build_state(
            user_id=user_id,
            thread_id=thread_id,
            messages=history,
            requested_model=request.model,
            provider=request.provider,
            custom_system_prompt=user_settings.get("system_prompt") or None,
            images=request.images,
        )

        # Store short-term memory of the user message
        await self._memory.add_short_term(
            user_id, f"User said: {request.message}", thread_id=thread_id
        )

        # Invoke the graph
        start = time.perf_counter()
        result = await self._graph.invoke(state)
        latency = int((time.perf_counter() - start) * 1000)

        # Store the assistant message. The ask_user path ends the graph with
        # no generation at all, so its clarifying question is the message.
        assistant_content = result.get("generation") or result.get("pending_question") or ""
        assistant_message = Message(
            thread_id=thread_id,
            role=MessageRole.ASSISTANT,
            content=assistant_content,
            tokens=result.get("token_usage", {}).get("total_tokens"),
            latency_ms=latency,
            cost=result.get("cost", 0.0),
            model=result.get("current_model"),
            metadata_={
                "provider": result.get("current_provider"),
                "citations": result.get("citations", []),
                "tool_results": result.get("tool_results", []),
            },
        )
        await self._message_repo.create(assistant_message)
        await self._message_repo.commit()

        # Store assistant response in memory
        await self._memory.add_short_term(
            user_id, f"Assistant said: {assistant_content[:200]}", thread_id=thread_id
        )
        self._schedule_llm_profile_update(user_id, request.message, assistant_content)

        return {
            "thread_id": thread_id,
            "message_id": str(assistant_message.id),
            "content": assistant_content,
            # The ask_user path ends the graph before llm_node ever runs, so
            # no provider was actually selected - ChatResponse requires
            # non-null strings here, so fall back rather than 500.
            "model": result.get("current_model") or "none",
            "provider": result.get("current_provider") or "none",
            "token_usage": result.get("token_usage", {}),
            "tokens": result.get("token_usage", {}).get("total_tokens") or 0,
            "latency_ms": latency,
            "cost": result.get("cost", 0.0),
            "citations": result.get("citations", []),
            "needs_user_input": result.get("needs_user_input", False),
            "pending_question": result.get("pending_question"),
        }

    async def stream_message(
        self,
        user_id: str,
        thread_id: str,
        request: ChatRequest,
    ) -> AsyncIterator[dict[str, Any]]:
        """Stream a user message and produce token-by-token events."""
        # Persist the user message
        user_message = Message(
            thread_id=thread_id,
            role=MessageRole.USER,
            content=request.message,
            attachments=[a.model_dump() for a in request.attachments],
            images=request.images,
            metadata_=request.metadata_,
        )
        await self._message_repo.create(user_message)
        await self._message_repo.commit()
        await self._remember_personal_info(user_id, request.message)

        # Build the graph state - `history` already includes the user message
        # just created above.
        user_settings = await self._user_service.get_settings(user_id)
        history = await self._load_history_messages(thread_id)
        state = self._build_state(
            user_id=user_id,
            thread_id=thread_id,
            messages=history,
            requested_model=request.model,
            provider=request.provider,
            custom_system_prompt=user_settings.get("system_prompt") or None,
            images=request.images,
        )

        # Yield a start event
        yield {"type": "start", "thread_id": thread_id}

        # Stream the graph execution
        full_generation = ""
        current_model: str | None = None
        current_provider: str | None = None
        try:
            async for event in self._graph.stream(state):
                # event is a dict of node updates
                for node_name, update in event.items():
                    if update.get("current_model"):
                        current_model = update["current_model"]
                    if update.get("current_provider"):
                        current_provider = update["current_provider"]
                    if "generation" in update and update.get("generation"):
                        full_generation = update["generation"]
                        yield {"type": "token", "content": update["generation"]}
                    if "tool_results" in update and update.get("tool_results"):
                        yield {"type": "tool_call", "data": update["tool_results"]}
                    if update.get("needs_user_input"):
                        # The ask_user path never sets "generation" - its
                        # question is the only content this turn produces,
                        # so it must also be what gets persisted below.
                        full_generation = update.get("pending_question") or full_generation
                        yield {
                            "type": "message",
                            "content": update.get("pending_question"),
                        }
        except Exception as exc:  # noqa: BLE001
            await self._persist_failed_turn(thread_id, str(exc))
            yield {"type": "error", "content": str(exc)}
            return

        # Persist the assistant message
        assistant_message = Message(
            thread_id=thread_id,
            role=MessageRole.ASSISTANT,
            content=full_generation,
            model=current_model,
            metadata_={"provider": current_provider},
        )
        await self._message_repo.create(assistant_message)
        await self._message_repo.commit()
        self._schedule_llm_profile_update(user_id, request.message, full_generation)

        yield {"type": "done", "message_id": str(assistant_message.id)}

    async def _persist_failed_turn(self, thread_id: str, error_content: str) -> None:
        """Save a placeholder assistant message when a turn fails outright.

        Without this, a failed generation (e.g. every provider unavailable)
        left no trace in the thread: the browser showed an ephemeral error
        bubble that vanished on refresh, and "retry" had no persisted
        assistant message to regenerate in place, so it always fell back to
        resending as a brand-new turn instead.
        """
        try:
            failed_message = Message(
                thread_id=thread_id,
                role=MessageRole.ASSISTANT,
                content=f"⚠️ {error_content}",
                metadata_={"error": True},
            )
            await self._message_repo.create(failed_message)
            await self._message_repo.commit()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to persist error placeholder for thread %s: %s", thread_id, exc)

    async def regenerate_stream(
        self,
        user_id: str,
        thread_id: str,
        message_id: str,
    ) -> AsyncIterator[dict[str, Any]]:
        """Regenerate a specific assistant reply in place.

        Unlike `stream_message`, this does NOT persist a new user message -
        the prompt being answered already exists in the thread (and in the
        LangGraph checkpoint's accumulated history for this thread_id), so
        re-invoking the graph with no *new* message just re-runs the same
        turn and produces a fresh reply to it. The old reply is deleted
        first so the thread ends up with one answer for that turn, not two.
        """
        old_message = await self._message_repo.get(message_id)
        if not old_message or old_message.thread_id != thread_id or old_message.role != MessageRole.ASSISTANT:
            yield {"type": "error", "content": "Message not found"}
            return

        last_user_message = await self._get_last_user_message_before(thread_id, old_message.created_at)
        if last_user_message is None:
            yield {"type": "error", "content": "No prior user message to regenerate a reply for"}
            return

        await self._message_repo.delete(old_message)
        await self._message_repo.commit()

        # `before` pins history to what existed up to (and including) the
        # user message being answered - so regenerating an older reply
        # (not just the latest one) doesn't leak later messages into it.
        user_settings = await self._user_service.get_settings(user_id)
        history = await self._load_history_messages(thread_id, before=last_user_message.created_at)
        state = self._build_state(
            user_id=user_id,
            thread_id=thread_id,
            messages=history,
            custom_system_prompt=user_settings.get("system_prompt") or None,
        )

        yield {"type": "start", "thread_id": thread_id}

        full_generation = ""
        current_model: str | None = None
        current_provider: str | None = None
        try:
            async for event in self._graph.stream(state):
                for node_name, update in event.items():
                    if update.get("current_model"):
                        current_model = update["current_model"]
                    if update.get("current_provider"):
                        current_provider = update["current_provider"]
                    if "generation" in update and update.get("generation"):
                        full_generation = update["generation"]
                        yield {"type": "token", "content": update["generation"]}
                    if "tool_results" in update and update.get("tool_results"):
                        yield {"type": "tool_call", "data": update["tool_results"]}
                    if update.get("needs_user_input"):
                        full_generation = update.get("pending_question") or full_generation
                        yield {"type": "message", "content": update.get("pending_question")}
        except Exception as exc:  # noqa: BLE001
            # The old reply was already deleted above - without this, a
            # failed regeneration left the thread with the user's message
            # and no assistant reply at all, not even the original one.
            await self._persist_failed_turn(thread_id, str(exc))
            yield {"type": "error", "content": str(exc)}
            return

        assistant_message = Message(
            thread_id=thread_id,
            role=MessageRole.ASSISTANT,
            content=full_generation,
            model=current_model,
            metadata_={"provider": current_provider},
        )
        await self._message_repo.create(assistant_message)
        await self._message_repo.commit()
        self._schedule_llm_profile_update(user_id, last_user_message.content, full_generation)

        yield {"type": "done", "message_id": str(assistant_message.id)}

    async def _get_last_user_message_before(self, thread_id: str, before: Any) -> Message | None:
        """Find the most recent USER message before a given timestamp in a thread."""
        from sqlalchemy import select

        stmt = (
            select(Message)
            .where(
                Message.thread_id == thread_id,
                Message.role == MessageRole.USER,
                Message.created_at <= before,
            )
            .order_by(Message.created_at.desc())
            .limit(1)
        )
        result = await self._db.execute(stmt)
        return result.scalar_one_or_none()

    def _build_state(
        self,
        user_id: str,
        thread_id: str,
        messages: list[Any],
        requested_model: str | None = None,
        provider: str | None = None,
        custom_system_prompt: str | None = None,
        images: list[str] | None = None,
    ) -> dict[str, Any]:
        """Build the initial graph state.

        The graph is checkpointed per thread_id (MemorySaver), and LangGraph
        merges this dict into whatever was persisted from the *previous*
        turn - any key not set here keeps its old value. `messages` is the
        full thread history rebuilt from the database each turn (see
        `_load_history_messages`), not just this turn's new message - its
        `add_messages` reducer merges by message id, so this replaces stale
        checkpoint entries in place rather than duplicating them. Routing/tool
        fields are NOT meant to accumulate the same way: without explicitly
        zeroing them every turn, a stale `selected_tool`/`detected_tools`
        from a prior message (e.g. "weather") silently reruns against a
        later, unrelated message, and stale `tool_results`/`generation`
        bleed into answers that never asked for them. Everything below
        except the first block must be reset here.
        """
        return {
            "user_id": user_id,
            "thread_id": thread_id,
            "session_id": thread_id,
            "messages": messages,
            "images": images or [],
            "requested_model": requested_model,
            "metadata": {"provider": provider or "auto"},
            "custom_system_prompt": custom_system_prompt,
            "retry_count": 0,
            "max_retries": 2,
            "intent": INTENT_UNKNOWN,
            "route": "direct",
            "selected_tool": None,
            "detected_tools": [],
            "tool_args": {},
            "tool_results": [],
            "tool_request": None,
            "retrieved_documents": [],
            "context": None,
            "citations": [],
            "needs_user_input": False,
            "pending_question": None,
            "generation": None,
            "reflection_feedback": None,
            "is_valid_answer": True,
            "error_state": None,
            "current_model": None,
            "current_provider": None,
            "model_attempts": 0,
        }
