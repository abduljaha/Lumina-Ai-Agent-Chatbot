"""One-time backfill: extract personal facts from message history that
predates the extraction.py fixes, so existing users don't have to
re-introduce themselves for global memory to know about them.

Safe to run multiple times - upsert_entity/add_preference_if_new are
idempotent (they update in place / skip duplicates).
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select

from app.db.models import Message, MessageRole, Thread, User
from app.db.session import async_session_factory
from app.memory.extraction import extract_personal_info
from app.memory.manager import MemoryManager


async def backfill() -> None:
    async with async_session_factory() as session:
        manager = MemoryManager(session)
        facts_written = 0
        users_touched: set[str] = set()

        # Account-level facts (email/full name) - only auto-seeded for
        # accounts created *after* this feature landed, so existing accounts
        # need it backfilled here too.
        user_result = await session.execute(select(User.id, User.email, User.full_name))
        for user_id, email, full_name in user_result.all():
            if email:
                await manager.upsert_entity(user_id, "email", email)
                facts_written += 1
                users_touched.add(user_id)
            if full_name:
                await manager.upsert_entity(user_id, "name", full_name)
                facts_written += 1
                users_touched.add(user_id)

        result = await session.execute(
            select(Message.thread_id, Message.content)
            .join(Message.thread)
            .where(Message.role == MessageRole.USER)
            .order_by(Message.created_at.asc())
        )
        rows = result.all()

        # Need each message's owning user_id - fetch thread->user mapping once.
        thread_result = await session.execute(select(Thread.id, Thread.user_id))
        thread_to_user = {tid: uid for tid, uid in thread_result.all()}

        for thread_id, content in rows:
            user_id = thread_to_user.get(thread_id)
            if not user_id or not content:
                continue
            for fact in extract_personal_info(content):
                if fact.kind == "entity" and fact.key:
                    await manager.upsert_entity(user_id, fact.key, fact.value)
                    facts_written += 1
                    users_touched.add(user_id)
                elif fact.kind == "preference":
                    written = await manager.add_preference_if_new(user_id, fact.value)
                    if written:
                        facts_written += 1
                        users_touched.add(user_id)

        print(f"Backfill complete: {facts_written} facts written across {len(users_touched)} users.")


if __name__ == "__main__":
    asyncio.run(backfill())
