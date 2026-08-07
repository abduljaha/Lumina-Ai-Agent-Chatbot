"""Ask User tool - requests clarification from the user."""
from __future__ import annotations

from typing import Any

from app.tools.base import ToolResult


class AskUserTool:
    """Asks the user a follow-up question when information is missing."""

    name = "ask_user"
    description = "Ask the user a clarifying or follow-up question when information is missing or ambiguous."

    async def invoke(self, question: str = "", **kwargs: Any) -> ToolResult:
        """Request a follow-up from the user."""
        if not question:
            return ToolResult(success=False, error="No question provided")
        return ToolResult(
            success=True,
            output=None,
            metadata={"question": question, "needs_user_input": True, "pending": True},
        )

    def to_dict(self) -> dict[str, Any]:
        """Return tool metadata."""
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {"type": "string", "description": "The follow-up question to ask the user"},
                },
                "required": ["question"],
            },
        }
