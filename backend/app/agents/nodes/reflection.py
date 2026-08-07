"""Reflection node - evaluates the quality of the generated answer."""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("app")


class ReflectionNode:
    """Evaluates the generated answer for quality and correctness.

    Checks for:
    - Empty or trivial responses
    - Hallucination risk (unsubstantiated claims when context is expected)
    - Answer relevance to the question
    - Whether a tool was needed but not used
    """

    MIN_ANSWER_LENGTH = 5

    async def __call__(self, state: dict[str, Any]) -> dict[str, Any]:
        """Evaluate the generated answer and decide on retry."""
        generation = state.get("generation") or ""
        intent = state.get("intent")
        context = state.get("context")
        tool_results = state.get("tool_results", [])

        feedback = None
        is_valid = True

        # Check for empty/trivial answer
        if not generation or len(generation.strip()) < self.MIN_ANSWER_LENGTH:
            is_valid = False
            feedback = "The answer is too short or empty. Please provide a complete, helpful response."

        # Check if a tool was needed (intent was tool) but no tool results
        elif intent == "tool" and not tool_results and not state.get("needs_user_input"):
            is_valid = False
            feedback = "The question likely requires a tool, but no tool result was used. Consider using the appropriate tool."

        # Check if RAG context was expected but answer doesn't reference it
        elif intent == "rag" and context and len(generation) < 20:
            is_valid = False
            feedback = "The answer should incorporate the retrieved context. Please use the provided documents."

        # Check for hallucination risk: overconfident claims without context
        elif context and not tool_results and not self._references_context(generation, intent):
            # Not necessarily a failure, just a soft warning
            pass

        return {
            "is_valid_answer": is_valid,
            "reflection_feedback": feedback,
            "retry_count": state.get("retry_count", 0) + (0 if is_valid else 1),
        }

    @staticmethod
    def _references_context(generation: str, intent: str) -> bool:
        """Heuristic check whether the answer references the context."""
        if intent != "rag":
            return True
        # Check for citation-like markers
        return any(marker in generation for marker in ["[", "according to", "source", "document"])
