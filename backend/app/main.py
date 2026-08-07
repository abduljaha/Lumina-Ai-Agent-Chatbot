"""FastAPI application factory and entry point.

Configures the application with middleware, routers, exception handlers,
and lifespan hooks.
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.v1.router import api_router
from app.core.config import get_settings
from app.core.di import container
from app.core.exceptions import register_exception_handlers
from app.core.logging import RequestLoggingMiddleware, setup_logging
from app.core.middleware import setup_middleware
from app.db.session import init_db

settings = get_settings()
logger = logging.getLogger("app")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Application lifespan - startup and shutdown hooks."""
    logger.info("Starting %s v%s ...", settings.app_name, settings.app_version)
    await container.startup()
    try:
        await init_db()
        logger.info("Database tables verified.")
    except Exception as exc:
        logger.warning("Database init skipped: %s", exc)

    # RAG retrieval now runs on every chat message (not just explicit
    # document searches), so the embedding backend's first-use cold start -
    # trying OpenAI, failing, then loading a local sentence-transformers
    # model - would otherwise land on whichever user happens to send the
    # first message after a restart, adding ~10+ seconds to their turn.
    # Paying that cost once here at boot instead is what actually makes it
    # invisible to users.
    try:
        from app.core.container import app_container

        await app_container.get_embedder().initialize()
        logger.info("Embedding backend warmed up.")
    except Exception as exc:  # noqa: BLE001
        logger.warning("Embedder warm-up skipped: %s", exc)

    yield
    await container.shutdown()
    logger.info("Shutdown complete.")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    setup_logging()

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description=(
            "Enterprise-grade Lumina AI API built with FastAPI, LangGraph, "
            "and Clean Architecture. Supports multiple LLM providers, RAG, "
            "memory, streaming, and FastMCP."
        ),
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        lifespan=lifespan,
        debug=settings.debug,
    )

    # Register exception handlers
    register_exception_handlers(app)

    # Apply middleware
    app.add_middleware(GZipMiddleware, minimum_size=1000)
    app.add_middleware(RequestLoggingMiddleware)
    setup_middleware(app, container.limiter)

    # Include versioned API router
    app.include_router(api_router, prefix=settings.api_v1_prefix)

    # Health check
    @app.get("/health", tags=["system"], summary="Health check")
    async def health_check() -> dict:
        """Return service health status."""
        return {
            "status": "ok",
            "app": settings.app_name,
            "version": settings.app_version,
            "env": settings.app_env,
        }

    # Root endpoint
    @app.get("/", tags=["system"], summary="Root")
    async def root() -> dict:
        """Return API metadata."""
        return {
            "name": settings.app_name,
            "version": settings.app_version,
            "docs": "/docs",
            "api": settings.api_v1_prefix,
        }

    # Mount static uploads (if directory exists)
    if settings.upload_path.exists():
        app.mount("/uploads", StaticFiles(directory=str(settings.upload_path)), name="uploads")

    return app


app = create_app()
