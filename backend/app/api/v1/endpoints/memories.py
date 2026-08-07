"""Memory management endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Query

from app.api.deps import CurrentUser, DbDep
from app.core.exceptions import NotFoundError
from app.db.models import Memory, MemoryType
from app.memory.manager import MemoryManager
from app.schemas.models import MemoryCreate, MemoryList, MemoryRead, MemoryUpdate

router = APIRouter()


@router.get("", response_model=MemoryList, summary="List memories")
async def list_memories(
    user: CurrentUser,
    db: DbDep,
    memory_type: MemoryType | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
) -> MemoryList:
    """List the current user's memories."""
    manager = MemoryManager(db)
    memories = await manager.retrieve(user.id, memory_type=memory_type, limit=limit)
    return MemoryList(
        items=[MemoryRead.model_validate(m) for m in memories],
        total=len(memories),
    )


@router.post("", response_model=MemoryRead, status_code=201, summary="Create a memory")
async def create_memory(
    data: MemoryCreate,
    user: CurrentUser,
    db: DbDep,
) -> Memory:
    """Create a new memory for the current user."""
    manager = MemoryManager(db)
    return await manager.add(
        user.id,
        data.content,
        data.memory_type,
        key=data.key,
        importance=data.importance,
        metadata=data.metadata_,
    )


@router.patch("/{memory_id}", response_model=MemoryRead, summary="Update a memory")
async def update_memory(
    memory_id: str,
    data: MemoryUpdate,
    user: CurrentUser,
    db: DbDep,
) -> Memory:
    """Update a memory's content, importance, or metadata.

    404s (rather than exposing whether the id exists) if it doesn't belong
    to the current user - same ownership check as delete.
    """
    manager = MemoryManager(db)
    memory = await manager.update(
        memory_id,
        user.id,
        content=data.content,
        importance=data.importance,
        metadata=data.metadata_,
    )
    if memory is None:
        raise NotFoundError("Memory not found")
    return memory


# response_model=None required alongside status_code=204 - see threads.py's
# delete_thread for why "-> None" alone isn't enough under this file's
# `from __future__ import annotations`.
@router.delete("/{memory_id}", status_code=204, response_model=None, summary="Delete a memory")
async def delete_memory(memory_id: str, user: CurrentUser, db: DbDep) -> None:
    """Delete a specific memory."""
    manager = MemoryManager(db)
    await manager.delete(memory_id, user.id)


@router.delete("", status_code=204, response_model=None, summary="Clear memories")
async def clear_memories(
    user: CurrentUser,
    db: DbDep,
    memory_type: MemoryType | None = Query(None),
) -> None:
    """Clear all memories, optionally by type."""
    manager = MemoryManager(db)
    await manager.clear(user.id, memory_type)


@router.get("/context", response_model=dict, summary="Get memory context bundle")
async def get_context(
    user: CurrentUser,
    db: DbDep,
    thread_id: str | None = Query(None),
) -> dict:
    """Return the full memory context bundle for the user."""
    manager = MemoryManager(db)
    return await manager.retrieve_for_context(user.id, thread_id=thread_id)
