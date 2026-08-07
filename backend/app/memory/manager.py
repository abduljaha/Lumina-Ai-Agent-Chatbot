"""Memory manager - orchestrates all memory stores and compression."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.background import track as _track_background
from app.db.models import Memory, MemoryType
from app.memory.base import MemoryItem
from app.repositories import MemoryRepository

logger = logging.getLogger("app")


def _is_expired(expires_at: datetime | None, now: datetime) -> bool:
    """Return whether a memory has expired.

    SQLite hands back naive datetimes, so an unqualified comparison against an
    aware `now` raises TypeError. Naive values are read as UTC.
    """
    if expires_at is None:
        return False
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    return expires_at < now


class MemoryManager:
    """Centralized memory system supporting all memory types.

    Implements short-term, long-term, conversation, summarization, entity,
    semantic, user-preference, and thread memory with automatic compression.
    """

    SHORT_TERM_TTL_HOURS = 24
    MAX_SHORT_TERM_ITEMS = 50
    COMPRESSION_THRESHOLD = 30

    def __init__(self, db: AsyncSession, profile_index: Any = None) -> None:
        self._db = db
        self._repo = MemoryRepository(db)
        # Lazily resolved rather than imported at module scope: this file is
        # imported before the DI container is fully wired in some paths
        # (e.g. auth.py during registration), and semantic indexing is an
        # enhancement, not a hard dependency - MemoryManager must still work
        # if the embedding backend fails to construct for any reason.
        self._profile_index = profile_index

    def _get_profile_index(self) -> Any:
        if self._profile_index is None:
            try:
                from app.core.container import app_container

                self._profile_index = app_container.get_profile_memory_index()
            except Exception as exc:  # noqa: BLE001
                logger.warning("Profile memory semantic index unavailable: %s", exc)
        return self._profile_index

    def _index_entity_background(self, user_id: str, memory_id: str, key: str, content: str) -> None:
        """Schedule semantic (re-)indexing without blocking the caller.

        Embedding a fact only touches the embedder/vector store, not the
        request's DB session, so it's safe to let this keep running after
        the HTTP response has already been sent.
        """
        index = self._get_profile_index()
        if index is None:
            return
        _track_background(index.index_fact(user_id, memory_id, key, content))

    # ------------------------------------------------------------------
    # Add operations
    # ------------------------------------------------------------------
    async def add(self, user_id: str, content: str, memory_type: MemoryType, **kwargs: Any) -> Memory:
        """Add a memory item for a user."""
        item = Memory(
            user_id=user_id,
            content=content,
            memory_type=memory_type,
            key=kwargs.get("key"),
            importance=kwargs.get("importance", 0.5),
            metadata_=kwargs.get("metadata", {}),
            thread_id=kwargs.get("thread_id"),
            expires_at=self._compute_expiry(memory_type),
        )
        await self._repo.create(item)
        await self._repo.commit()
        await self._auto_compress_if_needed(user_id, memory_type)
        return item

    async def add_short_term(self, user_id: str, content: str, **kwargs: Any) -> Memory:
        """Add short-term (working) memory."""
        return await self.add(user_id, content, MemoryType.SHORT_TERM, **kwargs)

    async def add_long_term(self, user_id: str, content: str, **kwargs: Any) -> Memory:
        """Add long-term memory."""
        return await self.add(user_id, content, MemoryType.LONG_TERM, **kwargs)

    async def add_entity(self, user_id: str, entity: str, fact: str, **kwargs: Any) -> Memory:
        """Add entity memory: entity -> fact."""
        item = await self.add(
            user_id,
            content=f"{entity}: {fact}",
            memory_type=MemoryType.ENTITY,
            key=entity.lower(),
            **kwargs,
        )
        self._index_entity_background(user_id, str(item.id), entity.lower(), item.content)
        return item

    async def add_preference(self, user_id: str, preference: str, **kwargs: Any) -> Memory:
        """Add a user preference memory."""
        return await self.add(
            user_id, preference, MemoryType.USER_PREFERENCE, **kwargs
        )

    async def upsert_entity(self, user_id: str, entity: str, fact: str, **kwargs: Any) -> Memory:
        """Add or update a global entity fact, keyed by entity name.

        Unlike `add_entity`, this won't create a new duplicate row every time
        the user restates the same fact (e.g. their name) - it updates the
        existing one in place, or replaces it if the value has changed.
        """
        key = entity.lower()
        existing = await self._repo.get_by_key(user_id, MemoryType.ENTITY.value, key)
        content = f"{entity}: {fact}"
        if existing:
            if existing.content != content:
                existing.content = content
                await self._repo.update(existing)
                await self._repo.commit()
                self._index_entity_background(user_id, str(existing.id), key, content)
            return existing
        return await self.add_entity(user_id, entity, fact, **kwargs)

    async def add_preference_if_new(self, user_id: str, preference: str, **kwargs: Any) -> Memory | None:
        """Add a preference memory only if this exact statement isn't already stored."""
        existing = await self._repo.list_for_user(user_id, MemoryType.USER_PREFERENCE.value, limit=200)
        if any(m.content == preference for m in existing):
            return None
        return await self.add_preference(user_id, preference, **kwargs)

    async def add_summary(self, user_id: str, summary: str, thread_id: str | None = None) -> Memory:
        """Store a conversation summary."""
        return await self.add(
            user_id, summary, MemoryType.SUMMARIZATION, thread_id=thread_id, importance=0.9
        )

    async def add_semantic(self, user_id: str, content: str, **kwargs: Any) -> Memory:
        """Add semantic memory (knowledge statement)."""
        return await self.add(user_id, content, MemoryType.SEMANTIC, **kwargs)

    async def add_thread_memory(self, user_id: str, thread_id: str, content: str, **kwargs: Any) -> Memory:
        """Add thread-scoped memory."""
        return await self.add(
            user_id, content, MemoryType.THREAD, thread_id=thread_id, **kwargs
        )

    # ------------------------------------------------------------------
    # Retrieval operations
    # ------------------------------------------------------------------
    async def retrieve(self, user_id: str, memory_type: MemoryType | None = None, limit: int = 50) -> list[Memory]:
        """Retrieve memories for a user."""
        return await self._repo.list_for_user(
            user_id, memory_type.value if memory_type else None, limit
        )

    # Below this many facts, just send everything - simpler and safer than
    # semantic filtering (a "what's my name" question is not semantically
    # close to a stored "name: Abdul" fact, so filtering too eagerly can
    # hide facts the user obviously still wants recalled). Semantic
    # filtering only starts pulling its weight once the fact list is long
    # enough that dumping all of it would bloat every prompt.
    SEMANTIC_ENTITY_THRESHOLD = 12
    # Keys that stay in context regardless of semantic relevance - core
    # identity a reply should almost always be able to draw on.
    ALWAYS_INCLUDE_KEYS = {"name", "age", "email"}

    async def retrieve_for_context(
        self, user_id: str, thread_id: str | None = None, limit: int = 30, query: str | None = None
    ) -> dict[str, Any]:
        """Retrieve a rich memory context bundle for the graph state.

        Returns categorized memories: short-term, long-term, entities,
        preferences, semantic, thread-scoped, and the latest summary.

        `query` (typically the user's current message) enables semantic
        filtering of `entities` when there are enough of them that sending
        all of them would bloat the prompt - see SEMANTIC_ENTITY_THRESHOLD.
        """
        all_memories = await self._repo.list_for_user(user_id, limit=200)
        now = datetime.now(timezone.utc)

        bundle: dict[str, Any] = {
            "short_term": [],
            "long_term": [],
            "entities": {},
            "preferences": [],
            "semantic": [],
            "thread": [],
            "summary": None,
        }

        for m in all_memories:
            # Skip expired short-term memory
            if m.memory_type == MemoryType.SHORT_TERM and _is_expired(m.expires_at, now):
                continue

            if m.memory_type == MemoryType.SHORT_TERM:
                bundle["short_term"].append(m.content)
            elif m.memory_type == MemoryType.LONG_TERM:
                bundle["long_term"].append({"content": m.content, "importance": m.importance})
            elif m.memory_type == MemoryType.ENTITY:
                bundle["entities"][m.key or m.content.split(":")[0]] = m.content
            elif m.memory_type == MemoryType.USER_PREFERENCE:
                bundle["preferences"].append(m.content)
            elif m.memory_type == MemoryType.SEMANTIC:
                bundle["semantic"].append(m.content)
            elif m.memory_type == MemoryType.THREAD and thread_id and m.thread_id == thread_id:
                bundle["thread"].append(m.content)
            elif m.memory_type == MemoryType.SUMMARIZATION:
                # Keep the most recent summary
                bundle["summary"] = m.content

        # Sort short-term by recency, truncate
        bundle["short_term"] = bundle["short_term"][-self.MAX_SHORT_TERM_ITEMS:]

        if query and len(bundle["entities"]) > self.SEMANTIC_ENTITY_THRESHOLD:
            index = self._get_profile_index()
            if index is not None:
                relevant_contents = set(await index.search(user_id, query, top_k=10))
                if relevant_contents:
                    bundle["entities"] = {
                        k: v
                        for k, v in bundle["entities"].items()
                        if k in self.ALWAYS_INCLUDE_KEYS or v in relevant_contents
                    }

        return bundle

    async def search(self, query: str, user_id: str, limit: int = 10) -> list[Memory]:
        """Simple keyword search over memories (semantic search in RAG layer)."""
        all_memories = await self._repo.list_for_user(user_id, limit=500)
        query_lower = query.lower()
        scored = []
        for m in all_memories:
            if query_lower in m.content.lower():
                scored.append((m.importance, m))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [m for _, m in scored[:limit]]

    async def update(
        self,
        memory_id: str,
        user_id: str,
        content: str | None = None,
        importance: float | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Memory | None:
        """Update a memory's content/importance/metadata in place.

        Same ownership check as `delete` - returns None (rather than
        raising) if the memory doesn't exist or belongs to someone else, so
        the caller can turn that into a 404 without leaking which case it was.
        """
        memory = await self._repo.get(memory_id)
        if not memory or memory.user_id != user_id:
            return None
        if content is not None:
            memory.content = content
        if importance is not None:
            memory.importance = importance
        if metadata is not None:
            memory.metadata_ = metadata
        await self._repo.update(memory)
        await self._repo.commit()
        if memory.memory_type == MemoryType.ENTITY and content is not None:
            self._index_entity_background(user_id, str(memory.id), memory.key or "", memory.content)
        return memory

    async def delete_entity_by_key(self, user_id: str, key: str) -> bool:
        """Delete a global entity fact by its key (e.g. "employer").

        Complements `delete()` (which needs a memory row id) for callers
        that only know the key - the LLM-driven extractor names facts to
        forget by key, not id, since it never sees row ids.
        """
        existing = await self._repo.get_by_key(user_id, MemoryType.ENTITY.value, key.lower())
        if not existing:
            return False
        await self.delete(str(existing.id), user_id)
        return True

    async def delete(self, memory_id: str, user_id: str) -> None:
        """Delete a specific memory.

        Ownership is checked here (`memory.user_id == user_id`) rather than
        trusting the caller - this is the one place deletion actually
        happens, so it's the enforcement point that keeps one user from
        deleting another's memory even if a route ever forgets to check.
        """
        memory = await self._repo.get(memory_id)
        if memory and memory.user_id == user_id:
            await self._repo.delete(memory)
            await self._repo.commit()
            if memory.memory_type == MemoryType.ENTITY:
                index = self._get_profile_index()
                if index is not None:
                    await index.remove_fact(str(memory.id))

    async def clear(self, user_id: str, memory_type: MemoryType | None = None) -> None:
        """Clear memories for a user, optionally by type."""
        memories = await self._repo.list_for_user(
            user_id, memory_type.value if memory_type else None
        )
        for memory in memories:
            await self._repo.delete(memory)
        await self._repo.commit()
        index = self._get_profile_index()
        if index is not None:
            entity_ids = [str(m.id) for m in memories if m.memory_type == MemoryType.ENTITY]
            if entity_ids:
                await asyncio.gather(*(index.remove_fact(mid) for mid in entity_ids))

    # ------------------------------------------------------------------
    # Compression / summarization
    # ------------------------------------------------------------------
    async def _auto_compress_if_needed(self, user_id: str, memory_type: MemoryType) -> None:
        """Automatically compress short-term memory when it grows large."""
        if memory_type != MemoryType.SHORT_TERM:
            return
        short_term = await self._repo.list_for_user(user_id, MemoryType.SHORT_TERM.value)
        if len(short_term) > self.COMPRESSION_THRESHOLD:
            await self.compress_short_term(user_id)

    async def compress_short_term(self, user_id: str) -> str | None:
        """Compress short-term memory into a long-term summary."""
        short_term = await self._repo.list_for_user(user_id, MemoryType.SHORT_TERM.value)
        if not short_term:
            return None

        content_items = [m.content for m in short_term]
        summary = self._summarize_items(content_items)

        # Store as long-term memory
        await self.add(
            user_id,
            f"Summary: {summary}",
            MemoryType.LONG_TERM,
            importance=0.8,
            metadata={"source": "compressed_short_term"},
        )
        # Clear short-term
        for memory in short_term:
            await self._repo.delete(memory)
        await self._repo.commit()
        return summary

    def _summarize_items(self, items: list[str]) -> str:
        """Create a concise summary of memory items.

        In production this uses the LLM; here a deterministic heuristic
        is provided to avoid an external dependency in the memory path.
        """
        if not items:
            return ""
        if len(items) == 1:
            return items[0]
        # Simple concatenation heuristic
        joined = "; ".join(items)
        if len(joined) <= 500:
            return joined
        return joined[:497] + "..."

    def _compute_expiry(self, memory_type: MemoryType) -> datetime | None:
        """Compute expiry for short-term memories."""
        if memory_type == MemoryType.SHORT_TERM:
            return datetime.now(timezone.utc) + timedelta(hours=self.SHORT_TERM_TTL_HOURS)
        return None
