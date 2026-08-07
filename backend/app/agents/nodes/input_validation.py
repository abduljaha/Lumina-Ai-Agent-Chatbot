"""Input validation node + security guardrails."""
from __future__ import annotations

import logging
from typing import Any

from app.security.guardrails import (
    contains_jailbreak_pattern,
    detect_prompt_injection,
    is_content_filtered,
)

logger = logging.getLogger("app")


class InputValidationNode:
    """Validates and sanitizes user input before processing.

    Applies:
    - Empty input detection
    - Max length enforcement
    - Prompt injection protection
    - Jailbreak detection
    - Content filtering
    """

    MAX_INPUT_LENGTH = 10000

    async def __call__(self, state: dict[str, Any]) -> dict[str, Any]:
        """Validate user input from the last message."""
        messages = state.get("messages", [])
        if not messages:
            return {
                "error_state": "no_messages",
                "intent": "error",
            }

        last_message = messages[-1]
        content = getattr(last_message, "content", "") or ""
        if isinstance(content, str) is False:
            content = str(content)

        # Length validation
        if len(content) > self.MAX_INPUT_LENGTH:
            return {
                "error_state": "input_too_long",
                "intent": "error",
            }

        if not content.strip():
            return {
                "error_state": "empty_input",
                "intent": "error",
            }

        # Security: prompt injection detection
        if detect_prompt_injection(content):
            logger.warning("Prompt injection attempt detected: %s", content[:200])
            return {
                "error_state": "prompt_injection_detected",
                "intent": "error",
                "needs_user_input": True,
            }

        # Security: jailbreak detection
        if contains_jailbreak_pattern(content):
            logger.warning("Jailbreak attempt detected")
            return {
                "error_state": "jailbreak_detected",
                "intent": "error",
            }

        # Content filtering
        if is_content_filtered(content):
            return {
                "error_state": "content_blocked",
                "intent": "error",
            }

        # Store sanitized content
        return {
            "error_state": None,
            "intent": "unknown",
            "metadata": {**state.get("metadata", {}), "input_validated": True},
        }
