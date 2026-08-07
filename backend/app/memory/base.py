"""Base memory store interface and memory item dataclass."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from app.db.models import MemoryType


@dataclass
class MemoryItem:
    """A single memory entry."""

    content: str
    memory_type: MemoryType
    key: str | None = None
    importance: float = 0.5
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str | None = None
    expires_at: str | None = None


class BaseMemoryStore(Protocol):
    """Protocol for memory stores."""

    async def add(self, item: MemoryItem, user_id: str) -> None:
        """Add a memory item for a user."""
        ...

    async def retrieve(self, user_id: str, memory_type: MemoryType | None = None, limit: int = 50) -> list[MemoryItem]:
        """Retrieve memory items for a user."""
        ...

    async def search(self, query: str, user_id: str, limit: int = 10) -> list[MemoryItem]:
        """Semantic search over memory items."""
        ...

    async def delete(self, memory_id: str, user_id: str) -> None:
        """Delete a memory item."""
        ...

    async def clear(self, user_id: str, memory_type: MemoryType | None = None) -> None:
        """Clear memory items for a user."""
        ...
