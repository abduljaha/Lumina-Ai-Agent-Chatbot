"""Reranker - reorders retrieved documents by relevance."""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("app")


class Reranker:
    """Reranks retrieved documents using a cross-encoder model.

    Falls back to score-based reranking when no cross-encoder is available.
    """

    def __init__(self) -> None:
        self._model = None
        self._try_load_model()

    def _try_load_model(self) -> None:
        """Attempt to load a cross-encoder model."""
        try:
            from sentence_transformers import CrossEncoder

            self._model = CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2")
            logger.info("Loaded cross-encoder reranker")
        except Exception as exc:  # noqa: BLE001
            logger.info("Cross-encoder not available, using score-based reranking: %s", exc)
            self._model = None

    async def rerank(self, query: str, documents: list[dict[str, Any]], top_k: int = 5) -> list[dict[str, Any]]:
        """Rerank documents by relevance to the query."""
        if not documents:
            return []

        if self._model is not None:
            pairs = [(query, doc.get("content", "")) for doc in documents]
            scores = self._model.predict(pairs)
            ranked = sorted(zip(documents, scores), key=lambda x: x[1], reverse=True)
            results = []
            for doc, score in ranked[:top_k]:
                doc = dict(doc)
                doc["score"] = float(score)
                results.append(doc)
            return results

        # Fallback: sort by existing score
        ranked = sorted(documents, key=lambda d: d.get("score", 0), reverse=True)
        return ranked[:top_k]
