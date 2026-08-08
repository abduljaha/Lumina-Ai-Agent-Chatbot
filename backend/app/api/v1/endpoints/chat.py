"""Chat endpoints - non-streaming and streaming."""
from __future__ import annotations

import json
from typing import Any, AsyncIterator

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, DbDep
from app.core.container import app_container
from app.core.exceptions import NotFoundError
from app.db.models import Feedback, Thread, User
from app.repositories import FeedbackRepository, MessageRepository
from app.schemas.chat import (
    ChatRequest,
    ChatResponse,
    EditMessageRequest,
    FeedbackRead,
    FeedbackRequest,
    RegenerateRequest,
    ThreadCreate,
)
from app.services.thread import ThreadService

router = APIRouter()


def _get_chat_service(db: AsyncSession) -> "ChatService":
    """Build a ChatService lazily so optional packages do not break startup."""
    from app.services.chat import ChatService
    from app.memory.manager import MemoryManager

    return ChatService(db=db, agent_graph=app_container.get_agent(), memory_manager=MemoryManager(db))


async def _ensure_thread(db: AsyncSession, user: User, thread_id: str | None) -> Thread:
    """Resolve the thread, creating one if needed."""
    thread_service = ThreadService(db)
    if not thread_id:
        return await thread_service.create(user.id, ThreadCreate())
    thread = await thread_service.get(thread_id, user.id)
    return thread


@router.post("/messages", response_model=ChatResponse, summary="Send a chat message")
async def send_message(
    request: ChatRequest,
    user: CurrentUser,
    db: DbDep,
) -> ChatResponse:
    """Send a message and get a non-streaming response."""
    thread = await _ensure_thread(db, user, request.thread_id)
    service = _get_chat_service(db)
    result = await service.process_message(user.id, thread.id, request)
    return ChatResponse(**result)


@router.post("/stream", summary="Stream a chat response")
async def stream_chat(
    request: ChatRequest,
    user: CurrentUser,
    db: DbDep,
) -> StreamingResponse:
    """Stream a chat response as server-sent events."""
    thread = await _ensure_thread(db, user, request.thread_id)
    service = _get_chat_service(db)

    async def event_generator() -> AsyncIterator[str]:
        async for event in service.stream_message(user.id, thread.id, request):
            yield f"data: {json.dumps(event, default=str)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/regenerate/stream", summary="Regenerate a specific assistant reply in place")
async def regenerate_chat(
    request: RegenerateRequest,
    user: CurrentUser,
    db: DbDep,
) -> StreamingResponse:
    """Stream a freshly-regenerated reply for an existing assistant message.

    Ownership check happens via `_ensure_thread` (raises NotFoundError if the
    thread isn't the current user's) before the service ever touches the
    message - same pattern as every other thread-scoped route here.
    """
    thread_service = ThreadService(db)
    await thread_service.get(request.thread_id, user.id)
    service = _get_chat_service(db)

    async def event_generator() -> AsyncIterator[str]:
        async for event in service.regenerate_stream(user.id, request.thread_id, request.message_id):
            yield f"data: {json.dumps(event, default=str)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/edit/stream", summary="Edit a user message in place and regenerate everything after it")
async def edit_message(
    request: EditMessageRequest,
    user: CurrentUser,
    db: DbDep,
) -> StreamingResponse:
    """Stream a freshly-generated reply after editing an earlier user message.

    Truncates the conversation from the edited message onward (old reply and
    anything sent after it) - same ownership-check pattern as regenerate.
    """
    thread_service = ThreadService(db)
    await thread_service.get(request.thread_id, user.id)
    service = _get_chat_service(db)

    async def event_generator() -> AsyncIterator[str]:
        async for event in service.edit_and_regenerate_stream(
            user.id, request.thread_id, request.message_id, request.content
        ):
            yield f"data: {json.dumps(event, default=str)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post(
    "/messages/{message_id}/feedback",
    response_model=FeedbackRead,
    summary="Rate an assistant message (thumbs up/down)",
)
async def submit_feedback(
    message_id: str,
    request: FeedbackRequest,
    user: CurrentUser,
    db: DbDep,
) -> Feedback:
    """Create or update the current user's feedback for a message."""
    message_repo = MessageRepository(db)
    message = await message_repo.get(message_id)
    if not message:
        raise NotFoundError("Message not found")

    thread_service = ThreadService(db)
    await thread_service.get(message.thread_id, user.id)  # raises NotFoundError if not owned

    feedback_repo = FeedbackRepository(db)
    existing = await feedback_repo.get_for_message_and_user(message_id, user.id)
    if existing:
        existing.feedback_type = request.feedback_type
        existing.comment = request.comment
        await feedback_repo.update(existing)
        await feedback_repo.commit()
        return existing

    feedback = Feedback(
        message_id=message_id,
        user_id=user.id,
        feedback_type=request.feedback_type,
        comment=request.comment,
    )
    await feedback_repo.create(feedback)
    await feedback_repo.commit()
    return feedback
