"""Tests for ToolExecutor - the shared execution engine behind both
tool-invocation paths (regex fast-path and native LLM function-calling):
parallel batch execution, result caching, duplicate-call suppression within
a batch, and per-user rate limiting.
"""
from __future__ import annotations

import asyncio
import time

import pytest

from app.tools.base import ToolResult
from app.tools.executor import ToolExecutor
from app.tools.registry import ToolRegistry


class _CountingTool:
    """A tool that records every real invocation and can simulate latency/failure."""

    def __init__(self, name: str, delay: float = 0.0, fail_times: int = 0, transient: bool = True) -> None:
        self.name = name
        self.description = f"test tool {name}"
        self.delay = delay
        self.fail_times = fail_times
        self.transient = transient
        self.call_count = 0
        self.call_args: list[dict] = []

    async def invoke(self, **kwargs):
        self.call_count += 1
        self.call_args.append(kwargs)
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.call_count <= self.fail_times:
            return ToolResult(success=False, error="simulated failure", metadata={"transient": self.transient})
        return ToolResult(success=True, output=f"{self.name}-result-{self.call_count}")

    def to_dict(self):
        return {"name": self.name, "description": self.description, "parameters": {}}


def _registry_with(*tools: _CountingTool) -> ToolRegistry:
    registry = ToolRegistry()
    registry.register_all(list(tools))
    return registry


@pytest.mark.asyncio
async def test_independent_tools_run_in_parallel_not_sequentially() -> None:
    """Two 300ms tools in one batch should take ~300ms total, not ~600ms."""
    slow_a = _CountingTool("slow_a", delay=0.3)
    slow_b = _CountingTool("slow_b", delay=0.3)
    executor = ToolExecutor(_registry_with(slow_a, slow_b))

    start = time.perf_counter()
    results = await executor.run_many([("slow_a", {}), ("slow_b", {})])
    elapsed = time.perf_counter() - start

    assert all(r["success"] for r in results)
    assert elapsed < 0.5, f"expected parallel execution (~0.3s), took {elapsed:.2f}s"


@pytest.mark.asyncio
async def test_successful_result_is_cached_and_not_reinvoked() -> None:
    tool = _CountingTool("calculator")
    executor = ToolExecutor(_registry_with(tool))

    first = await executor.run_one("calculator", {"expression": "2+2"})
    second = await executor.run_one("calculator", {"expression": "2+2"})

    assert tool.call_count == 1  # second call was served from cache
    assert first["output"] == second["output"]
    assert second["metadata"].get("cached") is True


@pytest.mark.asyncio
async def test_current_time_is_never_cached() -> None:
    """The clock tool is excluded from caching so it never serves stale wall-clock time."""
    tool = _CountingTool("current_time")
    executor = ToolExecutor(_registry_with(tool))

    await executor.run_one("current_time", {})
    await executor.run_one("current_time", {})

    assert tool.call_count == 2  # both calls hit the real tool


@pytest.mark.asyncio
async def test_duplicate_calls_in_one_batch_are_deduplicated() -> None:
    """The same tool+args requested twice in a single batch is only invoked once."""
    tool = _CountingTool("wikipedia")
    executor = ToolExecutor(_registry_with(tool))

    results = await executor.run_many([("wikipedia", {"query": "Paris"}), ("wikipedia", {"query": "Paris"})])

    assert tool.call_count == 1
    assert len(results) == 2
    assert results[0]["output"] == results[1]["output"]


@pytest.mark.asyncio
async def test_different_args_are_not_deduplicated() -> None:
    tool = _CountingTool("wikipedia")
    executor = ToolExecutor(_registry_with(tool))

    await executor.run_many([("wikipedia", {"query": "Paris"}), ("wikipedia", {"query": "London"})])

    assert tool.call_count == 2


@pytest.mark.asyncio
async def test_transient_failure_is_retried_then_succeeds() -> None:
    tool = _CountingTool("weather", fail_times=1, transient=True)
    executor = ToolExecutor(_registry_with(tool))

    result = await executor.run_one("weather", {"city": "Paris"})

    assert result["success"] is True
    assert tool.call_count == 2  # one failure + one successful retry


@pytest.mark.asyncio
async def test_deterministic_failure_is_not_retried() -> None:
    tool = _CountingTool("calculator", fail_times=5, transient=False)
    executor = ToolExecutor(_registry_with(tool))

    result = await executor.run_one("calculator", {"expression": "bad"})

    assert result["success"] is False
    assert tool.call_count == 1  # no retry for a deterministic failure


@pytest.mark.asyncio
async def test_failing_tool_falls_back_to_configured_alternative() -> None:
    primary = _CountingTool("serp_search", fail_times=99, transient=False)
    fallback = _CountingTool("web_search")
    executor = ToolExecutor(_registry_with(primary, fallback))

    result = await executor.run_one("serp_search", {"query": "latest news"})

    assert result["success"] is True
    assert result["tool"] == "web_search"
    assert result["metadata"]["fallback_from"] == "serp_search"


@pytest.mark.asyncio
async def test_rate_limit_blocks_excessive_calls_for_same_user_and_tool(monkeypatch) -> None:
    import app.tools.executor as executor_module

    monkeypatch.setattr(executor_module, "_RATE_LIMIT_MAX_CALLS", 3)
    tool = _CountingTool("calculator")
    executor = ToolExecutor(_registry_with(tool))

    for i in range(3):
        result = await executor.run_one("calculator", {"expression": f"{i}+{i}"}, user_id="u1")
        assert result["success"] is True

    limited = await executor.run_one("calculator", {"expression": "999+999"}, user_id="u1")
    assert limited["success"] is False
    assert limited["metadata"]["rate_limited"] is True
    assert tool.call_count == 3  # the 4th call never reached the tool


@pytest.mark.asyncio
async def test_rate_limit_is_per_user() -> None:
    import app.tools.executor as executor_module

    tool = _CountingTool("calculator")
    executor = ToolExecutor(_registry_with(tool))
    original_max = executor_module._RATE_LIMIT_MAX_CALLS
    executor_module._RATE_LIMIT_MAX_CALLS = 1
    try:
        r1 = await executor.run_one("calculator", {"expression": "1+1"}, user_id="alice")
        r2 = await executor.run_one("calculator", {"expression": "2+2"}, user_id="bob")
        assert r1["success"] is True
        assert r2["success"] is True  # different user, own window
    finally:
        executor_module._RATE_LIMIT_MAX_CALLS = original_max
