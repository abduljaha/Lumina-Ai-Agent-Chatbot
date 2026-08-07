"""Seed script to populate default data.

Usage:
    cd backend && python -m scripts.seed
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# Allow running from project root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.core.security import hash_password  # noqa: E402
from app.db.models import User, UserRole  # noqa: E402
from app.db.session import async_session_factory, init_db  # noqa: E402


async def seed() -> None:
    """Create default admin user and sample data."""
    await init_db()
    async with async_session_factory() as session:
        from sqlalchemy import select

        admin = await session.execute(select(User).where(User.email == "admin@example.com"))
        if not admin.scalar_one_or_none():
            admin_user = User(
                email="admin@example.com",
                username="admin",
                full_name="System Admin",
                hashed_password=hash_password("AdminPass123"),
                role=UserRole.ADMIN,
                is_verified=True,
            )
            session.add(admin_user)
            await session.commit()
            print("Created admin user: admin@example.com / AdminPass123")
        else:
            print("Admin user already exists")


if __name__ == "__main__":
    asyncio.run(seed())
