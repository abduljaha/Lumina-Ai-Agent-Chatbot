"""Prompt templates for the conversational agent.

Centralizes every piece of prompt text the LLM node sends - the base system
prompt and the pieces layered onto it (user preferences, known entities,
custom instructions, retrieved context, tool results, reflection feedback),
plus the user prompt itself - so prompt engineering happens in one place
instead of being scattered as inline string literals through node logic.
"""
from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------
SYSTEM_PROMPT_BASE = (
    "You are a helpful, accurate, and concise AI assistant.\n"
    "If a 'Tool results' section appears below, that data was fetched for this exact "
    "question, so use it directly and confidently instead of deflecting to it being "
    "unavailable. When a calculator result appears, briefly explain how you reached it.\n"
    "For anything whose answer could have changed after your training cutoff or "
    "depends on the current date - release/availability status, current events, "
    "prices, schedules, scores, whether something has happened 'yet' - do not guess "
    "from memory even if you recall related facts. If no tool result answers it, say "
    "plainly that you don't have current information on it rather than stating a "
    "guessed date, status, or outcome as if it were confirmed.\n"
    "For stable, non-time-sensitive facts, answer from your own knowledge normally. "
    "If you don't know something and no tool result covers it, say so honestly rather than guessing."
)

SYSTEM_PROMPT_PREFERENCES_TEMPLATE = "User preferences: {preferences}"

SYSTEM_PROMPT_ENTITIES_TEMPLATE = "Known facts about the user: {entities}"

SYSTEM_PROMPT_CUSTOM_INSTRUCTIONS_TEMPLATE = (
    "User's custom instructions (follow these unless unsafe or illegal):\n{instructions}"
)


def build_system_prompt(state: dict[str, Any]) -> str:
    """Assemble the full system prompt from the base instructions plus context.

    Layers, in order: base instructions -> user preferences -> known entities
    -> the user's own custom instructions (Settings > System Prompt), which
    is deliberately layered last so it reads as refinement on top of the
    baseline behavior rather than a replacement for it.
    """
    parts = [SYSTEM_PROMPT_BASE]

    prefs = state.get("user_preferences", {})
    if prefs and isinstance(prefs, dict):
        pref_list = prefs.get("preferences", [])
        if pref_list:
            parts.append(SYSTEM_PROMPT_PREFERENCES_TEMPLATE.format(preferences="; ".join(pref_list)))

    entities = state.get("entity_memory", {})
    if entities:
        entity_text = "; ".join(f"{k}: {v}" for k, v in entities.items())
        parts.append(SYSTEM_PROMPT_ENTITIES_TEMPLATE.format(entities=entity_text))

    custom_prompt = state.get("custom_system_prompt")
    if custom_prompt:
        parts.append(SYSTEM_PROMPT_CUSTOM_INSTRUCTIONS_TEMPLATE.format(instructions=custom_prompt))

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# User prompt
# ---------------------------------------------------------------------------
# Pass-through by default - kept as an explicit template (rather than using
# the raw message inline) so any future need to wrap the user's message
# (e.g. adding formatting instructions or few-shot framing) has a single,
# obvious place to change instead of being buried in node logic.
USER_PROMPT_TEMPLATE = "{content}"


def build_user_prompt(content: str) -> str:
    """Build the user-turn content sent to the LLM from the raw user message."""
    return USER_PROMPT_TEMPLATE.format(content=content)


# ---------------------------------------------------------------------------
# Auxiliary context injected as additional system-role turns
# ---------------------------------------------------------------------------
CONTEXT_TEMPLATE = "Context:\n{context}"

TOOL_RESULT_SUCCESS_LINE_TEMPLATE = "- {tool} (live, fetched just now): {output}"
TOOL_RESULT_FAILURE_LINE_TEMPLATE = "- {tool} failed ({error}) - tell the user this specific lookup didn't work, don't claim you have no such capability at all"

TOOL_RESULTS_TEMPLATE = "Tool results for this question:\n{results}"

REFLECTION_FEEDBACK_TEMPLATE = (
    "Previous answer was insufficient. Feedback: {feedback}. Please improve your answer."
)


def build_context_message(context: str) -> str:
    """Build the system-role message that injects retrieved/RAG context."""
    return CONTEXT_TEMPLATE.format(context=context)


def build_tool_results_message(tool_results: list[dict[str, Any]]) -> str:
    """Build the system-role message summarizing tool execution results."""
    lines = []
    for result in tool_results:
        tool = result.get("tool", "unknown")
        if result.get("success", True):
            lines.append(TOOL_RESULT_SUCCESS_LINE_TEMPLATE.format(tool=tool, output=result.get("output")))
        else:
            lines.append(TOOL_RESULT_FAILURE_LINE_TEMPLATE.format(tool=tool, error=result.get("error")))
    return TOOL_RESULTS_TEMPLATE.format(results="\n".join(lines))


def build_reflection_feedback_message(feedback: str) -> str:
    """Build the system-role message relaying reflection feedback on a retry."""
    return REFLECTION_FEEDBACK_TEMPLATE.format(feedback=feedback)
