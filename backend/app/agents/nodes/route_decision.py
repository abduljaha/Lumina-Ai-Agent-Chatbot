"""Route decision node - conditional edge routing."""
from __future__ import annotations

import logging
from typing import Any

from app.agents.state import INTENT_ASK_USER, INTENT_CHAT, INTENT_RAG, INTENT_TOOL

logger = logging.getLogger("app")


class RouteDecisionNode:
    """Decides the next route based on the detected intent.

    Returns a route string that the graph uses for conditional edges:
    - "direct": answer directly from the LLM
    - "rag": retrieve documents first, then answer
    - "tool": execute a tool first, then answer
    - "ask_user": ask the user a follow-up question
    """

    async def __call__(self, state: dict[str, Any]) -> dict[str, Any]:
        """Determine the routing decision."""
        intent = state.get("intent", INTENT_CHAT)
        error_state = state.get("error_state")

        if error_state:
            return {"route": "direct"}  # Let the LLM handle errors gracefully

        if intent == INTENT_TOOL:
            return {"route": "tool"}
        if intent == INTENT_RAG:
            return {"route": "rag"}
        if intent == INTENT_ASK_USER:
            return {"route": "ask_user"}
        return {"route": "direct"}

    @staticmethod
    def route_after_validation(state: dict[str, Any]) -> str:
        """Graph edge: route after input validation."""
        error_state = state.get("error_state")
        if error_state:
            return "handle_error"
        return "context_builder"

    @staticmethod
    def route_after_intent(state: dict[str, Any]) -> str:
        """Graph edge: route after intent detection."""
        intent = state.get("intent")
        error_state = state.get("error_state")
        if error_state:
            return "handle_error"
        if intent == INTENT_TOOL:
            return "tool_selection"
        if intent == INTENT_RAG:
            return "rag_retrieval"
        if intent == INTENT_ASK_USER:
            return "ask_user"
        return "llm_node"

    @staticmethod
    def route_after_tool(state: dict[str, Any]) -> str:
        """Graph edge: route after tool execution."""
        if state.get("needs_user_input"):
            return "ask_user"
        return "llm_node"

    @staticmethod
    def route_after_reflection(state: dict[str, Any]) -> str:
        """Graph edge: route after reflection (retry loop)."""
        if not state.get("is_valid_answer", True) and state.get("retry_count", 0) < state.get("max_retries", 2):
            return "llm_node"  # Retry with reflection feedback
        return "formatting"
