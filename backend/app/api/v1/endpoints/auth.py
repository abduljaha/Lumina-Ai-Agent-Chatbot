"""Authentication endpoints."""
from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from app.api.deps import CurrentUser, DbDep
from app.core.exceptions import AuthenticationError, ConflictError
from app.db.models import User
from app.schemas.auth import (
    ChangePasswordRequest,
    ForgotPasswordRequest,
    LoginRequest,
    LogoutRequest,
    MessageResponse,
    RefreshRequest,
    ResetPasswordRequest,
    TokenPair,
    UserCreate,
    UserRead,
)
from app.services.auth import AuthService
from app.services.user import UserService

logger = logging.getLogger("app")
router = APIRouter()


@router.post(
    "/register",
    response_model=UserRead,
    status_code=201,
    summary="Register a new user",
)
async def register(data: UserCreate, db: DbDep) -> User:
    """Create a new user account with local credentials."""
    service = AuthService(db)
    user = await service.register(data)
    await db.refresh(user)
    return user


@router.post("/login", response_model=TokenPair, summary="Login with email and password")
async def login(data: LoginRequest, db: DbDep) -> TokenPair:
    """Authenticate a user and return JWT tokens."""
    service = AuthService(db)
    user = await service.login(data)
    return await service.get_token_pair(user)


@router.post("/refresh", response_model=TokenPair, summary="Refresh access token")
async def refresh(data: RefreshRequest, db: DbDep) -> TokenPair:
    """Issue a new token pair from a valid refresh token."""
    service = AuthService(db)
    return await service.refresh(data)


@router.post("/logout", response_model=MessageResponse, summary="Logout")
async def logout(data: LogoutRequest, user: CurrentUser, db: DbDep) -> MessageResponse:
    """Log out the current user, revoking their refresh token if provided."""
    service = AuthService(db)
    await service.logout(data.refresh_token)
    return MessageResponse(message="Logged out successfully")


@router.get("/me", response_model=UserRead, summary="Get current user")
async def me(user: CurrentUser) -> User:
    """Return the currently authenticated user's profile."""
    return user


@router.post("/change-password", response_model=MessageResponse, summary="Change password")
async def change_password(
    data: ChangePasswordRequest,
    user: CurrentUser,
    db: DbDep,
) -> MessageResponse:
    """Change the current user's password."""
    from app.core.security import hash_password, verify_password

    if not user.hashed_password or not verify_password(data.current_password, user.hashed_password):
        raise AuthenticationError("Current password is incorrect")
    user.hashed_password = hash_password(data.new_password)
    await db.commit()
    return MessageResponse(message="Password changed successfully")


@router.post("/forgot-password", response_model=MessageResponse, summary="Request password reset")
async def forgot_password(data: ForgotPasswordRequest, db: DbDep) -> MessageResponse:
    """Issue a password reset token for the user's email, if the account exists."""
    from app.core.security import create_password_reset_token
    from app.repositories import UserRepository

    repo = UserRepository(db)
    user = await repo.get_by_email(data.email)
    if user and user.hashed_password:
        token = create_password_reset_token(user.id, user.hashed_password)
        # No email provider is wired up in this app yet, so there is no way
        # to actually deliver `token` to the user - logging it server-side
        # is the best available fallback so the flow is at least testable.
        # A real deployment MUST send `token` via email (or SMS, etc.)
        # instead of relying on this log line.
        logger.info("Password reset requested for user %s - reset token: %s", user.id, token)
    # Always return success to avoid user enumeration
    return MessageResponse(message="If the account exists, a reset link has been sent")


@router.post("/reset-password", response_model=MessageResponse, summary="Reset password")
async def reset_password(data: ResetPasswordRequest, db: DbDep) -> MessageResponse:
    """Reset a user's password using a signed, short-lived reset token.

    `data.token` is a JWT minted by `forgot_password` (see
    `create_password_reset_token`), not a raw user id - the previous version
    of this endpoint accepted any valid user UUID as the "token" and reset
    that account's password with zero verification.
    """
    from jose import JWTError

    from app.core.security import (
        decode_password_reset_token,
        hash_password,
        password_reset_token_matches,
    )
    from app.repositories import UserRepository

    try:
        payload = decode_password_reset_token(data.token)
    except (JWTError, ValueError) as exc:
        raise AuthenticationError("Invalid or expired reset token") from exc

    user = await UserRepository(db).get(payload.get("sub"))
    if not user or not user.hashed_password or not password_reset_token_matches(payload, user.hashed_password):
        raise AuthenticationError("Invalid or expired reset token")

    user.hashed_password = hash_password(data.new_password)
    await db.commit()
    return MessageResponse(message="Password reset successfully")
