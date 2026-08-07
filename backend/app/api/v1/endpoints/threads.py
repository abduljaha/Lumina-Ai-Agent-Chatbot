"""Thread management endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Query

from app.api.deps import CurrentUser, DbDep
from app.db.models import Thread
from app.schemas.chat import (
    MessageList,
    MessageRead,
    ThreadCreate,
    ThreadList,
    ThreadRead,
    ThreadUpdate,
)
from app.services.thread import ThreadService

router = APIRouter()


@router.post("", response_model=ThreadRead, status_code=201, summary="Create a thread")
async def create_thread(
    data: ThreadCreate,
    user: CurrentUser,
    db: DbDep,
) -> Thread:
    """Create a new chat thread."""
    service = ThreadService(db)
    return await service.create(user.id, data)


@router.get("", response_model=ThreadList, summary="List threads")
async def list_threads(
    user: CurrentUser,
    db: DbDep,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    search: str | None = Query(None),
) -> ThreadList:
    """List the current user's threads with pagination and search."""
    service = ThreadService(db)
    threads, total = await service.list_for_user(
        user.id, page=page, page_size=page_size, search=search
    )
    return ThreadList(
        items=[ThreadRead.model_validate(t) for t in threads],
        total=total,
        page=page,
        page_size=page_size,
        has_more=(page * page_size) < total,
    )


@router.get("/{thread_id}", response_model=ThreadRead, summary="Get a thread")
async def get_thread(thread_id: str, user: CurrentUser, db: DbDep) -> Thread:
    """Get a single thread by id."""
    service = ThreadService(db)
    return await service.get(thread_id, user.id)


@router.patch("/{thread_id}", response_model=ThreadRead, summary="Update a thread")
async def update_thread(
    thread_id: str,
    data: ThreadUpdate,
    user: CurrentUser,
    db: DbDep,
) -> Thread:
    """Update a thread's title, status, or pinned flag."""
    service = ThreadService(db)
    return await service.update(thread_id, user.id, data)


# response_model=None is required, not redundant with "-> None": this file's
# `from __future__ import annotations` makes FastAPI resolve that return
# annotation to the NoneType *class* rather than the None singleton, which
# fails the "204 must not have a body" check unless overridden explicitly.
@router.delete("/{thread_id}", status_code=204, response_model=None, summary="Delete a thread")
async def delete_thread(thread_id: str, user: CurrentUser, db: DbDep) -> None:
    """Delete a thread and its messages."""
    service = ThreadService(db)
    await service.delete(thread_id, user.id)


@router.post("/{thread_id}/archive", response_model=ThreadRead, summary="Archive a thread")
async def archive_thread(thread_id: str, user: CurrentUser, db: DbDep) -> Thread:
    """Archive a thread."""
    service = ThreadService(db)
    return await service.archive(thread_id, user.id)


@router.post("/{thread_id}/pin", response_model=ThreadRead, summary="Pin a thread")
async def pin_thread(thread_id: str, user: CurrentUser, db: DbDep) -> Thread:
    """Pin a thread."""
    service = ThreadService(db)
    return await service.pin(thread_id, user.id, True)


@router.post("/{thread_id}/unpin", response_model=ThreadRead, summary="Unpin a thread")
async def unpin_thread(thread_id: str, user: CurrentUser, db: DbDep) -> Thread:
    """Unpin a thread."""
    service = ThreadService(db)
    return await service.pin(thread_id, user.id, False)


@router.get("/{thread_id}/messages", response_model=MessageList, summary="List thread messages")
async def list_messages(
    thread_id: str,
    user: CurrentUser,
    db: DbDep,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> MessageList:
    """List messages in a thread with pagination."""
    from app.repositories import MessageRepository

    # Verify thread ownership
    await ThreadService(db).get(thread_id, user.id)
    msg_repo = MessageRepository(db)
    messages = await msg_repo.list_for_thread(thread_id, limit=limit, offset=offset)
    total = len(messages)
    return MessageList(
        items=[MessageRead.model_validate(m) for m in messages],
        total=total,
        has_more=(offset + limit) < total,
    )
