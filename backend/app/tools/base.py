"""Base tool protocol and result dataclass."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass
class ToolResult:
    """Standard result shape returned by tools."""

    success: bool
    output: Any = None
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a dict for graph state / API responses."""
        return {
            "success": self.success,
            "output": self.output,
            "error": self.error,
            "metadata": self.metadata,
        }


@runtime_checkable
class BaseTool(Protocol):
    """Protocol that every tool must implement."""

    name: str
    description: str

    async def invoke(self, **kwargs: Any) -> ToolResult:
        """Execute the tool with the given arguments."""
        raise NotImplementedError

    def to_dict(self) -> dict[str, Any]:
        """Return tool metadata (name, description, args schema)."""
        raise NotImplementedError
