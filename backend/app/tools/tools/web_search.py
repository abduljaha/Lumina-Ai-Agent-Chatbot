"""Web search tool using DuckDuckGo, with a Google fallback.

Both backends scrape public search pages rather than using a paid API, so
either can be transiently rate-limited under heavy use. Falling back to a
second provider - instead of surfacing the first failure - keeps the tool
usable when one provider is temporarily blocking this host.
"""
from __future__ import annotations

import asyncio
from typing import Any

from app.tools.base import ToolResult


class WebSearchTool:
    """Performs web searches and returns top results."""

    name = "web_search"
    description = "Search the web for current information. Returns title, URL, and snippet for top results."

    async def invoke(self, query: str = "", max_results: int = 5, **kwargs: Any) -> ToolResult:
        """Execute a web search, trying DuckDuckGo then falling back to Google."""
        if not query:
            return ToolResult(success=False, error="No search query provided")

        errors: list[str] = []

        try:
            results = await self._search_duckduckgo(query, max_results)
            if results:
                return ToolResult(
                    success=True,
                    output=results,
                    metadata={"query": query, "count": len(results), "provider": "duckduckgo"},
                )
        except Exception as exc:  # noqa: BLE001
            errors.append(f"DuckDuckGo: {exc}")

        try:
            results = await self._search_google(query, max_results)
            if results:
                return ToolResult(
                    success=True,
                    output=results,
                    metadata={"query": query, "count": len(results), "provider": "google"},
                )
        except Exception as exc:  # noqa: BLE001
            errors.append(f"Google: {exc}")

        detail = "; ".join(errors) if errors else "both providers returned no results"
        return ToolResult(success=False, error=f"Web search failed: {detail}")

    async def _search_duckduckgo(self, query: str, max_results: int) -> list[dict[str, Any]]:
        from duckduckgo_search import DDGS

        def _run() -> list[dict[str, Any]]:
            with DDGS() as ddgs:
                return [
                    {"title": r.get("title"), "url": r.get("href"), "snippet": r.get("body")}
                    for r in ddgs.text(query, max_results=max_results)
                ]

        return await asyncio.to_thread(_run)

    async def _search_google(self, query: str, max_results: int) -> list[dict[str, Any]]:
        from googlesearch import search as google_search

        def _run() -> list[dict[str, Any]]:
            return [
                {"title": r.title, "url": r.url, "snippet": r.description}
                for r in google_search(query, num_results=max_results, advanced=True)
            ]

        return await asyncio.to_thread(_run)

    def to_dict(self) -> dict[str, Any]:
        """Return tool metadata."""
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "The search query"},
                    "max_results": {"type": "integer", "description": "Max results to return", "default": 5},
                },
                "required": ["query"],
            },
        }
