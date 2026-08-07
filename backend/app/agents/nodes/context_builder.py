"""Context builder node - assemble conversation context."""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("app")


class ContextBuilderNode:
    """Builds the full context for the LLM request.

    Combines:
    - Recent message history (sliding window)
    - User preferences
    - Retrieved documents (RAG)
    - Memory summaries
    """

    MAX_HISTORY_MESSAGES = 20

    async def __call__(self, state: dict[str, Any]) -> dict[str, Any]:
        """Construct the context bundle from state."""
        messages = state.get("messages", [])
        history = messages[-self.MAX_HISTORY_MESSAGES:]  # Sliding window

        # Serialize history for the prompt
        history_text = []
        for msg in history:
            role = getattr(msg, "type", None) or getattr(msg, "role", "user")
            content = getattr(msg, "content", "")
            history_text.append(f"{role}: {content}")

        user_prefs = state.get("user_preferences", {})
        pref_text = "; ".join(user_prefs.get("preferences", [])) if isinstance(user_prefs, dict) else ""

        retrieved = state.get("retrieved_documents", [])
        doc_text = ""
        if retrieved:
            doc_text = "\n\n".join(
                f"[Document {i}]: {doc.get('content', '')}" for i, doc in enumerate(retrieved)
            )

        context_parts = []
        if pref_text:
            context_parts.append(f"User Preferences: {pref_text}")
        if doc_text:
            context_parts.append(f"Retrieved Documents:\n{doc_text}")
        if state.get("memory_summary"):
            context_parts.append(f"Conversation Summary: {state['memory_summary']}")

        context = "\n".join(context_parts) if context_parts else None

        return {
            "context": context,
            "metadata": {
                **state.get("metadata", {}),
                "history_length": len(history_text),
                "has_context": bool(context),
            },
        }
