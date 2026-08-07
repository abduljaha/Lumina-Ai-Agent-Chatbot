"""Retriever - orchestrates the full RAG retrieval pipeline."""
from __future__ import annotations

import logging
from typing import Any

from app.rag.embedder import Embedder
from app.rag.hybrid_search import HybridSearch
from app.rag.reranker import Reranker
from app.rag.vectorstore import VectorStore

logger = logging.getLogger("app")


class Retriever:
    """End-to-end RAG retriever.

    Pipeline: embed query -> hybrid search (vector + BM25) -> rerank -> compress.
    """

    def __init__(
        self,
        vector_store: VectorStore,
        embedder: Embedder,
        hybrid_search: HybridSearch,
        reranker: Reranker,
    ) -> None:
        self._vector_store = vector_store
        self._embedder = embedder
        self._hybrid_search = hybrid_search
        self._reranker = reranker

    async def get_by_ids(self, ids: list[str]) -> list[dict[str, Any]]:
        """Fetch specific chunks by id, bypassing similarity search entirely.

        Used for deterministic inclusion (e.g. "every chunk of the document
        just uploaded in this thread") where the caller already knows
        exactly which chunks it wants, rather than hoping they rank highly
        enough in a similarity search to be included.
        """
        return await self._vector_store.get_by_ids(ids)

    async def retrieve(
        self,
        query: str,
        top_k: int = 5,
        user_id: str | None = None,
        filters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Retrieve relevant documents for a query, scoped to `user_id`.

        `user_id` used to be accepted but silently dropped here, which meant
        every user's uploaded documents were searchable by every other
        user - vector search has no inherent per-user boundary, so it must
        be enforced explicitly as a metadata filter.
        """
        query_embedding = await self._embedder.embed_query(query)

        effective_filters = dict(filters or {})
        if user_id:
            effective_filters["user_id"] = user_id

        # Vector search
        vector_results = await self._vector_store.search(
            query_embedding, top_k=top_k * 2, filters=effective_filters or None
        )

        if not vector_results:
            return []

        # Hybrid search (BM25 + vector fusion)
        hybrid_results = await self._hybrid_search.search(
            query=query,
            query_embedding=query_embedding,
            documents=vector_results,
            vector_store=self._vector_store,
            top_k=top_k,
            filters=effective_filters or None,
        )

        # Rerank
        reranked = await self._reranker.rerank(query, hybrid_results, top_k=top_k)

        # Compress context (truncate long contents)
        for doc in reranked:
            doc["content"] = self._compress(doc.get("content", ""), max_chars=600)

        return reranked

    def _compress(self, content: str, max_chars: int = 600) -> str:
        """Compress long document content."""
        if len(content) <= max_chars:
            return content
        return content[:max_chars] + "..."
