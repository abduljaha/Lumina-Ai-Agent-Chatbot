"""Hybrid search - combines BM25 keyword search with vector search."""
from __future__ import annotations

import logging
from typing import Any

from rank_bm25 import BM25Okapi

logger = logging.getLogger("app")


class HybridSearch:
    """Performs hybrid search combining BM25 and vector retrieval."""

    def __init__(self, vector_search_weight: float = 0.6, bm25_weight: float = 0.4) -> None:
        self._vector_weight = vector_search_weight
        self._bm25_weight = bm25_weight

    def _tokenize(self, text: str) -> list[str]:
        """Tokenize text for BM25."""
        import re

        return re.findall(r"\w+", text.lower())

    def _bm25_search(
        self,
        query: str,
        documents: list[dict[str, Any]],
        top_k: int,
    ) -> list[tuple[int, float]]:
        """Run BM25 search over documents."""
        if not documents:
            return []
        corpus = [self._tokenize(doc["content"]) for doc in documents]
        bm25 = BM25Okapi(corpus)
        query_tokens = self._tokenize(query)
        scores = bm25.get_scores(query_tokens)
        # Normalize scores
        max_score = max(scores) if len(scores) > 0 and max(scores) > 0 else 1.0
        normalized = [(score / max_score) for score in scores]
        ranked = sorted(enumerate(normalized), key=lambda x: x[1], reverse=True)
        return ranked[:top_k]

    async def search(
        self,
        query: str,
        query_embedding: list[float],
        documents: list[dict[str, Any]],
        vector_store: Any,
        top_k: int = 5,
        filters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Run hybrid search combining vector + BM25 with result fusion."""
        # Vector search
        vector_results = await vector_store.search(query_embedding, top_k=top_k * 2, filters=filters)

        # BM25 search over the same document pool
        all_docs = [doc for doc in vector_results]
        bm25_ranked = self._bm25_search(query, all_docs, top_k)

        # Fuse scores (Reciprocal Rank Fusion style)
        scores: dict[int, float] = {}
        for rank, (idx, _) in enumerate(bm25_ranked):
            scores[idx] = scores.get(idx, 0) + (self._bm25_weight / (rank + 1))

        for rank, doc in enumerate(vector_results):
            idx = self._find_index(all_docs, doc)
            scores[idx] = scores.get(idx, 0) + (self._vector_weight / (rank + 1))

        # Sort by fused score
        ranked_indices = sorted(scores, key=lambda i: scores[i], reverse=True)
        results = []
        for idx in ranked_indices[:top_k]:
            if idx < len(all_docs):
                doc = dict(all_docs[idx])
                doc["score"] = scores[idx]
                results.append(doc)
        return results

    def _find_index(self, documents: list[dict[str, Any]], target: dict[str, Any]) -> int:
        """Find the index of a document in the list."""
        for i, doc in enumerate(documents):
            if doc.get("content") == target.get("content"):
                return i
        return 0
