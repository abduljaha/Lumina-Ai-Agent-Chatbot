"""Model listing endpoints."""
from __future__ import annotations

from fastapi import APIRouter

from app.core.container import app_container
from app.core.config import get_settings
from app.schemas.models import ModelList

settings = get_settings()
router = APIRouter()


@router.get("", response_model=ModelList, summary="List available models")
async def list_models() -> ModelList:
    """Return all available models across providers."""
    router = app_container.model_router
    models = router.list_models()
    return ModelList(
        default=settings.openai_model,
        fallback_chain=settings.fallback_models,
        models=models,
    )


@router.get("/providers", summary="List available providers")
async def list_providers() -> dict:
    """Return available LLM providers."""
    router = app_container.model_router
    return {
        "providers": router.available_providers,
        "default_provider": router.available_providers[0] if router.available_providers else None,
    }
