"""API v1 router aggregator.

Includes all versioned sub-routers with version metadata.
"""
from __future__ import annotations

from fastapi import APIRouter

from app.api.v1.endpoints import (
    auth,
    chat,
    files,
    memories,
    models,
    threads,
    tools,
    users,
)

api_router = APIRouter()

api_router.include_router(auth.router, prefix="/auth", tags=["Authentication"])
api_router.include_router(users.router, prefix="/users", tags=["Users"])
api_router.include_router(threads.router, prefix="/threads", tags=["Threads"])
api_router.include_router(chat.router, prefix="/chat", tags=["Chat"])
api_router.include_router(models.router, prefix="/models", tags=["Models"])
api_router.include_router(memories.router, prefix="/memories", tags=["Memory"])
api_router.include_router(files.router, prefix="/files", tags=["Files"])
api_router.include_router(tools.router, prefix="/tools", tags=["Tools"])
