"""Memory retrieval node."""
from __future__ import annotations

import logging
from typing import Any

from app.db.session import async_session_factory
from app.memory.manager import MemoryManager

logger = logging.getLogger("app")


class MemoryRetrievalNode:
    """Retrieves relevant memories and populates the state's memory fields."""

    def __init__(self, memory_manager: MemoryManager | None = None) -> None:
        self._memory = memory_manager

    async def _retrieve(self, user_id: str, thread_id: str | None, query: str | None) -> dict[str, Any]:
        """Retrieve the memory bundle, opening a session if none was injected.

        The graph is a long-lived singleton, so it cannot hold the request-scoped
        session a MemoryManager needs. When no manager is injected this read runs
        in its own short-lived session instead.
        """
        if self._memory is not None:
            return await self._memory.retrieve_for_context(user_id, thread_id=thread_id, query=query)

        async with async_session_factory() as session:
            manager = MemoryManager(session)
            return await manager.retrieve_for_context(user_id, thread_id=thread_id, query=query)

    async def __call__(self, state: dict[str, Any]) -> dict[str, Any]:
        """Retrieve memory context for the current user/thread."""
        user_id = state.get("user_id")
        thread_id = state.get("thread_id")
        if not user_id:
            return {
                "short_term_memory": [],
                "long_term_memory": [],
                "entity_memory": {},
                "user_preferences": {},
            }

        messages = state.get("messages", [])
        query = getattr(messages[-1], "content", None) if messages else None

        try:
            bundle = await self._retrieve(user_id, thread_id, query)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Memory retrieval failed: %s", exc)
            return {
                "short_term_memory": [],
                "long_term_memory": [],
                "entity_memory": {},
                "user_preferences": {},
                "memory_summary": None,
            }

        return {
            "short_term_memory": bundle.get("short_term", []),
            "long_term_memory": bundle.get("long_term", []),
            "entity_memory": bundle.get("entities", {}),
            "semantic_memory": bundle.get("semantic", []),
            "user_preferences": {"preferences": bundle.get("preferences", [])},
            "memory_summary": bundle.get("summary"),
        }
