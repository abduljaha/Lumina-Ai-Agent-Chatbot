"""Tool selection node - choose and execute tools."""
from __future__ import annotations

import logging
import re
from typing import Any

from app.tools.executor import ToolExecutor
from app.tools.registry import ToolRegistry

logger = logging.getLogger("app")

# Captures the place name after a preposition, stopping at sentence-ending
# punctuation or a conjunction so "...time and weather in Paris and London"
# still yields a sane match rather than swallowing the rest of the sentence.
_LOCATION_PATTERN = re.compile(
    r"\b(?:in|for|at)\b\s+([a-z][a-z\s,'-]*?)(?:[.?!]|\s+(?:and|or)\s+|$)",
    re.IGNORECASE,
)


def _extract_location(text: str) -> str:
    """Pull a place name out of a free-form query, e.g. '... in Madhapur, Hyderabad.'"""
    match = _LOCATION_PATTERN.search(text)
    return match.group(1).strip().rstrip(",") if match else ""


# Splits a compound multi-tool query into clauses for LOCATION SCOPING only
# (kept separate from `_CLAUSE_SPLIT_PATTERN` below, which is for isolating
# the search-query clause and must not change behavior there). A bare comma
# is deliberately NOT a boundary on its own - "weather in Madhapur,
# Hyderabad" needs that comma to stay inside one clause - but a comma
# immediately followed by what looks like the start of a new question
# ("what", "is", "and what", ...) is: "weather in bangalore, what time is
# it in tokyo" is two questions, not one compound place name.
_LOCATION_CLAUSE_BOUNDARY = re.compile(
    r"[.;]\s+|\s+(?:and|but)\s+|,\s*(?:and\s+)?(?=(?:what|when|is|does|will|how)\b)",
    re.IGNORECASE,
)
_WEATHER_KEYWORDS = re.compile(r"\b(weather|temperature|forecast|rain|snow|humid|climate)\b", re.IGNORECASE)
_TIME_KEYWORDS = re.compile(r"\b(time|date|clock)\b", re.IGNORECASE)
_LOCATION_KEYWORDS_BY_TOOL = {"weather": _WEATHER_KEYWORDS, "current_time": _TIME_KEYWORDS}


def _extract_location_for_tool(text: str, tool_name: str) -> str:
    """Extract a location scoped to the clause that actually mentions this tool.

    `_extract_location` always returns the FIRST "in X" match in the whole
    message - fine for a single-location query, but a compound one like
    "weather in Bangalore, what time is it in Tokyo" has two "in X" clauses,
    one per tool, and both the weather and current_time argument-building
    calls would otherwise land on the same (wrong, for one of them) match.
    Splits into clauses first and searches only the one containing this
    tool's own keywords; falls back to whole-text extraction (unchanged
    behavior) when there's nothing to disambiguate.
    """
    keyword_pattern = _LOCATION_KEYWORDS_BY_TOOL.get(tool_name)
    if keyword_pattern is not None:
        clauses = [c.strip() for c in _LOCATION_CLAUSE_BOUNDARY.split(text) if c.strip()]
        if len(clauses) > 1:
            matching = [c for c in clauses if keyword_pattern.search(c)]
            if matching:
                scoped = _extract_location(matching[0])
                if scoped:
                    return scoped
    return _extract_location(text)


# Requires at least one operator between digits, so a stray number ("top 5
# tips") doesn't get mistaken for an expression - only used as a candidate
# if it also contains +-*/^%.
_MATH_EXPRESSION_PATTERN = re.compile(r"[-+]?\d[\d\s+\-*/^%().]*[\d)]")


def _extract_math_expression(text: str) -> str:
    """Pull just the arithmetic expression out of a compound query.

    "what's the weather in X, and what is 458*37" used to hand the
    calculator the ENTIRE sentence (prefix-stripping only handles the
    expression being at the very start of the message), which reliably
    produced a syntax error for anything but a bare "calculate ..." message.
    """
    candidates = [
        m.group(0).strip()
        for m in _MATH_EXPRESSION_PATTERN.finditer(text)
        if any(op in m.group(0) for op in "+-*/^%")
    ]
    return max(candidates, key=len) if candidates else ""


# Conservative on purpose - only splits on clear clause boundaries
# (conjunctions, sentence-ending punctuation), never mid-clause, since a
# mis-split query is worse than an unsplit one.
_CLAUSE_SPLIT_PATTERN = re.compile(r"\s+(?:and|but)\s+|[.;]\s+", re.IGNORECASE)
_OTHER_TOOL_KEYWORDS = re.compile(
    r"\b(weather|temperature|forecast|time|calculate|compute)\b", re.IGNORECASE
)


def _extract_search_query(text: str, other_detected_tools: list[str]) -> str:
    """Isolate the search-relevant clause from a compound question.

    Only kicks in when web_search/serp_search was detected *alongside*
    another tool (e.g. "weather in Paris and today's gold price") - a
    single-tool query already IS the search query, so it's returned
    unchanged in the common case. Without this, a compound question sent
    the entire sentence - including the unrelated weather/time/calculator
    clause - as the search query, degrading result relevance.
    """
    if not other_detected_tools:
        return text
    clauses = [c.strip() for c in _CLAUSE_SPLIT_PATTERN.split(text) if c.strip()]
    if len(clauses) <= 1:
        return text
    # Prefer whichever clause(s) don't look like they belong to one of the
    # other detected tools; fall back to the last clause (where a trailing
    # "...and what's today's gold price" addendum usually lands) if every
    # clause happens to contain one of those keywords.
    candidates = [c for c in clauses if not _OTHER_TOOL_KEYWORDS.search(c)]
    return candidates[-1] if candidates else clauses[-1]


class ToolSelectionNode:
    """Selects and executes the appropriate tool(s) based on intent.

    A single message can need more than one live-data tool (e.g. "what's
    the time and weather in Paris"), so this executes every tool detected
    by intent_detection, not just the first one.
    """

    def __init__(self, tool_registry: ToolRegistry, tool_executor: ToolExecutor | None = None) -> None:
        self._registry = tool_registry
        # Falls back to a private executor (e.g. for tests constructing this
        # node directly) - production wiring always shares one process-wide
        # instance with LLMNode via AgentGraph/AppContainer, see executor.py.
        self._executor = tool_executor or ToolExecutor(tool_registry)

    async def __call__(self, state: dict[str, Any]) -> dict[str, Any]:
        """Execute the selected tool(s) and return results."""
        selected_tool = state.get("selected_tool")
        detected_tools = state.get("detected_tools") or ([selected_tool] if selected_tool else [])
        if not detected_tools:
            return {"tool_results": [], "needs_user_input": False}

        # ask_user is a request for clarification, not a data lookup - it
        # short-circuits the whole turn rather than running alongside others.
        if "ask_user" in detected_tools:
            args = self._build_arguments(state, "ask_user")
            question = args.get("question") or "Could you clarify what you'd like help with?"
            return {
                "needs_user_input": True,
                "pending_question": question,
                "tool_results": [],
            }

        # Independently-detected tools run concurrently (each is its own
        # network call) rather than one after another - a compound query
        # like "time and weather in X" would otherwise pay for two full
        # round-trips back to back. Timeout/retry/transient-fallback/caching/
        # rate-limiting all live in ToolExecutor now, shared with LLMNode's
        # native function-calling path so both behave identically.
        calls = [(tool_name, self._build_arguments(state, tool_name)) for tool_name in detected_tools]
        results = await self._executor.run_many(calls, user_id=state.get("user_id"))

        return {
            "tool_results": results,
            "selected_tool": detected_tools[0],
            "needs_user_input": False,
        }

    def _build_arguments(self, state: dict[str, Any], tool_name: str) -> dict[str, Any]:
        """Build arguments for the given tool from state."""
        messages = state.get("messages", [])
        last_content = ""
        if messages:
            last_content = getattr(messages[-1], "content", "") or ""

        base_args = {"user_id": state.get("user_id")}

        if tool_name == "calculator":
            expr = _extract_math_expression(last_content)
            if not expr:
                # Fall back to prefix-stripping for messages the regex can't
                # isolate a standalone expression from (e.g. spelled-out
                # word problems with no bare digit+operator run).
                expr = last_content
                for prefix in ["calculate ", "compute ", "what is ", "how much is ", "math:"]:
                    if expr.lower().startswith(prefix):
                        expr = expr[len(prefix):]
                        break
            base_args["expression"] = expr.strip()
        elif tool_name == "current_time":
            location = _extract_location_for_tool(last_content, "current_time")
            if location:
                base_args["location"] = location
        elif tool_name == "weather":
            location = _extract_location_for_tool(last_content, "weather")
            if not location:
                # Fall back to prefix-stripping for phrasings the
                # preposition pattern doesn't catch, e.g. "weather Paris".
                for prefix in ["weather in ", "weather for ", "temperature in ", "forecast for "]:
                    if last_content.lower().startswith(prefix):
                        location = last_content[len(prefix):].strip()
                        break
            if not location:
                # No extractable place name - fall back to the user's saved
                # location (e.g. "I live in Hyderabad") rather than passing
                # the whole unrelated sentence as a "city" and geocoding it,
                # which reliably 404s and surfaces a confusing tool error.
                # entity_memory stores "key: value" (see MemoryManager.
                # upsert_entity), so pull just the value half.
                raw = (state.get("entity_memory") or {}).get("location", "")
                location = raw.split(":", 1)[1].strip() if ":" in raw else raw.strip()
            if location:
                base_args["city"] = location.strip()
        elif tool_name in ("web_search", "serp_search"):
            other_tools = [t for t in (state.get("detected_tools") or []) if t != tool_name]
            base_args["query"] = _extract_search_query(last_content, other_tools)
        elif tool_name == "wikipedia":
            base_args["query"] = last_content
        elif tool_name == "knowledge_base_search":
            base_args["query"] = last_content
        elif tool_name == "ask_user":
            # No LLM call happens at this point in the pipeline (that's the
            # next node), so this can't generate a bespoke question - echoing
            # the user's own words back isn't a real clarifying question, so
            # frame it as one instead.
            base_args["question"] = (
                f'I\'d like to help with "{last_content.strip()}" - could you share a bit more, '
                "like what options you're weighing or what matters most to you?"
            )

        return base_args
