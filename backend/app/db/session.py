"""Database session management and base model.

Provides:
- Async SQLAlchemy engine/session
- Base declarative model
- Session dependency for FastAPI
- Automatic fallback to SQLite when PostgreSQL is unavailable
"""
from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from datetime import datetime, timezone

from sqlalchemy import DateTime, MetaData
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.core.config import get_settings

settings = get_settings()
logger = logging.getLogger("app")

# Metadata with naming convention for Alembic autogenerate
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

metadata = MetaData(naming_convention=NAMING_CONVENTION)


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""

    metadata = metadata


class TimestampMixin:
    """Mixin adding created_at and updated_at timestamps."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )


def _build_engine_url() -> str:
    """Return the database URL, falling back to SQLite if needed."""
    import os

    override = os.getenv("DATABASE_OVERRIDE_URL")
    if override:
        return override

    configured = str(settings.database_url)

    if configured.startswith("sqlite"):
        return configured

    if not settings.is_production:
        logger.warning(
            "PostgreSQL not configured for dev; using SQLite fallback. "
            "Set DATABASE_URL for PostgreSQL in production."
        )
        return "sqlite+aiosqlite:///./ai_chatbot.db"

    return configured


def _create_engine():
    """Create an async engine, using SQLite fallback when not in production."""
    db_url = _build_engine_url()

    if db_url.startswith("sqlite"):
        return create_async_engine(
            db_url,
            echo=settings.sql_echo,
            pool_pre_ping=True,
        ), db_url

    try:
        engine = create_async_engine(
            db_url,
            echo=settings.sql_echo,
            pool_pre_ping=True,
            pool_size=20,
            max_overflow=10,
        )
        return engine, db_url
    except Exception as exc:
        logger.warning("Failed to create PostgreSQL engine (%s); using SQLite.", exc)
        fallback = "sqlite+aiosqlite:///./ai_chatbot.db"
        return create_async_engine(fallback, echo=settings.sql_echo, pool_pre_ping=True), fallback


engine, _active_db_url = _create_engine()

async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Yield a database session for FastAPI dependency injection."""
    async with async_session_factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def init_db() -> None:
    """Create all tables (used in development/tests)."""
    from app.db import models  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_apply_lightweight_migrations)
    logger.info("Database initialized (engine=%s)", str(engine.url).split("///")[0])


# ---------------------------------------------------------------------------
# Lightweight migrations
#
# `create_all` only creates tables that don't exist yet - it never adds a
# column to a table that's already there, so a schema change like adding
# `documents.thread_id` would silently never take effect on an existing dev
# or production database. There's no Alembic migration actually wired up in
# this project (see the RevokedToken/AccountLockout comment in models.py),
# so each column addition here is applied by hand, guarded by an existence
# check so it's a no-op on a database that already has it (including a
# brand-new one from `create_all` above, which already includes it).
# ---------------------------------------------------------------------------
_COLUMN_MIGRATIONS: list[tuple[str, str, str]] = [
    # (table, column, DDL to add it)
    ("documents", "thread_id", "ALTER TABLE documents ADD COLUMN thread_id VARCHAR(36)"),
]


def _apply_lightweight_migrations(conn) -> None:
    """Add any columns from `_COLUMN_MIGRATIONS` missing from an existing database."""
    from sqlalchemy import inspect, text

    inspector = inspect(conn)
    existing_tables = set(inspector.get_table_names())
    for table, column, ddl in _COLUMN_MIGRATIONS:
        if table not in existing_tables:
            continue  # create_all just made it fresh, with the column already
        existing_columns = {c["name"] for c in inspector.get_columns(table)}
        if column in existing_columns:
            continue
        logger.info("Migrating: adding %s.%s", table, column)
        conn.execute(text(ddl))
