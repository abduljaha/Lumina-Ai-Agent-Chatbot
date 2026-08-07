"""FastAPI dependencies - authentication and authorization."""
from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request
from jose import JWTError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AuthenticationError, AuthorizationError
from app.core.security import verify_token
from app.db.models import User, UserRole
from app.db.session import get_db
from app.repositories import UserRepository

DbDep = Annotated[AsyncSession, Depends(get_db)]


async def get_current_user(
    request: Request,
    db: DbDep,
) -> User:
    """Resolve the current authenticated user from the JWT token."""
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise AuthenticationError("Missing or invalid Authorization header")

    token = auth_header.removeprefix("Bearer ").strip()
    try:
        payload = verify_token(token, expected_type="access")
    except (JWTError, ValueError) as exc:
        raise AuthenticationError("Invalid or expired token") from exc

    user_id = payload.get("sub")
    if not user_id:
        raise AuthenticationError("Invalid token payload")

    user_repo = UserRepository(db)
    user = await user_repo.get(user_id)
    if not user:
        raise AuthenticationError("User not found")
    if not user.is_active:
        raise AuthenticationError("User account is disabled")

    request.state.user_id = user_id
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_role(*roles: UserRole):
    """Dependency factory that enforces user role permissions."""

    async def _role_checker(user: CurrentUser) -> User:
        if user.role not in roles:
            raise AuthorizationError("Insufficient permissions for this action")
        return user

    return _role_checker


AdminUser = Annotated[User, Depends(require_role(UserRole.ADMIN))]
