"""Wikipedia search tool."""
from __future__ import annotations

from typing import Any

from app.tools.base import ToolResult


class WikipediaTool:
    """Searches and retrieves Wikipedia article summaries."""

    name = "wikipedia"
    description = "Search Wikipedia and retrieve article summaries and details."

    async def invoke(self, query: str = "", fetch_summary: bool = True, **kwargs: Any) -> ToolResult:
        """Search Wikipedia and optionally fetch article summary."""
        if not query:
            return ToolResult(success=False, error="No query provided")
        try:
            import wikipediaapi

            wiki = wikipediaapi.Wikipedia("ai-chatbot/1.0", language="en")
            page = wiki.page(query)
            if not page.exists():
                # Try search
                import wikipedia

                search_results = wikipedia.search(query, results=3)
                if not search_results:
                    return ToolResult(success=False, error=f"No Wikipedia article found for '{query}'")
                return ToolResult(
                    success=True,
                    output={"suggestions": search_results},
                    metadata={"mode": "suggestions"},
                )

            result = {"title": page.title, "url": page.fullurl}
            if fetch_summary:
                result["summary"] = page.summary[:2000] if page.summary else ""
            return ToolResult(success=True, output=result, metadata={"mode": "article"})
        except Exception as exc:
            return ToolResult(success=False, error=f"Wikipedia lookup failed: {exc}")

    def to_dict(self) -> dict[str, Any]:
        """Return tool metadata."""
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Wikipedia search query"},
                    "fetch_summary": {"type": "boolean", "description": "Fetch article summary", "default": True},
                },
                "required": ["query"],
            },
        }
