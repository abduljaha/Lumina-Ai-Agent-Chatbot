"""Knowledge base search tool backed by the RAG retriever."""
from __future__ import annotations

from typing import Any

from app.tools.base import ToolResult


class KnowledgeBaseSearchTool:
    """Searches the indexed knowledge base (RAG) for relevant documents."""

    name = "knowledge_base_search"
    description = "Search the user's uploaded documents and knowledge base for relevant information."

    def __init__(self, retriever=None) -> None:
        self._retriever = retriever

    async def invoke(
        self,
        query: str = "",
        top_k: int = 5,
        user_id: str | None = None,
        file_type: str | None = None,
        **kwargs: Any,
    ) -> ToolResult:
        """Search the knowledge base.

        `file_type` (e.g. "pdf", "xlsx") narrows the search to documents of
        that type only, via the same metadata-filter mechanism `user_id`
        uses to scope results to their owner - see Retriever.retrieve and
        DocumentProcessor._extract_metadata, which is what tags each chunk
        with its source file's extension in the first place.
        """
        if not query:
            return ToolResult(success=False, error="No search query provided")
        if self._retriever is None:
            return ToolResult(
                success=False,
                error="Knowledge base retriever is not configured",
                metadata={"available": False},
            )
        try:
            filters = {"file_type": file_type} if file_type else None
            docs = await self._retriever.retrieve(
                query=query,
                top_k=top_k,
                user_id=user_id,
                filters=filters,
            )
            results = [
                {
                    "content": d.get("content"),
                    "score": d.get("score"),
                    "source": d.get("source"),
                    "document_id": d.get("document_id"),
                }
                for d in docs
            ]
            return ToolResult(
                success=True,
                output=results,
                metadata={"query": query, "count": len(results)},
            )
        except Exception as exc:
            return ToolResult(success=False, error=f"Knowledge base search failed: {exc}")

    def to_dict(self) -> dict[str, Any]:
        """Return tool metadata."""
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                    "top_k": {"type": "integer", "description": "Number of results", "default": 5},
                    "file_type": {
                        "type": "string",
                        "description": "Restrict results to one file type, e.g. 'pdf', 'xlsx', 'docx' (optional)",
                    },
                },
                "required": ["query"],
            },
        }
