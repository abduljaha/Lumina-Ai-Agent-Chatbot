"""Tool selection node - choose and execute tools."""
from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

from app.tools.registry import ToolRegistry

logger = logging.getLogger("app")

# Applied uniformly to every tool call here rather than per-tool, so a tool
# with no timeout/retry logic of its own (wikipedia, web_search's inner
# libraries, ...) still can't hang a whole turn or die on one transient
# blip - this is the single enforcement point for "every tool is reliable"
# instead of duplicating the same wait_for/retry boilerplate in each tool.
_TOOL_TIMEOUT_SECONDS = 20
_MAX_TOOL_ATTEMPTS = 3
_TRANSIENT_ERROR_HINTS = (
    "timeout", "timed out", "connection", "temporarily", "rate limit",
    "rate-limit", "429", "502", "503", "504", "unavailable", "reset by peer",
)

# Tools that should transparently retry against a different tool when the
# preferred one fails outright, rather than just returning nothing. Both
# sides take the same {"query": ...} argument shape, so no remapping is
# needed. serp_search's own "not configured" error message has said
# "falling back to web_search" since it was written (see serp_search.py) -
# this is what actually makes that happen, for every failure mode (quota
# exhausted, bad key, outage), not just the "no key configured" case.
_FALLBACK_TOOLS = {"serp_search": "web_search"}


def _is_transient(result_dict: dict[str, Any]) -> bool:
    """Whether a tool failure looks worth retrying vs. a deterministic one.

    Deterministic failures (bad input, unsupported expression, "no query
    provided") will fail identically on retry - only network/availability
    -shaped errors are worth spending the extra attempts on.

    Prefers an explicit `metadata["transient"]` flag when a tool sets one
    (see serp_search.py, which classifies by exception type/HTTP status
    rather than guessing from message text) - falls back to substring
    matching on the error message for tools that don't set it, since some
    transient exceptions (e.g. httpx connect timeouts) stringify to an
    empty or generic message that no keyword list would ever match.
    """
    metadata = result_dict.get("metadata") or {}
    if "transient" in metadata:
        return bool(metadata["transient"])
    error = result_dict.get("error")
    if not error:
        return False
    lowered = error.lower()
    return any(hint in lowered for hint in _TRANSIENT_ERROR_HINTS)

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

    def __init__(self, tool_registry: ToolRegistry) -> None:
        self._registry = tool_registry

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

        # Run independently-detected tools concurrently (each is its own
        # network call) rather than one after another - a compound query
        # like "time and weather in X" would otherwise pay for two full
        # round-trips back to back.
        results = await asyncio.gather(
            *(self._run_tool_with_fallback(state, tool_name) for tool_name in detected_tools)
        )

        return {
            "tool_results": list(results),
            "selected_tool": detected_tools[0],
            "needs_user_input": False,
        }

    async def _run_tool_with_fallback(self, state: dict[str, Any], tool_name: str) -> dict[str, Any]:
        """Run a tool, transparently retrying against its fallback tool on failure.

        Only applies to tools listed in `_FALLBACK_TOOLS` - everything else
        just runs `_run_tool` directly. This is what makes a SerpAPI outage
        (bad key, exhausted quota, provider downtime) degrade to the free
        web_search tool instead of returning nothing for a live-data question.
        """
        result = await self._run_tool(state, tool_name)
        fallback_name = _FALLBACK_TOOLS.get(tool_name)
        if result.get("success") or not fallback_name or not self._registry.has(fallback_name):
            return result

        logger.warning(
            "Tool '%s' failed (%s), falling back to '%s'",
            tool_name, result.get("error"), fallback_name,
        )
        fallback_result = await self._run_tool(state, fallback_name)
        if fallback_result.get("success"):
            fallback_result["metadata"] = {
                **(fallback_result.get("metadata") or {}),
                "fallback_from": tool_name,
            }
            return fallback_result
        # Both failed - surface the primary tool's error (what was actually
        # asked for), not the fallback's, since it's the more informative one.
        return result

    async def _run_tool(self, state: dict[str, Any], tool_name: str) -> dict[str, Any]:
        """Execute a single tool with a timeout and retries, in the standard result shape.

        Every attempt gets its own `_TOOL_TIMEOUT_SECONDS` budget so a stuck
        network call can't stall the whole turn; failures that look
        transient get up to `_MAX_TOOL_ATTEMPTS` tries total with a short
        backoff, while deterministic failures (bad args, unsupported input)
        return immediately after the first attempt.
        """
        if not self._registry.has(tool_name):
            return {"tool": tool_name, "success": False, "error": f"tool_not_found:{tool_name}"}
        args = self._build_arguments(state, tool_name)

        last_result: dict[str, Any] = {"tool": tool_name, "success": False, "error": "Tool did not run"}
        for attempt in range(1, _MAX_TOOL_ATTEMPTS + 1):
            try:
                result = await asyncio.wait_for(
                    self._registry.invoke(tool_name, **args), timeout=_TOOL_TIMEOUT_SECONDS
                )
                result_dict = result.to_dict()
                result_dict["tool"] = tool_name
                if result_dict.get("success") or not _is_transient(result_dict):
                    return result_dict
                last_result = result_dict
            except asyncio.TimeoutError:
                # A timeout is transient by definition - metadata isn't
                # needed here since _run_tool's own retry loop below (not
                # _is_transient) is what decides to try again in this branch.
                last_result = {
                    "tool": tool_name,
                    "success": False,
                    "error": f"Tool '{tool_name}' timed out after {_TOOL_TIMEOUT_SECONDS}s",
                    "metadata": {"transient": True},
                }
            except Exception as exc:  # noqa: BLE001
                # ToolRegistry.invoke already catches exceptions from inside
                # the tool itself - reaching here means something failed
                # even more fundamentally (e.g. argument construction).
                last_result = {
                    "tool": tool_name,
                    "success": False,
                    "error": f"Tool '{tool_name}' raised an unexpected error: {exc}",
                    "metadata": {"transient": False},
                }

            if attempt < _MAX_TOOL_ATTEMPTS:
                logger.warning(
                    "Tool '%s' attempt %d/%d failed transiently, retrying: %s",
                    tool_name, attempt, _MAX_TOOL_ATTEMPTS, last_result.get("error"),
                )
                await asyncio.sleep(0.5 * attempt)

        return last_result

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
            location = _extract_location(last_content)
            if location:
                base_args["location"] = location
        elif tool_name == "weather":
            location = _extract_location(last_content)
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
