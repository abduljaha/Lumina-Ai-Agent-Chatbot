"""User service - profile management and settings."""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.db.models import User, UserSetting
from app.repositories import SettingRepository, UserRepository
from app.schemas.auth import UserUpdate
from app.schemas.models import SettingsUpdate


class UserService:
    """Business logic for user profile and settings management."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db
        self._user_repo = UserRepository(db)
        self._setting_repo = SettingRepository(db)

    async def get_profile(self, user_id: str) -> User:
        """Get a user profile by id."""
        user = await self._user_repo.get(user_id)
        if not user:
            raise NotFoundError("User not found")
        return user

    async def update_profile(self, user_id: str, data: UserUpdate) -> User:
        """Update a user's profile information."""
        user = await self.get_profile(user_id)
        if data.full_name is not None:
            user.full_name = data.full_name
        if data.avatar_url is not None:
            user.avatar_url = data.avatar_url
        if data.preferences is not None:
            user.preferences = {**user.preferences, **data.preferences}
        await self._user_repo.update(user)
        await self._user_repo.commit()
        return user

    async def get_settings(self, user_id: str) -> dict:
        """Get all settings for a user as a merged dict."""
        settings = await self._setting_repo.list_for_user(user_id)
        result: dict = {"theme": "dark", "streaming_enabled": True, "system_prompt": ""}
        for setting in settings:
            result[setting.key] = setting.value
        return result

    async def update_settings(self, user_id: str, data: SettingsUpdate) -> dict:
        """Update user settings, merging with existing values."""
        updates = data.model_dump(exclude_none=True)
        for key, value in updates.items():
            existing = None
            for setting in await self._setting_repo.list_for_user(user_id):
                if setting.key == key:
                    existing = setting
                    break
            if existing:
                existing.value = value
                await self._setting_repo.update(existing)
            else:
                setting = UserSetting(user_id=user_id, key=key, value=value)
                await self._setting_repo.create(setting)
        await self._setting_repo.commit()
        return await self.get_settings(user_id)
