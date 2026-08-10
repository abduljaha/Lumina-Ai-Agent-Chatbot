"""Tests for LLMNode's multi-round native function-calling: dependent tool
chaining (a second tool call built from the first tool's result), the
round-cap safety limit, and single-round back-compat behavior.

The LLM side is scripted (a fake router returning a pre-set sequence of
responses) so these tests are deterministic and don't need a real provider;
tool execution goes through a real `ToolExecutor` + `ToolRegistry` with fake
tools, so the actual concurrency/caching machinery is exercised for real.
"""
from __future__ import annotations

import pytest

from app.agents.nodes.llm_node import LLMNode, _MAX_TOOL_ROUNDS
from app.llm.base import ModelResponse
from app.tools.base import ToolResult
from app.tools.executor import ToolExecutor
from app.tools.registry import ToolRegistry


class _FakeTool:
    def __init__(self, name: str) -> None:
        self.name = name
        self.description = f"fake {name}"
        self.call_count = 0

    async def invoke(self, **kwargs):
        self.call_count += 1
        return ToolResult(success=True, output=f"{self.name}-output", metadata={})

    def to_dict(self):
        return {"name": self.name, "description": self.description, "parameters": {}}


class _FakeRouter:
    """Returns responses from a pre-scripted queue, one per generate_with_tools call.

    `generate` (no tools) always returns the last scripted "final" response.
    """

    def __init__(self, responses: list[ModelResponse], final: ModelResponse) -> None:
        self._responses = list(responses)
        self._final = final
        self.generate_with_tools_calls = 0
        self.generate_calls = 0

    async def generate_with_tools(self, request, provider=None):
        self.generate_with_tools_calls += 1
        if not self._responses:
            return self._final
        return self._responses.pop(0)

    async def generate(self, request, provider=None):
        self.generate_calls += 1
        return self._final


def _tool_call(name: str, args: dict) -> dict:
    return {"name": name, "arguments": args}


def _state(user_id: str = "u1") -> dict:
    return {"messages": [], "user_id": user_id, "model_attempts": 0}


@pytest.mark.asyncio
async def test_dependent_two_tool_chain_completes_and_returns_final_answer() -> None:
    """Round 1 calls geocode; round 2 (seeing geocode's result) calls weather; round 3 answers."""
    geocode_tool = _FakeTool("geocode_tool")
    weather_tool = _FakeTool("weather_tool")
    registry = ToolRegistry()
    registry.register_all([geocode_tool, weather_tool])
    executor = ToolExecutor(registry)

    round1 = ModelResponse(content="", model="m", provider="p", tool_calls=[_tool_call("geocode_tool", {"city": "Paris"})])
    round2 = ModelResponse(content="", model="m", provider="p", tool_calls=[_tool_call("weather_tool", {"lat": 48.85, "lon": 2.35})])
    final = ModelResponse(content="It's sunny in Paris.", model="m", provider="p")

    router = _FakeRouter(responses=[round1, round2], final=final)
    node = LLMNode(router, tool_registry=registry, tool_executor=executor)

    result = await node(_state())

    assert result["generation"] == "It's sunny in Paris."
    assert geocode_tool.call_count == 1
    assert weather_tool.call_count == 1
    tool_names = {r["tool"] for r in result["tool_results"]}
    assert tool_names == {"geocode_tool", "weather_tool"}
    # 3 tool-offering calls: initial (-> geocode), chained (-> weather), and
    # the one that finally comes back with real content and no more
    # tool_calls - the loop exits naturally there, so the separate untooled
    # generate() fallback is never needed for a chain that resolves itself.
    assert router.generate_with_tools_calls == 3
    assert router.generate_calls == 0


@pytest.mark.asyncio
async def test_model_that_never_stops_requesting_tools_is_capped() -> None:
    """A model that keeps asking for tools indefinitely is cut off at _MAX_TOOL_ROUNDS."""
    tool = _FakeTool("calculator")
    registry = ToolRegistry()
    registry.register_all([tool])
    executor = ToolExecutor(registry)

    # Every round asks for a DIFFERENT expression so the cache can't collapse
    # rounds together and hide a bug where execution silently stops early.
    infinite_responses = [
        ModelResponse(content="", model="m", provider="p", tool_calls=[_tool_call("calculator", {"expression": f"{i}+{i}"})])
        for i in range(_MAX_TOOL_ROUNDS + 2)
    ]
    final = ModelResponse(content="Here's what I found.", model="m", provider="p")
    router = _FakeRouter(responses=infinite_responses, final=final)
    node = LLMNode(router, tool_registry=registry, tool_executor=executor)

    result = await node(_state())

    assert result["generation"] == "Here's what I found."
    assert tool.call_count == _MAX_TOOL_ROUNDS
    assert router.generate_with_tools_calls == _MAX_TOOL_ROUNDS
    assert router.generate_calls == 1  # forced final answer, tools withheld


@pytest.mark.asyncio
async def test_single_round_no_chaining_needed_still_works() -> None:
    """Model calls one tool, then answers immediately - the common case, unchanged."""
    tool = _FakeTool("calculator")
    registry = ToolRegistry()
    registry.register_all([tool])
    executor = ToolExecutor(registry)

    round1 = ModelResponse(content="", model="m", provider="p", tool_calls=[_tool_call("calculator", {"expression": "2+2"})])
    final = ModelResponse(content="2 + 2 = 4.", model="m", provider="p")
    router = _FakeRouter(responses=[round1], final=final)
    node = LLMNode(router, tool_registry=registry, tool_executor=executor)

    result = await node(_state())

    assert result["generation"] == "2 + 2 = 4."
    assert tool.call_count == 1
    # Initial call (-> the tool request) + the round that returns the real,
    # tool_calls-free answer - loop exits naturally, no forced generate().
    assert router.generate_with_tools_calls == 2
    assert router.generate_calls == 0


@pytest.mark.asyncio
async def test_model_that_answers_immediately_never_calls_a_tool() -> None:
    """No tool_calls on the first response - no tool executed, no extra round-trip."""
    tool = _FakeTool("calculator")
    registry = ToolRegistry()
    registry.register_all([tool])
    executor = ToolExecutor(registry)

    final = ModelResponse(content="Hello! How can I help?", model="m", provider="p")
    router = _FakeRouter(responses=[final], final=final)
    node = LLMNode(router, tool_registry=registry, tool_executor=executor)

    result = await node(_state())

    assert result["generation"] == "Hello! How can I help?"
    assert tool.call_count == 0
    assert router.generate_with_tools_calls == 1
    assert router.generate_calls == 0


@pytest.mark.asyncio
async def test_reflection_retry_does_not_reoffer_tools() -> None:
    """model_attempts > 0 (a reflection retry) must not trigger a new tool-calling round."""
    tool = _FakeTool("calculator")
    registry = ToolRegistry()
    registry.register_all([tool])
    executor = ToolExecutor(registry)

    final = ModelResponse(content="Refined answer.", model="m", provider="p")
    router = _FakeRouter(responses=[final], final=final)
    node = LLMNode(router, tool_registry=registry, tool_executor=executor)

    state = _state()
    state["model_attempts"] = 1
    result = await node(state)

    assert result["generation"] == "Refined answer."
    assert tool.call_count == 0
