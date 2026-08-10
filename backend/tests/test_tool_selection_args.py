"""Tests for ToolSelectionNode's argument-building - specifically location
extraction scoped to the right clause in a compound multi-tool query.
"""
from __future__ import annotations

from app.agents.nodes.tool_selection import _extract_location, _extract_location_for_tool


def test_single_location_query_extracts_normally() -> None:
    assert _extract_location_for_tool("what is the weather in paris", "weather") == "paris"
    assert _extract_location_for_tool("what time is it in tokyo", "current_time") == "tokyo"


def test_compound_weather_and_time_query_scopes_each_tool_to_its_own_clause() -> None:
    """The bug this guards: both tools used to receive the SAME (garbled,
    cross-clause) location because plain `_extract_location` always returns
    the first "in X" match in the whole message, regardless of which tool
    asked for it."""
    text = "what is the weather in bangalore, what time is it in tokyo, and what is 458*37?"
    assert _extract_location_for_tool(text, "weather") == "bangalore"
    assert _extract_location_for_tool(text, "current_time") == "tokyo"


def test_compound_query_order_reversed_still_scopes_correctly() -> None:
    text = "what time is it in london, and what's the weather in madrid?"
    assert _extract_location_for_tool(text, "current_time") == "london"
    assert _extract_location_for_tool(text, "weather") == "madrid"


def test_compound_neighborhood_city_place_name_is_not_split_by_comma() -> None:
    """'Madhapur, Hyderabad' is one compound place name, not two clauses -
    the comma must stay inside the extracted location, same as before this
    tool-scoping was added."""
    text = "what's the weather in Madhapur, Hyderabad"
    assert _extract_location_for_tool(text, "weather") == "Madhapur, Hyderabad"
    # Unscoped extraction must be unchanged too - this is the fallback path.
    assert _extract_location("what's the weather in Madhapur, Hyderabad") == "Madhapur, Hyderabad"


def test_no_keyword_match_falls_back_to_whole_text_extraction() -> None:
    """A tool name with no keyword table entry behaves exactly like plain `_extract_location`."""
    text = "search for hotels in rome"
    assert _extract_location_for_tool(text, "some_other_tool") == _extract_location(text)
