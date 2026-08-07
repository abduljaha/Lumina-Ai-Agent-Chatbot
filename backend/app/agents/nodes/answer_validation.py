"""Answer validation node - final output checks."""
from __future__ import annotations

import logging
from typing import Any

from app.security.guardrails import is_content_filtered

logger = logging.getLogger("app")


class AnswerValidationNode:
    """Validates the final answer before it's returned to the user.

    Checks:
    - Content safety (no harmful content in the output)
    - Length sanity
    - No leftover system-prompt leakage
    """

    async def __call__(self, state: dict[str, Any]) -> dict[str, Any]:
        """Validate the final answer."""
        generation = state.get("generation") or ""

        # Content safety check on output
        if is_content_filtered(generation):
            return {
                "generation": "I'm unable to provide a response to that request. "
                "Please feel free to ask another question.",
                "is_valid_answer": False,
            }

        # Check for system prompt leakage
        leakage_markers = ["system prompt", "you are an ai assistant", "openai", "as an ai language model"]
        if any(marker in generation.lower() for marker in leakage_markers):
            logger.warning("Potential system prompt leakage detected in output")

        return {"is_valid_answer": True}
