"""Repository implementations for each entity."""
from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    Document,
    Feedback,
    File,
    Log,
    Memory,
    Message,
    Thread,
    User,
    UserSetting,
)
from app.repositories.base import BaseRepository


class UserRepository(BaseRepository[User]):
    """Repository for User entity."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, User)

    async def get_by_email(self, email: str) -> User | None:
        """Get a user by email."""
        stmt = select(User).where(User.email == email.lower())
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_username(self, username: str) -> User | None:
        """Get a user by username."""
        stmt = select(User).where(User.username == username)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_provider(self, provider: str, provider_id: str) -> User | None:
        """Get a user by OAuth provider and provider id."""
        stmt = select(User).where(User.provider == provider, User.provider_id == provider_id)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()


class ThreadRepository(BaseRepository[Thread]):
    """Repository for Thread entity."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Thread)

    async def list_for_user(
        self, user_id: str, limit: int = 50, offset: int = 0, search: str | None = None
    ) -> list[Thread]:
        """List threads for a user, optionally filtered by search."""
        stmt = select(Thread).where(Thread.user_id == user_id)
        if search:
            stmt = stmt.where(Thread.title.ilike(f"%{search}%"))
        stmt = stmt.order_by(Thread.updated_at.desc()).limit(limit).offset(offset)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())


class MessageRepository(BaseRepository[Message]):
    """Repository for Message entity."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Message)

    async def list_for_thread(
        self, thread_id: str, limit: int = 50, offset: int = 0
    ) -> list[Message]:
        """List messages for a thread ordered by creation time."""
        stmt = (
            select(Message)
            .where(Message.thread_id == thread_id)
            .order_by(Message.created_at.asc())
            .limit(limit)
            .offset(offset)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def list_recent_for_thread(
        self, thread_id: str, limit: int = 40, before: Any = None
    ) -> list[Message]:
        """Most recent `limit` messages in a thread, oldest first.

        Unlike `list_for_thread` (ascending + offset, for forward pagination),
        this fetches from the *tail* of a thread - `list_for_thread(limit=N)`
        on a thread with more than N messages would return the N OLDEST
        messages, not the most recent ones. `before`, when given, excludes
        anything at or after that timestamp, so a regenerated reply only
        reconstructs the context that existed up to that point in the thread.
        """
        stmt = select(Message).where(Message.thread_id == thread_id)
        if before is not None:
            stmt = stmt.where(Message.created_at <= before)
        stmt = stmt.order_by(Message.created_at.desc()).limit(limit)
        result = await self._session.execute(stmt)
        return list(reversed(result.scalars().all()))


class MemoryRepository(BaseRepository[Memory]):
    """Repository for Memory entity."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Memory)

    async def list_for_user(
        self, user_id: str, memory_type: str | None = None, limit: int = 100
    ) -> list[Memory]:
        """List memories for a user, optionally filtered by type."""
        stmt = select(Memory).where(Memory.user_id == user_id)
        if memory_type:
            stmt = stmt.where(Memory.memory_type == memory_type)
        stmt = stmt.order_by(Memory.importance.desc()).limit(limit)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def get_by_key(self, user_id: str, memory_type: str, key: str) -> Memory | None:
        """Get a user's memory of a given type by its key, if one exists."""
        stmt = select(Memory).where(
            Memory.user_id == user_id, Memory.memory_type == memory_type, Memory.key == key
        )
        result = await self._session.execute(stmt)
        return result.scalars().first()


class DocumentRepository(BaseRepository[Document]):
    """Repository for Document entity."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Document)

    async def list_for_thread(self, thread_id: str, ready_only: bool = True) -> list[Document]:
        """List documents uploaded within a specific conversation.

        Used by RAGRetrievalNode to deterministically include "the file(s)
        uploaded in this conversation" in context, rather than relying on
        semantic search to guess which of the user's documents (possibly
        from unrelated past conversations) a vague question is about.
        """
        from app.db.models import DocumentStatus

        stmt = select(Document).where(Document.thread_id == thread_id)
        if ready_only:
            stmt = stmt.where(Document.status == DocumentStatus.READY)
        stmt = stmt.order_by(Document.created_at.asc())
        result = await self._session.execute(stmt)
        return list(result.scalars().all())


class FeedbackRepository(BaseRepository[Feedback]):
    """Repository for Feedback entity."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Feedback)

    async def get_for_message_and_user(self, message_id: str, user_id: str) -> Feedback | None:
        """Get a user's existing feedback for a message, if any."""
        stmt = select(Feedback).where(
            Feedback.message_id == message_id, Feedback.user_id == user_id
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()


class FileRepository(BaseRepository[File]):
    """Repository for File entity."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, File)


class SettingRepository(BaseRepository[UserSetting]):
    """Repository for UserSetting entity."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, UserSetting)

    async def list_for_user(self, user_id: str) -> list[UserSetting]:
        """List all settings for a user."""
        stmt = select(UserSetting).where(UserSetting.user_id == user_id)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())


class LogRepository(BaseRepository[Log]):
    """Repository for Log entity."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Log)
