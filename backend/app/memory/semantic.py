"""Semantic (embedding-based) search over a user's global profile memory.

Kept in its own ChromaDB/FAISS collection ("profile_memory"), separate from
the RAG document collection ("documents") - different data, different
lifecycle, and mixing them would make per-user filtering easier to get
wrong. Every write and read here is scoped by `user_id`, enforced as a
metadata filter at the vector-store layer (see VectorStore.search/delete_ids)
so one user's facts can never surface in another user's search results.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("app")


class ProfileMemoryIndex:
    """Embeds and semantically searches a user's global ENTITY facts."""

    def __init__(self, embedder: Any, vector_store: Any) -> None:
        self._embedder = embedder
        self._vector_store = vector_store

    async def index_fact(self, user_id: str, memory_id: str, key: str, content: str) -> None:
        """Embed and (re)index a single profile fact.

        Safe to call again for the same `memory_id` - the vector store
        upserts, so an updated fact's old embedding is replaced rather than
        left as a stale duplicate.
        """
        try:
            embeddings = await self._embedder.embed([content])
            if not embeddings:
                return
            await self._vector_store.add_documents(
                [
                    {
                        "id": memory_id,
                        "content": content,
                        "source": key,
                        "document_id": memory_id,
                        "metadata": {"user_id": user_id, "key": key},
                    }
                ],
                embeddings,
            )
        except Exception as exc:  # noqa: BLE001
            # Indexing is an enhancement on top of the "include everything"
            # baseline in retrieve_for_context - never let it block a write.
            logger.warning("Profile fact indexing failed for user %s: %s", user_id, exc)

    async def remove_fact(self, memory_id: str) -> None:
        """Remove a fact from the semantic index (on delete)."""
        try:
            await self._vector_store.delete_ids([memory_id])
        except Exception as exc:  # noqa: BLE001
            logger.warning("Profile fact removal failed for %s: %s", memory_id, exc)

    async def search(self, user_id: str, query: str, top_k: int = 5) -> list[str]:
        """Return the content of the `top_k` facts most relevant to `query`.

        Always scoped to `user_id` - this is the only path a user's facts
        can be retrieved through here, and it can never return another
        user's data because the vector store filters on `user_id` before
        anything is ranked, not after.
        """
        if not query:
            return []
        try:
            query_embedding = await self._embedder.embed_query(query)
            results = await self._vector_store.search(
                query_embedding, top_k=top_k, filters={"user_id": user_id}
            )
            return [r["content"] for r in results]
        except Exception as exc:  # noqa: BLE001
            logger.warning("Profile semantic search failed for user %s: %s", user_id, exc)
            return []
