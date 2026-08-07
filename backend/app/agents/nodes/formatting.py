"""Formatting node - prepare the final response."""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("app")


class FormattingNode:
    """Formats the final response with citations and metadata.

    Produces the final output structure including:
    - The answer text
    - Citations (from RAG context)
    - Generation metadata
    """

    async def __call__(self, state: dict[str, Any]) -> dict[str, Any]:
        """Format the final answer."""
        generation = state.get("generation") or ""
        retrieved_docs = state.get("retrieved_documents", [])
        tool_results = state.get("tool_results", [])

        # Build citations from retrieved documents
        citations = []
        if retrieved_docs:
            for i, doc in enumerate(retrieved_docs[:5]):
                citations.append(
                    {
                        "index": i,
                        "source": doc.get("source", "document"),
                        "document_id": doc.get("document_id"),
                        "content": doc.get("content", "")[:200],
                    }
                )

        # Include tool results summary
        tool_summary = []
        for r in tool_results:
            tool_summary.append(
                {
                    "tool": r.get("tool", "unknown"),
                    "success": r.get("success", False),
                    "output": r.get("output"),
                }
            )

        return {
            "generation": generation,
            "citations": citations,
            "metadata": {
                **state.get("metadata", {}),
                "tool_results": tool_summary,
                "has_citations": bool(citations),
            },
        }
