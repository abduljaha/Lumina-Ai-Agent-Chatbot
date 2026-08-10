"""Unified tool-execution engine: timeouts, retries, fallback tools, a
result cache, per-user rate limiting, and duplicate-call suppression - used
by both tool-invocation paths in the graph (`ToolSelectionNode`'s regex-
routed fast path and `LLMNode`'s native function-calling path) so a tool
behaves identically - same reliability guarantees, same performance
characteristics - no matter which one triggered it.

Before this, `LLMNode._execute_tool_calls` ran tools in a bare sequential
loop with no timeout, no retry, and no fallback - a transient failure or a
compound "weather in X and the latest news" native tool-call round would
both behave far worse than the exact same request routed through
`ToolSelectionNode`. There is now exactly one place tool-execution
reliability logic lives.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from app.tools.registry import ToolRegistry

logger = logging.getLogger("app")

_TOOL_TIMEOUT_SECONDS = 20
_MAX_TOOL_ATTEMPTS = 3
_RETRY_BACKOFF_SECONDS = 0.5
_TRANSIENT_ERROR_HINTS = (
    "timeout", "timed out", "connection", "temporarily", "rate limit",
    "rate-limit", "429", "502", "503", "504", "unavailable", "reset by peer",
)

# Tools that should transparently retry against a different tool when the
# preferred one fails outright. Both sides take the same {"query": ...}
# argument shape, so no remapping is needed.
_FALLBACK_TOOLS = {"serp_search": "web_search"}

# How long a successful result may be reused for an identical call - both
# within one turn's multi-tool/multi-round execution AND across different
# users/turns hitting the same query shortly after each other (a real
# latency/API-call win for a shared external service like Open-Meteo or
# SerpAPI). 0 means "never cache this tool":
#  - current_time: caching would silently serve stale wall-clock time,
#    which is exactly the "never return stale data" bug this tool exists
#    to avoid - not worth even a few seconds of staleness.
#  - knowledge_base_search: results are scoped to a specific user/thread's
#    documents - a process-wide cache keyed only on (tool, args) would leak
#    one user's document snippets to another user asking a similarly-worded
#    question.
#  - python_executor: may have side effects or non-deterministic output
#    (random, time-based) - replaying a cached result would be wrong.
#  - ask_user: not a data lookup at all.
_CACHE_TTL_SECONDS: dict[str, float] = {
    "calculator": 300,
    "wikipedia": 300,
    "weather": 90,
    "web_search": 30,
    "serp_search": 30,
    "current_time": 0,
    "knowledge_base_search": 0,
    "python_executor": 0,
    "ask_user": 0,
}
_DEFAULT_CACHE_TTL_SECONDS = 30.0

# Per (user, tool) sliding-window limit - protects both upstream API quotas
# (SerpAPI, Open-Meteo) and against a runaway/looping caller (buggy client,
# or an LLM stuck re-requesting the same tool across chaining rounds).
_RATE_LIMIT_MAX_CALLS = 20
_RATE_LIMIT_WINDOW_SECONDS = 60.0


def _cache_key(tool_name: str, args: dict[str, Any]) -> tuple[str, tuple[tuple[str, Any], ...]]:
    """Order-independent, hashable key for a tool call - used for both the
    result cache and same-batch duplicate-call suppression."""
    normalized = tuple(sorted((k, v) for k, v in args.items() if k != "user_id"))
    return (tool_name, normalized)


def _is_transient(result_dict: dict[str, Any]) -> bool:
    """Whether a tool failure looks worth retrying vs. a deterministic one.

    Prefers an explicit `metadata["transient"]` flag when a tool sets one -
    falls back to substring matching on the error message for tools that
    don't, since some transient exceptions stringify to a generic message
    no keyword list would ever match.
    """
    metadata = result_dict.get("metadata") or {}
    if "transient" in metadata:
        return bool(metadata["transient"])
    error = result_dict.get("error")
    if not error:
        return False
    lowered = error.lower()
    return any(hint in lowered for hint in _TRANSIENT_ERROR_HINTS)


@dataclass
class _CacheEntry:
    result: dict[str, Any]
    expires_at: float


@dataclass
class _RateWindow:
    calls: list[float] = field(default_factory=list)


class ToolExecutor:
    """Executes one or many tool calls with production-grade guardrails.

    A single instance is shared process-wide (via the DI container) so its
    cache and rate-limit state actually accumulate across requests instead
    of resetting every turn.
    """

    def __init__(self, tool_registry: ToolRegistry) -> None:
        self._registry = tool_registry
        self._cache: dict[tuple[str, tuple[tuple[str, Any], ...]], _CacheEntry] = {}
        self._rate_windows: dict[tuple[str, str], _RateWindow] = {}
        self._lock = asyncio.Lock()

    async def run_many(
        self, calls: list[tuple[str, dict[str, Any]]], *, user_id: str | None = None
    ) -> list[dict[str, Any]]:
        """Execute a batch of (tool_name, args) calls.

        Independent calls run concurrently. Duplicate calls (identical tool
        + args, ignoring order) within the same batch are only actually
        invoked once and the result is fanned back out to every requester -
        this is what stops an LLM that (redundantly) asks for the same tool
        twice in one round from paying for it twice.
        """
        if not calls:
            return []

        keys = [_cache_key(name, args) for name, args in calls]
        unique_order: list[tuple[str, tuple[tuple[str, Any], ...]]] = []
        seen: set[tuple[str, tuple[tuple[str, Any], ...]]] = set()
        unique_calls: list[tuple[str, dict[str, Any]]] = []
        for key, (name, args) in zip(keys, calls):
            if key in seen:
                continue
            seen.add(key)
            unique_order.append(key)
            unique_calls.append((name, args))

        results_by_key: dict[tuple[str, tuple[tuple[str, Any], ...]], dict[str, Any]] = {}
        gathered = await asyncio.gather(
            *(self._run_one(name, args, user_id=user_id) for name, args in unique_calls)
        )
        for key, result in zip(unique_order, gathered):
            results_by_key[key] = result

        # Fan the (possibly deduplicated) results back out in the original
        # call order/count, so callers don't need to know dedup happened.
        return [dict(results_by_key[key]) for key in keys]

    async def run_one(self, tool_name: str, args: dict[str, Any], *, user_id: str | None = None) -> dict[str, Any]:
        """Convenience wrapper for a single call - see `run_many`."""
        return (await self.run_many([(tool_name, args)], user_id=user_id))[0]

    async def _run_one(self, tool_name: str, args: dict[str, Any], *, user_id: str | None) -> dict[str, Any]:
        cache_key = _cache_key(tool_name, args)
        cached = self._get_cached(cache_key)
        if cached is not None:
            return {**cached, "metadata": {**(cached.get("metadata") or {}), "cached": True}}

        rate_limited = await self._check_rate_limit(tool_name, user_id)
        if rate_limited is not None:
            return rate_limited

        result = await self._run_with_retry_and_fallback(tool_name, args)
        if result.get("success") and _CACHE_TTL_SECONDS.get(tool_name, _DEFAULT_CACHE_TTL_SECONDS) > 0:
            self._set_cached(cache_key, tool_name, result)
        return result

    # ------------------------------------------------------------------
    # Cache
    # ------------------------------------------------------------------
    def _get_cached(self, key: tuple[str, tuple[tuple[str, Any], ...]]) -> dict[str, Any] | None:
        entry = self._cache.get(key)
        if entry is None:
            return None
        if entry.expires_at < time.monotonic():
            del self._cache[key]
            return None
        return entry.result

    def _set_cached(self, key: tuple[str, tuple[tuple[str, Any], ...]], tool_name: str, result: dict[str, Any]) -> None:
        ttl = _CACHE_TTL_SECONDS.get(tool_name, _DEFAULT_CACHE_TTL_SECONDS)
        self._cache[key] = _CacheEntry(result=result, expires_at=time.monotonic() + ttl)

    # ------------------------------------------------------------------
    # Rate limiting
    # ------------------------------------------------------------------
    async def _check_rate_limit(self, tool_name: str, user_id: str | None) -> dict[str, Any] | None:
        """Returns a rejection result dict if over the limit, else None."""
        window_key = (user_id or "anonymous", tool_name)
        now = time.monotonic()
        async with self._lock:
            window = self._rate_windows.setdefault(window_key, _RateWindow())
            window.calls = [t for t in window.calls if now - t < _RATE_LIMIT_WINDOW_SECONDS]
            if len(window.calls) >= _RATE_LIMIT_MAX_CALLS:
                logger.warning(
                    "Tool '%s' rate-limited for user %s (%d calls in the last %.0fs)",
                    tool_name, user_id or "anonymous", len(window.calls), _RATE_LIMIT_WINDOW_SECONDS,
                )
                return {
                    "tool": tool_name,
                    "success": False,
                    "error": f"Too many '{tool_name}' calls - please try again in a moment.",
                    "metadata": {"transient": True, "rate_limited": True},
                }
            window.calls.append(now)
        return None

    # ------------------------------------------------------------------
    # Retry + fallback (per-tool execution)
    # ------------------------------------------------------------------
    async def _run_with_retry_and_fallback(self, tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
        result = await self._run_with_retry(tool_name, args)
        fallback_name = _FALLBACK_TOOLS.get(tool_name)
        if result.get("success") or not fallback_name or not self._registry.has(fallback_name):
            return result

        logger.warning("Tool '%s' failed (%s), falling back to '%s'", tool_name, result.get("error"), fallback_name)
        fallback_args = {k: v for k, v in args.items()}
        fallback_result = await self._run_with_retry(fallback_name, fallback_args)
        if fallback_result.get("success"):
            fallback_result["metadata"] = {**(fallback_result.get("metadata") or {}), "fallback_from": tool_name}
            return fallback_result
        return result  # both failed - the primary tool's error is more informative

    async def _run_with_retry(self, tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
        if not self._registry.has(tool_name):
            return {"tool": tool_name, "success": False, "error": f"tool_not_found:{tool_name}", "metadata": {"transient": False}}

        last_result: dict[str, Any] = {"tool": tool_name, "success": False, "error": "Tool did not run"}
        for attempt in range(1, _MAX_TOOL_ATTEMPTS + 1):
            try:
                result = await asyncio.wait_for(self._registry.invoke(tool_name, **args), timeout=_TOOL_TIMEOUT_SECONDS)
                result_dict = result.to_dict()
                result_dict["tool"] = tool_name
                if result_dict.get("success") or not _is_transient(result_dict):
                    return result_dict
                last_result = result_dict
            except asyncio.TimeoutError:
                last_result = {
                    "tool": tool_name,
                    "success": False,
                    "error": f"Tool '{tool_name}' timed out after {_TOOL_TIMEOUT_SECONDS}s",
                    "metadata": {"transient": True},
                }
            except Exception as exc:  # noqa: BLE001
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
                await asyncio.sleep(_RETRY_BACKOFF_SECONDS * attempt)

        return last_result
