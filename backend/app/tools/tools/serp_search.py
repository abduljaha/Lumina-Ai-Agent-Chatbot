"""SerpAPI tool - live Google Search results for fast-changing information.

Unlike the free web_search tool (which scrapes DuckDuckGo/Google and is
prone to rate-limiting), this calls SerpAPI's paid API directly. Its
answer_box/knowledge_graph fields surface Google's own instant answers -
scores, prices, exchange rates, breaking headlines - which is what actually
answers "what changed in the last few minutes" questions; organic_results
alone are just links to pages, not live data.
"""
from __future__ import annotations

from typing import Any

from app.core.config import get_settings
from app.tools.base import ToolResult

settings = get_settings()


class SerpApiTool:
    """Live search via SerpAPI for information that changes minute to minute."""

    name = "serp_search"
    available: bool = bool(settings.serpapi_api_key)
    description = (
        "Search Google for live, up-to-the-minute information: sports scores, "
        "stock/crypto prices, exchange rates, breaking news, election results, "
        "or anything else that changes frequently. Prefer this over web_search "
        "when the user needs the current, live value of something, not just "
        "background information."
    )

    def __init__(self, api_key: str | None = None) -> None:
        self._api_key = api_key or settings.serpapi_api_key

    async def invoke(self, query: str = "", max_results: int = 5, **kwargs: Any) -> ToolResult:
        """Run a live Google search via SerpAPI."""
        if not query:
            return ToolResult(success=False, error="No search query provided", metadata={"transient": False})
        if not self._api_key:
            return ToolResult(
                success=False,
                error="SerpAPI is not configured (set SERPAPI_API_KEY) - falling back to web_search",
                metadata={"available": False, "transient": False},
            )

        import httpx

        try:
            params = {
                "engine": "google",
                "q": query,
                "api_key": self._api_key,
                "num": max_results,
            }
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get("https://serpapi.com/search.json", params=params)
                try:
                    data = resp.json()
                except ValueError:
                    data = None

            if resp.status_code != 200:
                # SerpAPI puts a human-readable reason in the JSON body even
                # on non-200s (e.g. "Your account has run out of searches.")
                # - read it before deciding transience, since status 429
                # alone is ambiguous: SerpAPI uses it for both an ordinary
                # "slow down" rate limit (transient, worth retrying) *and*
                # permanent monthly-quota exhaustion (won't change until the
                # next billing cycle, retrying is pointless).
                error_message = (data or {}).get("error")
                quota_exhausted = bool(error_message) and "run out of searches" in error_message.lower()
                transient = not quota_exhausted and (resp.status_code >= 500 or resp.status_code == 429)
                return ToolResult(
                    success=False,
                    error=f"SerpAPI error: {error_message}" if error_message
                    else f"SerpAPI search failed: HTTP {resp.status_code}",
                    metadata={"transient": transient},
                )

            if not data:
                # 200 status but a non-JSON/empty body - unexpected enough
                # to be worth one retry rather than assuming it's permanent.
                return ToolResult(
                    success=False,
                    error="SerpAPI returned an unreadable response",
                    metadata={"transient": True},
                )

            if data.get("error"):
                # SerpAPI's own error field (bad/expired key, quota exhausted,
                # malformed query, ...) is a deterministic account/request
                # problem - retrying the identical request won't fix it, so
                # this is explicitly non-transient rather than left for the
                # caller to guess from message text.
                return ToolResult(
                    success=False,
                    error=f"SerpAPI error: {data['error']}",
                    metadata={"transient": False},
                )

            output: dict[str, Any] = {"query": query}

            answer_box = data.get("answer_box")
            if answer_box:
                output["live_answer"] = (
                    answer_box.get("answer")
                    or answer_box.get("result")
                    or answer_box.get("snippet")
                    or answer_box.get("title")
                )

            knowledge_graph = data.get("knowledge_graph")
            if knowledge_graph:
                output["knowledge_graph"] = {
                    "title": knowledge_graph.get("title"),
                    "description": knowledge_graph.get("description"),
                }

            top_stories = data.get("top_stories") or []
            if top_stories:
                output["top_stories"] = [
                    {"title": s.get("title"), "source": s.get("source"), "date": s.get("date")}
                    for s in top_stories[:max_results]
                ]

            organic = data.get("organic_results") or []
            output["results"] = [
                {"title": r.get("title"), "url": r.get("link"), "snippet": r.get("snippet")}
                for r in organic[:max_results]
            ]

            if not any([output.get("live_answer"), output.get("knowledge_graph"), output["results"]]):
                return ToolResult(
                    success=False,
                    error=f"No live results found for '{query}'",
                    metadata={"transient": False},
                )

            return ToolResult(success=True, output=output, metadata={"provider": "serpapi"})
        except (httpx.TimeoutException, httpx.ConnectError, httpx.ReadError) as exc:
            # Network-level failures - worth retrying and worth falling back
            # to web_search on, unlike a deterministic account/request error.
            return ToolResult(
                success=False,
                error=f"SerpAPI search failed (network error): {exc or type(exc).__name__}",
                metadata={"transient": True},
            )
        except Exception as exc:  # noqa: BLE001
            return ToolResult(success=False, error=f"SerpAPI search failed: {exc}", metadata={"transient": False})

    def to_dict(self) -> dict[str, Any]:
        """Return tool metadata."""
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "The live/current-information search query"},
                    "max_results": {"type": "integer", "description": "Max results to return", "default": 5},
                },
                "required": ["query"],
            },
        }
