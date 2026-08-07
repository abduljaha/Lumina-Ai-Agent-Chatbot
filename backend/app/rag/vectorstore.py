"""Vector store abstraction supporting FAISS and ChromaDB.

The vector store is configurable via the VECTOR_DB_TYPE setting.
"""
from __future__ import annotations

import logging
from typing import Any

from app.core.config import get_settings

logger = logging.getLogger("app")
settings = get_settings()


class VectorStore:
    """Configurable vector store backed by FAISS or ChromaDB.

    `collection` names an isolated namespace (a distinct ChromaDB collection,
    or - for FAISS, which has no native collection concept - a distinct
    in-memory index owned by this instance). Callers that must not mix data
    (e.g. RAG documents vs. per-user profile facts) should construct
    separate `VectorStore` instances with different collection names rather
    than share one.
    """

    def __init__(self, db_type: str | None = None, collection: str = "documents") -> None:
        self._db_type = db_type or settings.vector_db_type
        self._collection_name = collection
        self._collection = None
        self._index = None
        self._backend = None
        self._deleted_ids: set[str] = set()
        self._initialize()

    def _initialize(self) -> None:
        """Initialize the selected vector store backend."""
        if self._db_type == "faiss":
            self._backend = "faiss"
            self._init_faiss()
        elif self._db_type == "chroma":
            self._backend = "chroma"
            self._init_chroma()
        else:
            raise ValueError(f"Unsupported vector DB type: {self._db_type}")

    def _init_faiss(self) -> None:
        """Initialize a FAISS index (in-memory, with optional persistence)."""
        try:
            import faiss
            import numpy as np

            self._faiss = faiss
            self._np = np
            self._dim = 1536  # default embedding dimension
            self._index = faiss.IndexFlatIP(self._dim)
            self._documents: list[dict[str, Any]] = []
            logger.info("Initialized FAISS vector store '%s' (dim=%d)", self._collection_name, self._dim)
        except ImportError as exc:
            logger.error("FAISS is not installed: %s", exc)
            raise

    def _init_chroma(self) -> None:
        """Initialize the ChromaDB collection."""
        try:
            import chromadb

            client = chromadb.PersistentClient(path=settings.chroma_persist_dir)
            self._collection = client.get_or_create_collection(
                name=self._collection_name,
                metadata={"hnsw:space": "cosine"},
            )
            logger.info(
                "Initialized ChromaDB vector store '%s' at %s", self._collection_name, settings.chroma_persist_dir
            )
        except ImportError as exc:
            logger.error("ChromaDB is not installed: %s", exc)
            raise

    @property
    def backend(self) -> str:
        """Return the active backend name."""
        return self._backend

    async def add_documents(
        self,
        documents: list[dict[str, Any]],
        embeddings: list[list[float]],
    ) -> None:
        """Add documents with their embeddings to the vector store.

        Each document may include a `metadata` dict of arbitrary extra
        key/value pairs (e.g. `{"user_id": ..., "key": "location"}` for
        profile facts) - these are stored alongside the standard
        source/document_id/chunk_index fields and can be used as `filters`
        in `search()`.
        """
        if not documents:
            return
        if self._backend == "faiss":
            self._add_faiss(documents, embeddings)
        else:
            self._add_chroma(documents, embeddings)

    def _add_faiss(self, documents: list[dict[str, Any]], embeddings: list[list[float]]) -> None:
        """Add documents to the FAISS index."""
        import numpy as np

        vectors = np.array(embeddings, dtype="float32")
        if self._index is None or vectors.shape[1] != self._dim:
            # Rebuild index if dimension changed
            self._dim = vectors.shape[1]
            self._index = self._faiss.IndexFlatIP(self._dim)
        self._index.add(vectors)
        for doc in documents:
            self._documents.append(doc)
            # Overwriting an id re-embeds it as a new vector (FAISS has no
            # in-place update) - drop any earlier soft-delete tombstone so
            # the fresh entry is searchable again.
            self._deleted_ids.discard(doc.get("id"))

    def _add_chroma(self, documents: list[dict[str, Any]], embeddings: list[list[float]]) -> None:
        """Add documents to the ChromaDB collection."""
        if self._collection is None:
            return
        ids = [doc.get("id", f"doc_{i}") for i, doc in enumerate(documents)]
        metadatas = [
            {
                "source": doc.get("source", "unknown"),
                "document_id": doc.get("document_id", ""),
                "chunk_index": doc.get("chunk_index", 0),
                **doc.get("metadata", {}),
            }
            for doc in documents
        ]
        # `add` fails if any id already exists - `upsert` re-embeds in place,
        # which is what re-indexing an updated profile fact needs.
        self._collection.upsert(
            ids=ids,
            documents=[doc["content"] for doc in documents],
            embeddings=embeddings,
            metadatas=metadatas,
        )

    async def search(
        self,
        query_embedding: list[float],
        top_k: int = 5,
        filters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Search the vector store for similar documents.

        `filters` matches against both the standard fields and any extra
        `metadata` stored with each document (exact-match, ANDed together).
        """
        if self._backend == "faiss":
            return self._search_faiss(query_embedding, top_k, filters)
        return self._search_chroma(query_embedding, top_k, filters)

    def _search_faiss(
        self, query_embedding: list[float], top_k: int, filters: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        """Search the FAISS index."""
        import numpy as np

        if self._index is None or self._index.ntotal == 0:
            return []
        # Over-fetch so post-filtering (metadata match + tombstoned ids)
        # still leaves up to top_k results instead of starving on a small
        # index where the closest vectors happen to belong to other users.
        fetch_k = min(max(top_k * 5, top_k), self._index.ntotal)
        query = np.array([query_embedding], dtype="float32")
        distances, indices = self._index.search(query, fetch_k)
        results = []
        for i, idx in enumerate(indices[0]):
            if idx < 0 or idx >= len(self._documents):
                continue
            doc = self._documents[idx]
            if doc.get("id") in self._deleted_ids:
                continue
            metadata = doc.get("metadata", {})
            if filters and any(metadata.get(k) != v for k, v in filters.items()):
                continue
            results.append(
                {
                    "id": doc.get("id"),
                    "content": doc["content"],
                    "score": float(distances[0][i]),
                    "source": doc.get("source", "unknown"),
                    "document_id": doc.get("document_id", ""),
                    "metadata": metadata,
                }
            )
            if len(results) >= top_k:
                break
        return results

    def _search_chroma(
        self,
        query_embedding: list[float],
        top_k: int,
        filters: dict[str, Any] | None,
    ) -> list[dict[str, Any]]:
        """Search the ChromaDB collection."""
        if self._collection is None:
            return []
        where = dict(filters) if filters else None
        result = self._collection.query(
            query_embeddings=[query_embedding],
            n_results=top_k,
            where=where,
        )
        results = []
        if result["ids"]:
            for i in range(len(result["ids"][0])):
                metadata = result["metadatas"][0][i] or {}
                results.append(
                    {
                        "id": result["ids"][0][i],
                        "content": result["documents"][0][i],
                        "score": 1.0 - result["distances"][0][i],
                        "source": metadata.get("source", "unknown"),
                        "document_id": metadata.get("document_id", ""),
                        "metadata": metadata,
                    }
                )
        return results

    async def get_by_ids(self, ids: list[str]) -> list[dict[str, Any]]:
        """Fetch chunks by their exact ids, with no similarity ranking involved.

        Used to deterministically pull a specific document's full content
        (its chunk ids are reconstructable from `document_id` + `chunk_count`
        - see RAGRetrievalNode) rather than hoping a query happens to be
        semantically similar enough to surface it via `search()`. A vague
        request like "describe this file" has weak/no semantic similarity to
        the file's actual content, which is exactly the case this exists for.
        """
        if not ids:
            return []
        if self._backend == "faiss":
            wanted = set(ids)
            results = []
            for doc in self._documents:
                if doc.get("id") in wanted and doc.get("id") not in self._deleted_ids:
                    results.append(
                        {
                            "id": doc.get("id"),
                            "content": doc["content"],
                            "score": None,
                            "source": doc.get("source", "unknown"),
                            "document_id": doc.get("document_id", ""),
                            "metadata": doc.get("metadata", {}),
                        }
                    )
            return results

        if self._collection is None:
            return []
        result = self._collection.get(ids=ids)
        results = []
        for i, doc_id in enumerate(result.get("ids", [])):
            metadata = (result.get("metadatas") or [None] * len(result["ids"]))[i] or {}
            results.append(
                {
                    "id": doc_id,
                    "content": result["documents"][i],
                    "score": None,
                    "source": metadata.get("source", "unknown"),
                    "document_id": metadata.get("document_id", ""),
                    "metadata": metadata,
                }
            )
        return results

    async def delete_ids(self, ids: list[str]) -> None:
        """Remove specific documents by id.

        FAISS has no in-place removal, so ids are tombstoned and filtered
        out of future search results rather than physically removed from
        the index.
        """
        if not ids:
            return
        if self._backend == "faiss":
            self._deleted_ids.update(ids)
        elif self._collection is not None:
            try:
                self._collection.delete(ids=ids)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Vector store delete_ids failed: %s", exc)

    async def delete_collection(self, name: str = "documents") -> None:
        """Delete a collection (ChromaDB)."""
        if self._backend == "chroma" and self._collection is not None:
            try:
                import chromadb

                client = chromadb.PersistentClient(path=settings.chroma_persist_dir)
                client.delete_collection(name)
                logger.info("Deleted collection: %s", name)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Could not delete collection: %s", exc)
