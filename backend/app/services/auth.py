"""Authentication service - registration, login, token management."""
from __future__ import annotations

from datetime import datetime, timezone

from jose import JWTError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    AuthenticationError,
    ConflictError,
    NotFoundError,
)
from app.core.security import (
    create_access_token,
    create_refresh_token,
    hash_password,
    verify_password,
    verify_token,
)
from app.db.models import AuthProvider, RevokedToken, User
from app.memory.manager import MemoryManager
from app.repositories import UserRepository
from app.schemas.auth import (
    LoginRequest,
    RefreshRequest,
    TokenPair,
    UserCreate,
    UserRead,
)


class AuthService:
    """Business logic for authentication and authorization."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db
        self._user_repo = UserRepository(db)

    async def register(self, data: UserCreate) -> User:
        """Register a new user with local credentials."""
        if await self._user_repo.get_by_email(data.email):
            raise ConflictError("An account with this email already exists")
        if await self._user_repo.get_by_username(data.username):
            raise ConflictError("This username is already taken")

        user = User(
            email=data.email.lower(),
            username=data.username,
            full_name=data.full_name,
            hashed_password=hash_password(data.password),
            provider=AuthProvider.LOCAL,
        )
        await self._user_repo.create(user)
        try:
            await self._user_repo.commit()
        except IntegrityError as exc:
            # The existence checks above are not atomic with this insert, so a
            # concurrent registration for the same email/username (e.g. a
            # double-clicked submit button) can still race past them.
            await self._db.rollback()
            raise ConflictError("An account with this email or username already exists") from exc
        await self._seed_profile_memory(user)
        return user

    async def login(self, data: LoginRequest) -> User:
        """Authenticate a user with email and password."""
        user = await self._user_repo.get_by_email(data.email)
        if not user or not user.hashed_password:
            raise AuthenticationError("Invalid email or password")
        if not verify_password(data.password, user.hashed_password):
            raise AuthenticationError("Invalid email or password")
        if not user.is_active:
            raise AuthenticationError("Account is disabled")

        user.last_login_at = datetime.now(timezone.utc)
        await self._user_repo.update(user)
        await self._user_repo.commit()
        return user

    async def refresh(self, data: RefreshRequest) -> TokenPair:
        """Generate a new token pair from a valid refresh token."""
        try:
            payload = verify_token(data.refresh_token, expected_type="refresh")
        except (JWTError, ValueError) as exc:
            raise AuthenticationError("Invalid or expired refresh token") from exc

        user_id = payload.get("sub")
        user = await self._user_repo.get(user_id) if user_id else None
        if not user or not user.is_active:
            raise AuthenticationError("User not found or disabled")

        return self._issue_tokens(user)

    async def logout(self, refresh_token: str | None) -> None:
        """Revoke a refresh token so it can no longer mint new token pairs."""
        if not refresh_token:
            return
        try:
            payload = verify_token(refresh_token, expected_type="refresh")
        except (JWTError, ValueError):
            return
        jti = payload.get("jti")
        exp = payload.get("exp")
        if not jti or not exp:
            return
        self._db.add(RevokedToken(jti=jti, expires_at=datetime.fromtimestamp(exp, tz=timezone.utc)))
        try:
            await self._db.commit()
        except IntegrityError:
            # Already revoked (e.g. duplicate logout call) - nothing to do.
            await self._db.rollback()

    async def oauth_login_or_register(
        self,
        provider: AuthProvider,
        provider_id: str,
        email: str,
        username: str,
        full_name: str | None = None,
        avatar_url: str | None = None,
    ) -> tuple[User, bool]:
        """Log in an OAuth user, creating them if necessary."""
        user = await self._user_repo.get_by_provider(provider.value, provider_id)
        is_new = False
        if not user:
            user = User(
                email=email.lower() if email else f"{provider_id}@{provider.value}.oauth",
                username=username or f"{provider.value}_{provider_id[:8]}",
                full_name=full_name,
                avatar_url=avatar_url,
                provider=provider,
                provider_id=provider_id,
                is_verified=True,
            )
            await self._user_repo.create(user)
            is_new = True
        await self._user_repo.commit()
        if is_new:
            await self._seed_profile_memory(user)
        return user, is_new

    async def _seed_profile_memory(self, user: User) -> None:
        """Write the account's own email/name as global entity memory.

        Without this, "what's my email" only works if the user happens to
        retype it in chat - the account already knows it, so every thread
        should be able to answer from it immediately, same as any other
        profile fact.
        """
        memory = MemoryManager(self._db)
        await memory.upsert_entity(user.id, "email", user.email)
        if user.full_name:
            await memory.upsert_entity(user.id, "name", user.full_name)

    @staticmethod
    def _issue_tokens(user: User) -> TokenPair:
        """Issue an access and refresh token pair."""
        access = create_access_token(
            user.id,
            extra_claims={"role": user.role.value, "username": user.username},
        )
        refresh = create_refresh_token(user.id)
        return TokenPair(
            access_token=access,
            refresh_token=refresh,
            expires_in=30 * 60,
        )

    async def get_token_pair(self, user: User) -> TokenPair:
        """Return a token pair for an authenticated user."""
        return self._issue_tokens(user)
