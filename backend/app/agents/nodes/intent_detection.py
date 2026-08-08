"""Intent detection node - classify user intent."""
from __future__ import annotations

import logging
import re
from typing import Any

from app.agents.state import INTENT_ASK_USER, INTENT_CHAT, INTENT_RAG, INTENT_TOOL
from app.core.config import get_settings

logger = logging.getLogger("app")
settings = get_settings()

# Keyword-based intent heuristics
_CALCULATION_PATTERNS = [
    r"calculate",
    r"what is \d",
    r"compute",
    r"how much is \d",
    r"math",
    r"sum of",
    r"percent",
    r"(\d+[\s]*[+\-*/%][\s]*\d+)",
]

# "what time" alone used to also match ETA phrasing like "by what time would
# I be there" and misroute it to the current_time tool - excluded via the
# negative lookahead whenever the message is actually asking about arrival.
_TIME_PATTERNS = [
    r"\bwhat time\b(?!.*\b(?:reach|arrive|get there|would i be|will i be)\b)",
    r"what'?s the time",
    r"what is the time\b(?!.*\b(?:reach|arrive|get there|would i be|will i be|complexity|zone|difference)\b)",
    r"current time",
    r"what date",
    r"what'?s the date",
    r"what is the date",
    r"today('s)? date",
    r"what day",
]

_WEATHER_PATTERNS = [
    r"weather",
    r"temperature",
    r"forecast",
    r"is it (raining|snowing|sunny|hot|cold|windy)",
    r"climate",
    r"\brain(y|coat)?\b",
    r"\bumbrella\b",
    r"\bsnow(ing)?\b",
    r"\bhumidity\b",
]

# Commodity / market prices - not covered by the general "stock price" /
# "share price" live-data patterns below, and common enough (gold, fuel) to
# warrant their own bucket.
_PRICE_PATTERNS = [
    r"gold (price|rate)",
    r"silver (price|rate)",
    r"petrol price",
    r"diesel price",
    r"fuel price",
    r"\bprice of\b",
    r"today'?s (gold|silver|petrol|diesel|fuel)?\s*(price|rate)",
    r"market (price|rate)",
]

# Distance / travel-time / ETA questions - there's no dedicated
# directions tool, so these are routed to live web search, whose answer
# box/knowledge graph results reliably surface driving distance and time.
_DISTANCE_PATTERNS = [
    r"how (long|far)",
    r"distance (from|to|between)",
    r"travel time",
    r"how many (km|kilometers|kilometres|miles)",
    r"\beta\b",
    r"by what time (will|would) i",
    r"what time (will|would) i (reach|arrive|get there)",
]

_SEARCH_PATTERNS = [
    r"search (the web|online|for)",
    r"look up",
    r"find information about",
    r"what is the latest",
    r"current news",
    r"who won",
    r"latest",
    r"up-to-date",
    # Bare "news"/"headlines" (not just "current news"/"breaking news") -
    # "what are today's top news headlines" has neither qualifier but is
    # just as time-sensitive as either.
    r"\bnews\b",
    r"\bheadlines?\b",
]
# A bare 4-digit year (was here previously) matched far too broadly - "my
# product launched in 2024" or "Python 3.12 came out in 2023" are ordinary
# statements, not live-data questions, and each false-positive match burns a
# real search API call. Removed rather than narrowed: intent_detection is a
# fast, deliberately imprecise pre-filter, not the only path to a tool call -
# llm_node's native function-calling fallback (see llm_node.py) catches
# genuine live-data questions phrased in ways no fixed pattern list covers,
# so this list can now afford to favor precision over recall.

# Release/availability status - "is X released", "release date of X", "is X
# out yet" - is a narrower, more targeted signal than a bare year: asking
# whether something has *happened yet* is inherently a check against the
# present moment, unlike a statement merely mentioning a year. Without this,
# a question like "is <film/game/album> 2026 released or not" fell through
# every bucket (no match for any _WIKI_PATTERNS phrasing like "what is"/"who
# is" either, since it starts with "is") straight to plain chat, and the
# model - per its own training data cutoff - guessed or fabricated a status
# instead of checking.
_RELEASE_STATUS_PATTERNS = [
    r"\breleased?\s+(or not|yet|already)\b",
    r"\brelease date\b",
    r"\bwhen (is|does|will|was)\b.{0,40}\b(release|come out|launch|premiere|drop)\b",
    r"\bcoming out\b",
    r"\bout yet\b",
    r"\bhas\b.{0,40}\b(released?|launched|premiered|dropped)\b",
]

# Explicitly "changes minute to minute" phrasing - routed to serp_search
# (live Google results) in preference to the plain web_search scraper when
# SerpAPI is configured, since these need a fresh instant answer rather than
# a list of pages to read.
_LIVE_DATA_PATTERNS = [
    r"\blive\b",
    r"right now",
    r"\bcurrently\b",
    r"breaking news",
    r"stock price",
    r"share price",
    r"exchange rate",
    r"\bscore\b",
    r"scorecard",
    r"trading at",
    r"\bodds\b",
]

_WIKI_PATTERNS = [
    r"who is",
    r"what is",
    r"define",
    r"explain",
    r"history of",
    r"wikipedia",
]

_KNOWLEDGE_BASE_PATTERNS = [
    r"my documents",
    r"my knowledge base",
    r"search my files",
    r"from my (document|files|notes)",
    r"what did i upload",
]

_ASK_USER_PATTERNS = [
    r"which (city|location|option|one)",
    r"what would you recommend",
    r"help me decide",
    r"which one",
    r"what should i",
]


class IntentDetectionNode:
    """Determines the user's intent using keyword and pattern heuristics.

    In production a lightweight classifier or the LLM itself is used;
    this node provides a fast, deterministic fallback.
    """

    async def __call__(self, state: dict[str, Any]) -> dict[str, Any]:
        """Classify the intent of the latest user message."""
        messages = state.get("messages", [])
        if not messages:
            return {"intent": INTENT_CHAT}

        last = messages[-1]
        content = getattr(last, "content", "") or ""
        content = content.lower()

        # Ask-user takes priority - it's a request to clarify, not a lookup.
        if self._matches(content, _ASK_USER_PATTERNS):
            return {"intent": INTENT_ASK_USER, "selected_tool": "ask_user"}

        if self._matches(content, _KNOWLEDGE_BASE_PATTERNS):
            return {"intent": INTENT_RAG, "selected_tool": "knowledge_base_search"}

        # Every remaining category is checked independently and accumulated,
        # not a first-match-wins chain - a single compound question (travel
        # time + weather + a live price, for example) can legitimately need
        # several tools at once, and tool_selection already runs whatever
        # ends up in `detected_tools` concurrently.
        detected: list[str] = []
        if self._matches(content, _CALCULATION_PATTERNS):
            detected.append("calculator")
        if self._matches(content, _TIME_PATTERNS):
            detected.append("current_time")
        if self._matches(content, _WEATHER_PATTERNS):
            detected.append("weather")

        needs_search = self._matches(content, _PRICE_PATTERNS) or self._matches(
            content, _DISTANCE_PATTERNS
        ) or self._matches(content, _LIVE_DATA_PATTERNS) or self._matches(
            content, _SEARCH_PATTERNS
        ) or self._matches(content, _RELEASE_STATUS_PATTERNS)
        if needs_search:
            # Prefer SerpAPI's live Google results when configured - the free
            # web_search tool scrapes DuckDuckGo/Google directly and is prone
            # to rate-limiting, and it has no answer_box-style instant answers
            # for things like scores or prices.
            detected.append("serp_search" if settings.serpapi_api_key else "web_search")
        elif not detected and self._matches(content, _WIKI_PATTERNS):
            # Only a fallback when nothing else fired - wiki is for stable,
            # encyclopedic facts, not anything time-sensitive. "not detected"
            # matters here specifically: _WIKI_PATTERNS' "what is" also
            # matches inside compound queries like "...and what is 458*37",
            # where it's just how the calculation was phrased, not an actual
            # request to look something up on Wikipedia.
            detected.append("wikipedia")

        if detected:
            return {"intent": INTENT_TOOL, "selected_tool": detected[0], "detected_tools": detected}

        # Default to conversational chat
        return {"intent": INTENT_CHAT}

    @staticmethod
    def _matches(text: str, patterns: list[str]) -> bool:
        """Check whether text matches any pattern."""
        return any(re.search(p, text) for p in patterns)
