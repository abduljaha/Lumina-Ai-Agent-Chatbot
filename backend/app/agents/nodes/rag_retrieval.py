"""RAG retrieval node - retrieves relevant documents for the query."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.rag.retriever import Retriever

logger = logging.getLogger("app")

# This node runs unconditionally on every message (see graph.py), so unlike
# an explicit "search my documents" tool call, the user never opted into
# waiting on it - a slow embedding backend (e.g. a cold local-model load)
# must not be allowed to stall an otherwise-unrelated turn. Skipping RAG
# context for one turn is a much smaller cost than a multi-second hang on
# every message.
_RAG_TIMEOUT_SECONDS = 8

# Caps how much of "every chunk of every document uploaded in this thread"
# gets deterministically injected into context (see _thread_documents_context
# below) - a budget on total characters, not a per-document truncation, so
# several small files can all fit while one huge one doesn't blow out the
# LLM's context window on its own.
_THREAD_DOCS_CHAR_BUDGET = 12000


class RAGRetrievalNode:
    """Retrieves relevant documents from the knowledge base.

    Two complementary sources feed into context, not just one:

    1. Deterministic: every chunk of every document uploaded *in this
       thread*, unconditionally. A vague question like "describe this file"
       or "summarize this document" has weak-to-no semantic similarity to
       the file's actual content, so similarity search alone routinely
       fails to surface it (or surfaces it tied with unrelated documents
       from other conversations) - this makes an uploaded file reliably
       available without the user having to reference it by name.
    2. Semantic: the existing vector/BM25/rerank search across the user's
       full knowledge base, for cross-thread references ("what did that
       PDF from last week say about...").
    """

    def __init__(self, retriever: Retriever) -> None:
        self._retriever = retriever

    async def __call__(self, state: dict[str, Any]) -> dict[str, Any]:
        """Retrieve documents relevant to the user's query."""
        messages = state.get("messages", [])
        if not messages:
            return {"retrieved_documents": [], "context": None}

        query = getattr(messages[-1], "content", "") or ""
        user_id = state.get("user_id")
        thread_id = state.get("thread_id")

        thread_docs = await self._safe_thread_documents(thread_id)
        semantic_docs = await self._safe_semantic_search(query, user_id)

        # Thread documents take precedence - a semantic hit for a document
        # already included deterministically would just be a duplicate. Also
        # dedupes semantic_docs against each other by document_id: a long-
        # lived account with many past uploads (some possibly near-duplicate
        # content) can otherwise return the same document twice from a
        # single search - the retriever's own hybrid/rerank stages don't
        # guarantee document-level uniqueness, only chunk-level.
        thread_doc_ids = {d.get("document_id") for d in thread_docs}
        seen_ids = set(thread_doc_ids)
        semantic_unique = []
        for doc in semantic_docs:
            doc_id = doc.get("document_id")
            if doc_id in seen_ids:
                continue
            seen_ids.add(doc_id)
            semantic_unique.append(doc)
        merged = thread_docs + semantic_unique

        if not merged:
            logger.info(
                "RAG retrieval: no documents found (thread_id=%s, user_id=%s)", thread_id, user_id
            )
            return {"retrieved_documents": [], "context": None}

        # Explicitly labeled and separated, not just concatenated - an
        # unlabeled mix left the LLM no way to tell "the file(s) actually in
        # this conversation" (what "this file"/"this document" in the user's
        # question refers to) apart from other, only loosely-related
        # material pulled in from the rest of the user's history, which in
        # practice showed up as the model describing the wrong document
        # entirely once a few unrelated files were also similarity-ranked
        # highly.
        context_sections = []
        if thread_docs:
            thread_parts = [f"[{d.get('source') or 'Document'}]: {d.get('content', '')}" for d in thread_docs]
            context_sections.append(
                "=== Files uploaded in this conversation ===\n" + "\n\n".join(thread_parts)
            )
        if semantic_unique:
            other_parts = [f"[{d.get('source') or 'Document'}]: {d.get('content', '')}" for d in semantic_unique]
            context_sections.append(
                "=== Other potentially relevant documents from your knowledge base ===\n"
                + "\n\n".join(other_parts)
            )
        context = "\n\n".join(context_sections)

        logger.info(
            "RAG retrieval: %d document(s) in context (%d from this thread, %d from semantic search)",
            len(merged), len(thread_docs), len(merged) - len(thread_docs),
        )

        return {
            "retrieved_documents": merged,
            "context": context,
            "metadata": {
                **state.get("metadata", {}),
                "retrieved_count": len(merged),
                "thread_document_count": len(thread_docs),
            },
        }

    async def _safe_semantic_search(self, query: str, user_id: str | None) -> list[dict[str, Any]]:
        """Run the normal similarity search, tolerating timeout/failure."""
        try:
            return await asyncio.wait_for(
                self._retriever.retrieve(query=query, top_k=5, user_id=user_id),
                timeout=_RAG_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            logger.warning("Semantic RAG retrieval timed out after %ss, continuing without it", _RAG_TIMEOUT_SECONDS)
            return []
        except Exception:  # noqa: BLE001
            logger.exception("Semantic RAG retrieval failed")
            return []

    async def _safe_thread_documents(self, thread_id: str | None) -> list[dict[str, Any]]:
        """Deterministically fetch this thread's documents, tolerating timeout/failure."""
        if not thread_id:
            return []
        try:
            return await asyncio.wait_for(
                self._thread_documents_context(thread_id), timeout=_RAG_TIMEOUT_SECONDS
            )
        except asyncio.TimeoutError:
            logger.warning("Thread-document retrieval timed out for thread %s", thread_id)
            return []
        except Exception:  # noqa: BLE001
            logger.exception("Thread-document retrieval failed for thread %s", thread_id)
            return []

    async def _thread_documents_context(self, thread_id: str) -> list[dict[str, Any]]:
        """Every chunk of every READY document uploaded in this thread, in order."""
        from app.db.session import async_session_factory
        from app.repositories import DocumentRepository

        async with async_session_factory() as session:
            docs = await DocumentRepository(session).list_for_thread(thread_id)

        if not docs:
            return []

        results: list[dict[str, Any]] = []
        budget = _THREAD_DOCS_CHAR_BUDGET
        for doc in docs:
            if budget <= 0:
                logger.warning(
                    "Thread %s: document char budget exhausted before including %s", thread_id, doc.filename
                )
                break
            ids = [f"{doc.id}_{i}" for i in range(doc.chunk_count)]
            chunks = await self._retriever.get_by_ids(ids)
            # Vector-store lookup order isn't guaranteed to match the
            # document's original order - restore it from chunk_index so
            # the injected content reads coherently top to bottom.
            chunks.sort(key=lambda c: (c.get("metadata") or {}).get("chunk_index", 0))
            for chunk in chunks:
                content = chunk.get("content", "")
                if budget <= 0:
                    break
                if len(content) > budget:
                    content = content[:budget] + "... [truncated]"
                results.append({**chunk, "content": content, "source": doc.filename})
                budget -= len(content)
        return results
