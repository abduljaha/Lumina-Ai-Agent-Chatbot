"""End-to-end tests for the RAG pipeline: upload -> index -> thread-scoped retrieval.

This is the regression suite for the bug where a user uploads a file, asks
a vague question like "describe this file", and the app answers as if no
file was ever provided - the actual root cause was that retrieval only had
generic semantic similarity to go on, which doesn't reliably match a file
against a query that doesn't resemble its content at all. Fixed by tying an
uploaded document to the thread it was uploaded in (`Document.thread_id`)
and having RAGRetrievalNode deterministically include that thread's
documents in context regardless of how the question is phrased.

Uses a fake, offline embedder and an ephemeral in-memory FAISS store (see
`_isolated_rag_container`) - never the real network-backed embedder or the
developer's actual persisted vector store.
"""
from __future__ import annotations

import hashlib
from types import SimpleNamespace

import pytest
import pytest_asyncio

from app.agents.nodes.rag_retrieval import RAGRetrievalNode
from app.core.container import app_container
from app.rag.hybrid_search import HybridSearch
from app.rag.retriever import Retriever
from app.rag.vectorstore import VectorStore


class _FakeEmbedder:
    """Deterministic, offline embedder - no network calls, no API keys needed."""

    _backend = "fake-test-embedder"

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._vec(t) for t in texts]

    async def embed_query(self, text: str) -> list[float]:
        return self._vec(text)

    @staticmethod
    def _vec(text: str) -> list[float]:
        digest = hashlib.sha256(text.encode()).digest()
        return [b / 255 for b in digest[:32]]


class _PassthroughReranker:
    """No-op stand-in for the real cross-encoder reranker.

    The real `Reranker` downloads an ML model from HuggingFace on first
    construction - fine for the running app (loaded once, cached), but
    rebuilding it fresh in every test would mean a network call (and real
    latency) per test. Reranking quality isn't what these tests are about.
    """

    async def rerank(self, query: str, documents: list[dict], top_k: int = 5) -> list[dict]:
        return documents[:top_k]


@pytest_asyncio.fixture(autouse=True)
async def _isolated_rag_container():
    """Point the app container at an ephemeral store for the duration of each test."""
    vector_store = VectorStore(db_type="faiss", collection="test-rag")
    embedder = _FakeEmbedder()
    app_container._vector_store = vector_store
    app_container._embedder = embedder
    # Built directly (not left for get_retriever() to construct) so it uses
    # the fake reranker above instead of the real network-backed one.
    app_container._retriever = Retriever(
        vector_store=vector_store,
        embedder=embedder,
        hybrid_search=HybridSearch(),
        reranker=_PassthroughReranker(),
    )
    yield
    app_container._vector_store = None
    app_container._embedder = None
    app_container._retriever = None


async def _register_and_login(client, email: str) -> tuple[str, str]:
    """Register+login a fresh user, returning (user_id, access_token)."""
    payload = {
        "email": email,
        "username": email.split("@")[0],
        "password": "StrongPass123",
        "full_name": "Test User",
    }
    reg = await client.post("/api/v1/auth/register", json=payload)
    assert reg.status_code == 201, reg.text
    user_id = reg.json()["id"]
    login = await client.post(
        "/api/v1/auth/login", json={"email": email, "password": payload["password"]}
    )
    assert login.status_code == 200, login.text
    return user_id, login.json()["access_token"]


async def _create_thread(client, token: str) -> str:
    resp = await client.post(
        "/api/v1/threads", json={}, headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _upload_text(client, token: str, thread_id: str, filename: str, text: str) -> dict:
    resp = await client.post(
        "/api/v1/files/documents",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": (filename, text.encode(), "text/plain")},
        data={"thread_id": thread_id},
    )
    return resp


@pytest.mark.asyncio
async def test_upload_indexes_and_scopes_to_thread(client) -> None:
    _, token = await _register_and_login(client, "rag1@example.com")
    thread_id = await _create_thread(client, token)

    resp = await _upload_text(
        client, token, thread_id, "report.txt",
        "Quarterly revenue for Northwind Traders was $1,842,300 in Q2 2026.",
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["status"] == "ready"
    assert data["chunk_count"] > 0
    assert data["thread_id"] == thread_id


@pytest.mark.asyncio
async def test_unsupported_extension_rejected(client) -> None:
    _, token = await _register_and_login(client, "rag2@example.com")
    thread_id = await _create_thread(client, token)
    resp = await client.post(
        "/api/v1/files/documents",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": ("archive.zip", b"not a real zip", "application/zip")},
        data={"thread_id": thread_id},
    )
    assert resp.status_code == 422  # ValidationError -> 422 (see core/exceptions.py)


@pytest.mark.asyncio
async def test_empty_file_rejected(client) -> None:
    _, token = await _register_and_login(client, "rag3@example.com")
    thread_id = await _create_thread(client, token)
    resp = await _upload_text(client, token, thread_id, "empty.txt", "")
    assert resp.status_code == 422  # ValidationError -> 422 (see core/exceptions.py)


@pytest.mark.asyncio
async def test_corrupt_file_marked_failed_with_clear_error(client) -> None:
    """A file with a supported extension but garbage content must fail clearly, not silently succeed with 0 chunks."""
    _, token = await _register_and_login(client, "rag4@example.com")
    thread_id = await _create_thread(client, token)
    resp = await client.post(
        "/api/v1/files/documents",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": ("broken.docx", b"this is not a real docx file", "application/octet-stream")},
        data={"thread_id": thread_id},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "failed"
    assert data["metadata_"].get("error")  # a specific, non-empty reason, not silence


@pytest.mark.asyncio
async def test_describe_this_file_retrieves_uploaded_content(client) -> None:
    """The exact regression case: a vague question must still surface the file just uploaded in this thread."""
    user_id, token = await _register_and_login(client, "rag5@example.com")
    thread_id = await _create_thread(client, token)

    upload = await _upload_text(
        client, token, thread_id, "policy.txt",
        "Return Policy: items may be returned within 45 days of purchase for a full refund.",
    )
    assert upload.json()["status"] == "ready"

    retriever = app_container.get_retriever()
    node = RAGRetrievalNode(retriever)
    state = {
        "messages": [SimpleNamespace(content="Describe this file")],
        "user_id": user_id,
        "thread_id": thread_id,
    }
    result = await node(state)

    assert result["context"] is not None
    assert "45 days" in result["context"]
    assert result["metadata"]["thread_document_count"] == 1


@pytest.mark.asyncio
async def test_thread_documents_are_isolated_from_other_threads(client) -> None:
    """Deterministic thread-scoped inclusion must only ever pull *this* thread's documents.

    Semantic search is deliberately still allowed to surface other threads'
    documents too (cross-thread references, e.g. "what did that other file
    say") - that's a feature, not a leak - so this checks the specific,
    deterministic guarantee (`thread_document_count` and which document it
    came from), not that the rest of the user's knowledge base is
    invisible.
    """
    user_id, token = await _register_and_login(client, "rag6@example.com")
    thread_a = await _create_thread(client, token)
    thread_b = await _create_thread(client, token)

    await _upload_text(client, token, thread_a, "a.txt", "Project Aurora budget is $240,000.")
    await _upload_text(client, token, thread_b, "b.txt", "Project Zephyr budget is $99,000.")

    retriever = app_container.get_retriever()
    node = RAGRetrievalNode(retriever)

    result_b = await node(
        {
            "messages": [SimpleNamespace(content="What is the budget for this project?")],
            "user_id": user_id,
            "thread_id": thread_b,
        }
    )
    assert result_b["context"] is not None
    assert "99,000" in result_b["context"]
    # Exactly one document was deterministically pulled in for this thread,
    # and it's the one actually uploaded here - not thread A's.
    assert result_b["metadata"]["thread_document_count"] == 1
    assert result_b["retrieved_documents"][0]["source"] == "b.txt"


@pytest.mark.asyncio
async def test_multiple_file_types_all_retrievable_in_same_thread(client) -> None:
    """Several formats uploaded into one conversation must all be available together."""
    user_id, token = await _register_and_login(client, "rag7@example.com")
    thread_id = await _create_thread(client, token)

    await _upload_text(client, token, thread_id, "notes.json", '{"owner": "Priya Desai"}')
    await _upload_text(
        client, token, thread_id, "policy.html",
        "<html><body><p>Refunds within 45 days.</p></body></html>",
    )
    await _upload_text(client, token, thread_id, "readme.md", "# Setup\nRun `make install` first.")

    retriever = app_container.get_retriever()
    node = RAGRetrievalNode(retriever)
    result = await node(
        {
            "messages": [SimpleNamespace(content="Summarize everything I've shared")],
            "user_id": user_id,
            "thread_id": thread_id,
        }
    )
    assert result["metadata"]["thread_document_count"] == 3
    assert "Priya Desai" in result["context"]
    assert "45 days" in result["context"]
    assert "make install" in result["context"]


@pytest.mark.asyncio
async def test_no_documents_returns_empty_context_not_an_error(client) -> None:
    """A thread with nothing uploaded must retrieve cleanly with no context, not raise."""
    user_id, token = await _register_and_login(client, "rag8@example.com")
    thread_id = await _create_thread(client, token)

    retriever = app_container.get_retriever()
    node = RAGRetrievalNode(retriever)
    result = await node(
        {
            "messages": [SimpleNamespace(content="Describe this file")],
            "user_id": user_id,
            "thread_id": thread_id,
        }
    )
    assert result["context"] is None
    assert result["retrieved_documents"] == []
