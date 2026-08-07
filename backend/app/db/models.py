"""SQLAlchemy ORM models for all database tables.

Tables:
- users
- chats
- threads
- messages
- memory
- documents
- embeddings
- feedback
- settings
- logs
- files
"""
from __future__ import annotations

import enum
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    Uuid,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base, TimestampMixin


def gen_uuid() -> str:
    """Generate a string UUID primary key."""
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------
class UserRole(str, enum.Enum):
    USER = "user"
    ADMIN = "admin"
    MODERATOR = "moderator"


class AuthProvider(str, enum.Enum):
    LOCAL = "local"
    GOOGLE = "google"
    GITHUB = "github"


class MessageRole(str, enum.Enum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"
    TOOL = "tool"


class MemoryType(str, enum.Enum):
    SHORT_TERM = "short_term"
    LONG_TERM = "long_term"
    CONVERSATION = "conversation"
    SUMMARIZATION = "summarization"
    ENTITY = "entity"
    SEMANTIC = "semantic"
    USER_PREFERENCE = "user_preference"
    THREAD = "thread"


class FeedbackType(str, enum.Enum):
    THUMBS_UP = "thumbs_up"
    THUMBS_DOWN = "thumbs_down"


class ThreadStatus(str, enum.Enum):
    ACTIVE = "active"
    ARCHIVED = "archived"
    PINNED = "pinned"


class DocumentStatus(str, enum.Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------
class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True, default=gen_uuid)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    username: Mapped[str] = mapped_column(String(100), unique=True, index=True, nullable=False)
    full_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    hashed_password: Mapped[str | None] = mapped_column(String(255), nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole, name="user_role"), default=UserRole.USER, nullable=False
    )
    provider: Mapped[AuthProvider] = mapped_column(
        Enum(AuthProvider, name="auth_provider"), default=AuthProvider.LOCAL, nullable=False
    )
    provider_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    preferences: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    threads: Mapped[list["Thread"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    memories: Mapped[list["Memory"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    documents: Mapped[list["Document"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    settings: Mapped[list["UserSetting"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


# ---------------------------------------------------------------------------
# Chats / Threads
# ---------------------------------------------------------------------------
class Thread(Base, TimestampMixin):
    __tablename__ = "threads"

    id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True, default=gen_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(255), default="New Chat")
    status: Mapped[ThreadStatus] = mapped_column(
        Enum(ThreadStatus, name="thread_status"), default=ThreadStatus.ACTIVE
    )
    pinned: Mapped[bool] = mapped_column(Boolean, default=False)
    metadata_: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, default=dict)
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    model: Mapped[str | None] = mapped_column(String(255), nullable=True)

    user: Mapped[User] = relationship(back_populates="threads")
    messages: Mapped[list["Message"]] = relationship(
        back_populates="thread", cascade="all, delete-orphan", order_by="Message.created_at"
    )

    __table_args__ = (
        Index("ix_threads_user_status", "user_id", "status"),
        Index("ix_threads_user_updated", "user_id", "updated_at"),
    )


# ---------------------------------------------------------------------------
# Messages
# ---------------------------------------------------------------------------
class Message(Base, TimestampMixin):
    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True, default=gen_uuid)
    thread_id: Mapped[str] = mapped_column(ForeignKey("threads.id", ondelete="CASCADE"), index=True)
    role: Mapped[MessageRole] = mapped_column(Enum(MessageRole, name="message_role"))
    content: Mapped[str] = mapped_column(Text, default="")
    attachments: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    images: Mapped[list[str]] = mapped_column(JSON, default=list)
    tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cost: Mapped[float | None] = mapped_column(Float, nullable=True)
    model: Mapped[str | None] = mapped_column(String(255), nullable=True)
    metadata_: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, default=dict)

    thread: Mapped[Thread] = relationship(back_populates="messages")
    feedback: Mapped[list["Feedback"]] = relationship(
        back_populates="message", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_messages_thread_role", "thread_id", "role"),
        Index("ix_messages_thread_created", "thread_id", "created_at"),
    )


# ---------------------------------------------------------------------------
# Memory
# ---------------------------------------------------------------------------
class Memory(Base, TimestampMixin):
    __tablename__ = "memory"

    id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True, default=gen_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    thread_id: Mapped[str | None] = mapped_column(
        ForeignKey("threads.id", ondelete="CASCADE"), nullable=True, index=True
    )
    memory_type: Mapped[MemoryType] = mapped_column(Enum(MemoryType, name="memory_type"))
    content: Mapped[str] = mapped_column(Text)
    key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    importance: Mapped[float] = mapped_column(Float, default=0.5)
    metadata_: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, default=dict)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped[User] = relationship(back_populates="memories")

    __table_args__ = (
        Index("ix_memory_user_type", "user_id", "memory_type"),
        Index("ix_memory_user_key", "user_id", "key"),
    )


# ---------------------------------------------------------------------------
# Documents
# ---------------------------------------------------------------------------
class Document(Base, TimestampMixin):
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True, default=gen_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    # Nullable: a document can be uploaded to the general knowledge base with
    # no conversation context (e.g. a future "manage my documents" screen),
    # but when uploaded from a chat this ties it to that specific
    # conversation - see RAGRetrievalNode, which uses this to deterministically
    # surface "the file I just uploaded here" instead of relying on pure
    # semantic similarity to guess which of the user's many documents a vague
    # question like "describe this file" is even about.
    thread_id: Mapped[str | None] = mapped_column(
        ForeignKey("threads.id", ondelete="SET NULL"), nullable=True, index=True
    )
    filename: Mapped[str] = mapped_column(String(500))
    file_path: Mapped[str] = mapped_column(String(1000))
    file_type: Mapped[str] = mapped_column(String(50))
    file_size: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[DocumentStatus] = mapped_column(
        Enum(DocumentStatus, name="document_status"), default=DocumentStatus.PENDING
    )
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, default=dict)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)

    user: Mapped[User] = relationship(back_populates="documents")
    embeddings: Mapped[list["Embedding"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )


# ---------------------------------------------------------------------------
# Embeddings
# ---------------------------------------------------------------------------
class Embedding(Base, TimestampMixin):
    __tablename__ = "embeddings"

    id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True, default=gen_uuid)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    chunk_index: Mapped[int] = mapped_column(Integer, default=0)
    content: Mapped[str] = mapped_column(Text)
    vector: Mapped[list[float]] = mapped_column(JSON)  # stored for reference; primary search in vector DB
    metadata_: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, default=dict)

    document: Mapped[Document] = relationship(back_populates="embeddings")

    __table_args__ = (
        UniqueConstraint("document_id", "chunk_index", name="uq_embedding_doc_chunk"),
    )


# ---------------------------------------------------------------------------
# Feedback
# ---------------------------------------------------------------------------
class Feedback(Base, TimestampMixin):
    __tablename__ = "feedback"

    id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True, default=gen_uuid)
    message_id: Mapped[str] = mapped_column(ForeignKey("messages.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    feedback_type: Mapped[FeedbackType] = mapped_column(Enum(FeedbackType, name="feedback_type"))
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)

    message: Mapped[Message] = relationship(back_populates="feedback")


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------
class UserSetting(Base, TimestampMixin):
    __tablename__ = "settings"

    id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True, default=gen_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    key: Mapped[str] = mapped_column(String(100))
    value: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    user: Mapped[User] = relationship(back_populates="settings")

    __table_args__ = (
        UniqueConstraint("user_id", "key", name="uq_settings_user_key"),
    )


# ---------------------------------------------------------------------------
# Logs
# ---------------------------------------------------------------------------
class Log(Base, TimestampMixin):
    __tablename__ = "logs"

    id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True, default=gen_uuid)
    user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    level: Mapped[str] = mapped_column(String(20), default="info")
    message: Mapped[str] = mapped_column(Text)
    path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    method: Mapped[str | None] = mapped_column(String(10), nullable=True)
    status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    metadata_: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, default=dict)

    __table_args__ = (
        Index("ix_logs_user_created", "user_id", "created_at"),
        Index("ix_logs_level_created", "level", "created_at"),
    )


# ---------------------------------------------------------------------------
# Files
# ---------------------------------------------------------------------------
class File(Base, TimestampMixin):
    __tablename__ = "files"

    id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True, default=gen_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    filename: Mapped[str] = mapped_column(String(500))
    stored_path: Mapped[str] = mapped_column(String(1000))
    content_type: Mapped[str] = mapped_column(String(100))
    size: Mapped[int] = mapped_column(Integer, default=0)
    category: Mapped[str] = mapped_column(String(50), default="document")  # document|image|audio|video
    metadata_: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, default=dict)


# ---------------------------------------------------------------------------
# Auth security (revoked tokens, login lockout)
#
# Both are new tables rather than new columns on `users` - there's no
# Alembic migration in place yet (see backend/alembic/versions/), so ALTERing
# an existing table isn't safe against an already-populated dev/prod DB, but
# a new table is created automatically by `Base.metadata.create_all()` at
# startup (see db/session.py's init_db) with no migration needed.
# ---------------------------------------------------------------------------
class RevokedToken(Base):
    """Deny-list of refresh-token `jti`s that must no longer be honored.

    Populated on logout and on refresh-token rotation (the token used to
    mint a new pair is revoked immediately, so it can't be replayed). A DB
    table rather than an in-memory set since revocation must survive process
    restarts and be visible across multiple worker processes.
    """

    __tablename__ = "revoked_tokens"

    jti: Mapped[str] = mapped_column(String(64), primary_key=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AccountLockout(Base):
    """Failed-login tracking for brute-force protection, keyed by user."""

    __tablename__ = "account_lockouts"

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    failed_attempts: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
