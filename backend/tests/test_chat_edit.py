"""Tests for the message-edit flow: PATCH content in place, truncate, regenerate.

Uses a fake agent graph (no real LLM/network call) so this is fast and
deterministic - the assertions are about *what the endpoint does to the
thread's messages*, not about model output quality.
"""
from __future__ import annotations

import json

import pytest
import pytest_asyncio

from app.core.container import app_container


class _FakeAgentGraph:
    """Stands in for the real LangGraph agent - always answers the same way."""

    def __init__(self, reply: str = "Fake reply") -> None:
        self.model_router = object()
        self._reply = reply

    async def invoke(self, state, config=None):
        return {
            "generation": self._reply,
            "current_model": "fake-model",
            "current_provider": "fake",
            "token_usage": {},
            "cost": 0.0,
            "citations": [],
        }

    async def stream(self, state, config=None):
        yield {
            "llm_node": {
                "generation": self._reply,
                "current_model": "fake-model",
                "current_provider": "fake",
            }
        }


@pytest_asyncio.fixture(autouse=True)
async def _fake_agent():
    """Point the app container at a fake agent for the duration of each test."""
    app_container._agent = _FakeAgentGraph()
    yield
    app_container._agent = None


async def _register_and_login(client, email: str) -> str:
    payload = {
        "email": email,
        "username": email.split("@")[0],
        "password": "StrongPass123",
        "full_name": "Test User",
    }
    reg = await client.post("/api/v1/auth/register", json=payload)
    assert reg.status_code == 201, reg.text
    login = await client.post(
        "/api/v1/auth/login", json={"email": email, "password": payload["password"]}
    )
    assert login.status_code == 200, login.text
    return login.json()["access_token"]


async def _create_thread(client, token: str) -> str:
    resp = await client.post(
        "/api/v1/threads", json={}, headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _send(client, token: str, thread_id: str, message: str) -> dict:
    resp = await client.post(
        "/api/v1/chat/messages",
        headers={"Authorization": f"Bearer {token}"},
        json={"thread_id": thread_id, "message": message, "stream": False},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _list_messages(client, token: str, thread_id: str) -> list[dict]:
    resp = await client.get(
        f"/api/v1/threads/{thread_id}/messages", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["items"]


def _parse_sse_events(body: str) -> list[dict]:
    events = []
    for chunk in body.split("\n\n"):
        chunk = chunk.strip()
        if chunk.startswith("data: "):
            events.append(json.loads(chunk[len("data: "):]))
    return events


async def _edit(client, token: str, thread_id: str, message_id: str, content: str) -> list[dict]:
    resp = await client.post(
        "/api/v1/chat/edit/stream",
        headers={"Authorization": f"Bearer {token}"},
        json={"thread_id": thread_id, "message_id": message_id, "content": content},
    )
    assert resp.status_code == 200, resp.text
    return _parse_sse_events(resp.text)


@pytest.mark.asyncio
async def test_edit_updates_content_and_truncates_and_regenerates(client) -> None:
    token = await _register_and_login(client, "edit1@example.com")
    thread_id = await _create_thread(client, token)

    await _send(client, token, thread_id, "What is 2+2?")
    await _send(client, token, thread_id, "Actually, what is 3+3?")

    before = await _list_messages(client, token, thread_id)
    assert len(before) == 4  # U1, A1, U2, A2
    first_user_message = before[0]
    assert first_user_message["role"] == "user"

    events = await _edit(
        client, token, thread_id, first_user_message["id"], "What is 10+10?"
    )
    assert any(e["type"] == "done" for e in events), events
    assert not any(e["type"] == "error" for e in events), events

    after = await _list_messages(client, token, thread_id)
    # The edited user message plus exactly one fresh reply - the old reply
    # and the second exchange (which depended on the pre-edit prompt) are
    # gone, not left dangling alongside the new branch.
    assert len(after) == 2
    assert after[0]["role"] == "user"
    assert after[0]["content"] == "What is 10+10?"
    assert after[1]["role"] == "assistant"
    assert after[1]["content"] == "Fake reply"


@pytest.mark.asyncio
async def test_edit_rejects_assistant_message(client) -> None:
    token = await _register_and_login(client, "edit2@example.com")
    thread_id = await _create_thread(client, token)
    await _send(client, token, thread_id, "Hello")

    messages = await _list_messages(client, token, thread_id)
    assistant_message = next(m for m in messages if m["role"] == "assistant")

    events = await _edit(client, token, thread_id, assistant_message["id"], "New content")
    assert any(e["type"] == "error" for e in events)

    # Nothing was mutated - editing a non-user message must be a no-op.
    after = await _list_messages(client, token, thread_id)
    assert len(after) == len(messages)


@pytest.mark.asyncio
async def test_edit_rejects_message_from_a_different_thread(client) -> None:
    token = await _register_and_login(client, "edit3@example.com")
    thread_a = await _create_thread(client, token)
    thread_b = await _create_thread(client, token)
    await _send(client, token, thread_a, "Hello from thread A")

    messages_a = await _list_messages(client, token, thread_a)
    user_message = next(m for m in messages_a if m["role"] == "user")

    # Targeting thread B's edit endpoint with a message that actually
    # belongs to thread A must be rejected, not silently edit across threads.
    events = await _edit(client, token, thread_b, user_message["id"], "Hijacked content")
    assert any(e["type"] == "error" for e in events)
