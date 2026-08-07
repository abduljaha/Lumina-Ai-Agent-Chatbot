"""User management endpoints."""
from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import CurrentUser, DbDep
from app.db.models import User
from app.schemas.auth import UserRead, UserUpdate
from app.schemas.models import SettingsUpdate
from app.services.user import UserService

router = APIRouter()


@router.get("/me", response_model=UserRead, summary="Get current user profile")
async def get_me(user: CurrentUser) -> User:
    """Return the current user's profile."""
    return user


@router.patch("/me", response_model=UserRead, summary="Update current user profile")
async def update_me(
    data: UserUpdate,
    user: CurrentUser,
    db: DbDep,
) -> User:
    """Update the current user's profile."""
    service = UserService(db)
    return await service.update_profile(user.id, data)


@router.get("/me/settings", response_model=dict, summary="Get user settings")
async def get_settings(user: CurrentUser, db: DbDep) -> dict:
    """Return the current user's settings."""
    service = UserService(db)
    return await service.get_settings(user.id)


@router.patch("/me/settings", response_model=dict, summary="Update user settings")
async def update_settings(
    data: SettingsUpdate,
    user: CurrentUser,
    db: DbDep,
) -> dict:
    """Update the current user's settings."""
    service = UserService(db)
    return await service.update_settings(user.id, data)
