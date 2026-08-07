"""Pydantic schemas for threads and messages."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.db.models import FeedbackType, MessageRole, ThreadStatus


# ---------------------------------------------------------------------------
# Threads
# ---------------------------------------------------------------------------
class ThreadCreate(BaseModel):
    """Thread creation schema."""

    title: str = Field(default="New Chat", max_length=255)
    model: str | None = None
    metadata_: dict[str, Any] = Field(default_factory=dict)


class ThreadUpdate(BaseModel):
    """Thread update schema."""

    title: str | None = Field(default=None, max_length=255)
    status: ThreadStatus | None = None
    pinned: bool | None = None
    metadata_: dict[str, Any] | None = None


class ThreadRead(BaseModel):
    """Thread response schema."""

    id: str
    title: str
    status: ThreadStatus
    pinned: bool
    metadata_: dict[str, Any]
    model: str | None = None
    last_message_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ThreadList(BaseModel):
    """Paginated thread list."""

    items: list[ThreadRead]
    total: int
    page: int
    page_size: int
    has_more: bool


# ---------------------------------------------------------------------------
# Messages
# ---------------------------------------------------------------------------
class MessageAttachment(BaseModel):
    """Message attachment schema."""

    type: str
    name: str
    url: str | None = None
    size: int | None = None


class MessageCreate(BaseModel):
    """Message creation schema."""

    content: str
    attachments: list[MessageAttachment] = Field(default_factory=list)
    images: list[str] = Field(default_factory=list)
    metadata_: dict[str, Any] = Field(default_factory=dict)


class MessageRead(BaseModel):
    """Message response schema."""

    id: str
    thread_id: str
    role: MessageRole
    content: str
    attachments: list[dict[str, Any]]
    images: list[str]
    tokens: int | None = None
    latency_ms: int | None = None
    cost: float | None = None
    model: str | None = None
    metadata_: dict[str, Any]
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class MessageList(BaseModel):
    """Paginated message list."""

    items: list[MessageRead]
    total: int
    has_more: bool
    next_cursor: str | None = None


# ---------------------------------------------------------------------------
# Chat request/response
# ---------------------------------------------------------------------------
class ChatRequest(BaseModel):
    """Chat completion request."""

    thread_id: str | None = None
    message: str
    model: str | None = None
    provider: str | None = None
    stream: bool = True
    attachments: list[MessageAttachment] = Field(default_factory=list)
    images: list[str] = Field(default_factory=list)
    metadata_: dict[str, Any] = Field(default_factory=dict)


class RegenerateRequest(BaseModel):
    """Request to regenerate a specific assistant reply in place."""

    thread_id: str
    message_id: str


class ChatResponse(BaseModel):
    """Chat completion response (non-streaming)."""

    thread_id: str
    message_id: str
    content: str
    model: str
    provider: str
    tokens: int
    latency_ms: int
    cost: float
    citations: list[dict[str, Any]] = Field(default_factory=list)
    metadata_: dict[str, Any] = Field(default_factory=dict)


class FeedbackRequest(BaseModel):
    """Feedback submission schema."""

    feedback_type: FeedbackType
    comment: str | None = Field(default=None, max_length=2000)


class FeedbackRead(BaseModel):
    """Feedback response schema."""

    id: str
    message_id: str
    feedback_type: FeedbackType
    comment: str | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class StreamEvent(BaseModel):
    """Streaming event schema."""

    type: str  # token | message | done | error | tool_call | citation
    content: str | None = None
    data: dict[str, Any] | None = None
