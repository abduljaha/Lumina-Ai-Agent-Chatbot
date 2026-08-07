"""Pydantic schemas for authentication."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.db.models import AuthProvider, UserRole


class UserBase(BaseModel):
    """Base user schema."""

    email: EmailStr
    username: str = Field(min_length=3, max_length=100)
    full_name: str | None = Field(default=None, max_length=255)


class UserCreate(UserBase):
    """User registration schema."""

    password: str = Field(min_length=6, max_length=128)


class UserRead(UserBase):
    """User response schema."""

    id: str
    role: UserRole
    provider: AuthProvider
    is_active: bool
    is_verified: bool
    avatar_url: str | None = None
    last_login_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class UserUpdate(BaseModel):
    """User profile update schema."""

    full_name: str | None = Field(default=None, max_length=255)
    avatar_url: str | None = Field(default=None, max_length=500)
    preferences: dict | None = None


class LoginRequest(BaseModel):
    """Login request schema."""

    email: EmailStr
    password: str


class TokenPair(BaseModel):
    """JWT access & refresh token pair."""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class RefreshRequest(BaseModel):
    """Refresh token request schema."""

    refresh_token: str


class LogoutRequest(BaseModel):
    """Logout request schema."""

    refresh_token: str | None = None


class ForgotPasswordRequest(BaseModel):
    """Forgot password request schema."""

    email: EmailStr


class ResetPasswordRequest(BaseModel):
    """Reset password request schema."""

    token: str
    new_password: str = Field(min_length=6, max_length=128)


class ChangePasswordRequest(BaseModel):
    """Change password request schema."""

    current_password: str
    new_password: str = Field(min_length=6, max_length=128)


class OAuthCallbackResponse(BaseModel):
    """OAuth flow response."""

    token_pair: TokenPair
    user: UserRead
    is_new_user: bool


class MessageResponse(BaseModel):
    """Generic message response."""

    message: str
    success: bool = True
