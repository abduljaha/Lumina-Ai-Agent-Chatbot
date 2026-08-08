"""Tests for IntentDetectionNode's regex-based routing.

Covers the specific regression this was built to catch: a release-status
question like "is <film> 2026 released or not" matched no pattern at all
(not even the wiki fallback, since it doesn't start with "what is"/"who
is"), so it fell through to plain chat and the model guessed/fabricated an
answer instead of the agent routing it to a search tool.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.agents.nodes.intent_detection import IntentDetectionNode
from app.agents.state import INTENT_CHAT, INTENT_TOOL

node = IntentDetectionNode()


async def _detect(text: str) -> dict:
    state = {"messages": [SimpleNamespace(content=text)]}
    return await node(state)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "message",
    [
        "is korean kanakaraju 2026 released or not",
        "has the new season released yet",
        "what is the release date of the next iPhone",
        "when does the movie come out",
        "is the album out yet",
    ],
)
async def test_release_status_questions_route_to_search(message: str) -> None:
    result = await _detect(message)
    assert result["intent"] == INTENT_TOOL
    assert any(t in result["detected_tools"] for t in ("serp_search", "web_search"))


@pytest.mark.asyncio
async def test_ordinary_year_mention_is_not_treated_as_live_data() -> None:
    """A bare year must not be enough to trigger a search - only release/status phrasing should."""
    result = await _detect("my product launched in 2024 and did well")
    assert result["intent"] == INTENT_CHAT


@pytest.mark.asyncio
async def test_what_is_the_time_routes_to_time_tool() -> None:
    result = await _detect("what is the time in Tokyo")
    assert result["intent"] == INTENT_TOOL
    assert "current_time" in result["detected_tools"]


@pytest.mark.asyncio
async def test_weather_routes_to_weather_tool() -> None:
    result = await _detect("what's the weather like in Paris")
    assert result["intent"] == INTENT_TOOL
    assert "weather" in result["detected_tools"]


@pytest.mark.asyncio
async def test_calculation_routes_to_calculator() -> None:
    result = await _detect("calculate 458 * 37")
    assert result["intent"] == INTENT_TOOL
    assert "calculator" in result["detected_tools"]


@pytest.mark.asyncio
async def test_plain_greeting_is_chat_intent() -> None:
    result = await _detect("hey, how are you doing today?")
    assert result["intent"] == INTENT_CHAT


@pytest.mark.asyncio
async def test_compound_query_detects_multiple_tools() -> None:
    result = await _detect("what's the time and weather in Paris")
    assert result["intent"] == INTENT_TOOL
    assert "current_time" in result["detected_tools"]
    assert "weather" in result["detected_tools"]
