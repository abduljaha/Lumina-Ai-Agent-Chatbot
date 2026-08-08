"""Shared pytest fixtures.

Sets up an in-memory SQLite database for isolated, dependency-free tests.
The `get_db` dependency is overridden so the API routes use the test DB.
"""
from __future__ import annotations

from collections.abc import AsyncGenerator

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.security import hash_password
from app.db import models as db_models  # noqa: F401  (ensure models are registered)
from app.db.models import User
from app.db.session import Base, get_db

# In-memory SQLite test database
_test_engine = create_async_engine("sqlite+aiosqlite:///:memory:")
_test_session_factory = async_sessionmaker(
    _test_engine, class_=AsyncSession, expire_on_commit=False
)


async def _create_test_tables() -> None:
    """Create all tables in the test database."""
    async with _test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def _override_get_db() -> AsyncGenerator[AsyncSession, None]:
    """Yield a test database session."""
    async with _test_session_factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


@pytest_asyncio.fixture(autouse=True)
async def _setup_test_db() -> AsyncGenerator[None, None]:
    """Create tables before each test and clean up after.

    Also patches `app.db.session.async_session_factory` itself, not just
    the `get_db` FastAPI dependency above - some code (RAGRetrievalNode,
    MemoryRetrievalNode, the background LLM profile-update task) opens its
    own session directly via a lazy `from app.db.session import
    async_session_factory` inside the function body, since it runs outside
    any request's DI scope. Without this, that code silently reads/writes
    the real dev database instead of the test one, so a document uploaded
    through `client` in a test would be invisible to it.
    """
    import app.db.session as db_session_module

    original_factory = db_session_module.async_session_factory
    db_session_module.async_session_factory = _test_session_factory
    await _create_test_tables()
    yield
    async with _test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    db_session_module.async_session_factory = original_factory


@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """Provide a raw session on the same in-memory test DB `client` uses.

    For tests that exercise a service/repository directly (no HTTP layer
    involved) but still need real persistence to assert against.
    """
    async with _test_session_factory() as session:
        yield session


@pytest_asyncio.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    """Provide an async test client with the test DB dependency override."""
    from app.main import app

    # Override the DB dependency for the app's lifetime.
    overrides_caches = app.dependency_overrides
    app.dependency_overrides[get_db] = _override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    # Restore original dependencies.
    app.dependency_overrides.clear()
    overrides_caches.clear()


@pytest_asyncio.fixture
def test_user() -> dict:
    """Provide a sample test user payload."""
    return {
        "email": "test@example.com",
        "username": "testuser",
        "password": "StrongPass123",
        "full_name": "Test User",
    }


@pytest_asyncio.fixture
def hashed_password() -> str:
    """Provide a pre-hashed password."""
    return hash_password("StrongPass123")


@pytest_asyncio.fixture
def sample_user() -> User:
    """Provide an in-memory User model sample."""
    return User(
        email="test@example.com",
        username="testuser",
        hashed_password=hash_password("StrongPass123"),
        full_name="Test User",
    )

