"""Thread service - conversation lifecycle management."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.db.models import Thread, ThreadStatus
from app.repositories import ThreadRepository
from app.schemas.chat import ThreadCreate, ThreadUpdate


class ThreadService:
    """Business logic for chat thread management."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db
        self._thread_repo = ThreadRepository(db)

    async def create(self, user_id: str, data: ThreadCreate) -> Thread:
        """Create a new thread for a user."""
        thread = Thread(
            user_id=user_id,
            title=data.title or "New Chat",
            model=data.model,
            metadata_=data.metadata_,
        )
        await self._thread_repo.create(thread)
        await self._thread_repo.commit()
        return thread

    async def get(self, thread_id: str, user_id: str) -> Thread:
        """Get a thread, ensuring ownership."""
        thread = await self._thread_repo.get(thread_id)
        if not thread or thread.user_id != user_id:
            raise NotFoundError("Thread not found")
        return thread

    async def list_for_user(
        self,
        user_id: str,
        page: int = 1,
        page_size: int = 50,
        search: str | None = None,
    ) -> tuple[list[Thread], int]:
        """List threads for a user with pagination and search."""
        offset = (page - 1) * page_size
        threads = await self._thread_repo.list_for_user(
            user_id, limit=page_size, offset=offset, search=search
        )
        # Count via a dedicated query
        stmt = select(Thread).where(Thread.user_id == user_id)
        if search:
            stmt = stmt.where(Thread.title.ilike(f"%{search}%"))
        total = len((await self._db.execute(stmt)).scalars().all())
        return threads, total

    async def update(self, thread_id: str, user_id: str, data: ThreadUpdate) -> Thread:
        """Update thread properties (title, status, pinned, metadata)."""
        thread = await self.get(thread_id, user_id)
        if data.title is not None:
            thread.title = data.title
        if data.status is not None:
            thread.status = data.status
        if data.pinned is not None:
            thread.pinned = data.pinned
        if data.metadata_ is not None:
            thread.metadata_ = {**thread.metadata_, **data.metadata_}
        await self._thread_repo.update(thread)
        await self._thread_repo.commit()
        return thread

    async def archive(self, thread_id: str, user_id: str) -> Thread:
        """Archive a thread."""
        return await self.update(
            thread_id, user_id, ThreadUpdate(status=ThreadStatus.ARCHIVED)
        )

    async def pin(self, thread_id: str, user_id: str, pinned: bool) -> Thread:
        """Pin or unpin a thread."""
        return await self.update(thread_id, user_id, ThreadUpdate(pinned=pinned))

    async def delete(self, thread_id: str, user_id: str) -> None:
        """Delete a thread (cascades to messages)."""
        thread = await self.get(thread_id, user_id)
        await self._thread_repo.delete(thread)
        await self._thread_repo.commit()

    async def touch_last_message(self, thread_id: str) -> None:
        """Update the last_message_at timestamp on a thread."""
        thread = await self._thread_repo.get(thread_id)
        if thread:
            thread.last_message_at = datetime.now(timezone.utc)
            await self._thread_repo.update(thread)
            await self._thread_repo.commit()
