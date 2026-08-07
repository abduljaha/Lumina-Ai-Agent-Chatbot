"""Repository layer - data access abstractions.

Repositories encapsulate DB queries and are injected into services.
"""
from __future__ import annotations

from typing import Any, Generic, TypeVar

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import Base

ModelType = TypeVar("ModelType", bound=Base)


class BaseRepository(Generic[ModelType]):
    """Generic base repository with common CRUD operations."""

    def __init__(self, session: AsyncSession, model: type[ModelType]) -> None:
        self._session = session
        self._model = model

    async def get(self, entity_id: str) -> ModelType | None:
        """Get a single entity by primary key."""
        return await self._session.get(self._model, entity_id)

    async def list(self, *filters: Any, limit: int = 50, offset: int = 0) -> list[ModelType]:
        """List entities matching filters."""
        stmt = select(self._model).where(*filters).limit(limit).offset(offset)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def count(self, *filters: Any) -> int:
        """Count entities matching filters."""
        from sqlalchemy import func

        stmt = select(func.count()).select_from(self._model).where(*filters)
        result = await self._session.execute(stmt)
        return int(result.scalar_one())

    async def create(self, entity: ModelType) -> ModelType:
        """Create a new entity."""
        self._session.add(entity)
        await self._session.flush()
        return entity

    async def update(self, entity: ModelType) -> ModelType:
        """Update an existing entity."""
        await self._session.flush()
        return entity

    async def delete(self, entity: ModelType) -> None:
        """Delete an entity."""
        await self._session.delete(entity)
        await self._session.flush()

    async def commit(self) -> None:
        """Commit the current transaction."""
        await self._session.commit()
