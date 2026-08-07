"""Security utilities - password hashing, JWT tokens, OAuth integration.

Implements:
- Password hashing (bcrypt)
- JWT access & refresh token creation/verification
- OAuth callback state generation
"""
from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import get_settings

settings = get_settings()

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def _load_or_create_jwt_secret() -> str:
    """Load the JWT secret from a persistent file, creating it if needed.

    This keeps tokens valid across app restarts in development, avoiding
    the refresh-token loop caused by a random secret per restart.
    """
    import os

    secret_file = Path(settings.jwt_secret_file)
    try:
        secret_file.parent.mkdir(parents=True, exist_ok=True)
        if secret_file.exists():
            value = secret_file.read_text().strip()
            if value:
                return value
        value = settings.jwt_secret_key or secrets.token_urlsafe(64)
        secret_file.write_text(value)
        return value
    except OSError:
        # Fall back to the configured/random secret if file I/O fails.
        return settings.jwt_secret_key or secrets.token_urlsafe(64)


from pathlib import Path  # noqa: E402

# Resolve the effective JWT signing secret once at import time.
JWT_SECRET = _load_or_create_jwt_secret()


# ---------------------------------------------------------------------------
# Password hashing
# ---------------------------------------------------------------------------
def hash_password(password: str) -> str:
    """Hash a plaintext password using bcrypt."""
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plaintext password against a bcrypt hash."""
    return pwd_context.verify(plain_password, hashed_password)


# ---------------------------------------------------------------------------
# JWT tokens
# ---------------------------------------------------------------------------
TokenType = Literal["access", "refresh", "password_reset"]


def create_token(
    subject: str | int,
    token_type: TokenType = "access",
    expires_delta: timedelta | None = None,
    extra_claims: dict[str, Any] | None = None,
) -> str:
    """Create a JWT token (access, refresh, or password_reset)."""
    if token_type == "access":
        lifetime = expires_delta or timedelta(minutes=settings.access_token_expire_minutes)
    elif token_type == "refresh":
        lifetime = expires_delta or timedelta(days=settings.refresh_token_expire_days)
    else:
        lifetime = expires_delta or timedelta(minutes=30)

    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "sub": str(subject),
        "iat": now,
        "exp": now + lifetime,
        "type": token_type,
        "jti": secrets.token_hex(16),
    }
    if extra_claims:
        payload.update(extra_claims)

    # Signed with JWT_SECRET (the file-persisted secret, see
    # _load_or_create_jwt_secret above), not settings.jwt_secret_key
    # directly - the latter defaults to a fresh random value every process
    # start unless explicitly set in .env, which silently invalidated every
    # outstanding token on each restart/deploy.
    return jwt.encode(payload, JWT_SECRET, algorithm=settings.jwt_algorithm)


def create_access_token(subject: str | int, extra_claims: dict[str, Any] | None = None) -> str:
    """Create a short-lived JWT access token."""
    return create_token(subject, "access", extra_claims=extra_claims)


def create_refresh_token(subject: str | int, extra_claims: dict[str, Any] | None = None) -> str:
    """Create a long-lived JWT refresh token."""
    return create_token(subject, "refresh", extra_claims=extra_claims)


def decode_token(token: str) -> dict[str, Any]:
    """Decode and validate a JWT token. Raises JWTError on failure."""
    return jwt.decode(token, JWT_SECRET, algorithms=[settings.jwt_algorithm])


def verify_token(token: str, expected_type: TokenType | None = None) -> dict[str, Any]:
    """Verify a token and optionally enforce its type.

    Raises:
        JWTError: If the token is invalid or expired.
        ValueError: If the token type does not match.
    """
    payload = decode_token(token)
    if expected_type and payload.get("type") != expected_type:
        raise ValueError(f"Expected {expected_type} token, got {payload.get('type')}")
    return payload


def generate_oauth_state() -> str:
    """Generate a random state parameter for OAuth flows."""
    return secrets.token_urlsafe(32)


# ---------------------------------------------------------------------------
# Password reset tokens
#
# A signed, short-lived JWT rather than a raw user id (the previous
# "reset_password" endpoint literally looked a user up by the "token" field
# as if it were their id - anyone who knew/guessed a user's UUID could reset
# that account's password with no verification at all). Bound to a
# fingerprint of the user's *current* password hash rather than a separate
# DB-backed single-use-token table: using the token to reset the password
# changes the hash, which changes the fingerprint, which naturally
# invalidates the token (and any other outstanding one for the same
# account) without new schema.
# ---------------------------------------------------------------------------
def _password_reset_fingerprint(password_hash: str) -> str:
    return hashlib.sha256(password_hash.encode()).hexdigest()[:16]


def create_password_reset_token(user_id: str, password_hash: str) -> str:
    """Create a short-lived password reset token for a user."""
    return create_token(
        user_id,
        "password_reset",
        expires_delta=timedelta(minutes=30),
        extra_claims={"pwd_fp": _password_reset_fingerprint(password_hash)},
    )


def decode_password_reset_token(token: str) -> dict[str, Any]:
    """Decode+validate a password reset token's signature, expiry, and type.

    Does NOT check the password-hash fingerprint - callers must separately
    call `password_reset_token_matches` once they've looked up the user the
    token claims to be for (the fingerprint can't be checked here since
    doing so requires knowing the user's current hash first).
    """
    return verify_token(token, expected_type="password_reset")


def password_reset_token_matches(payload: dict[str, Any], current_password_hash: str) -> bool:
    """Whether a decoded reset token is still valid for the user's current password."""
    return payload.get("pwd_fp") == _password_reset_fingerprint(current_password_hash)


# ---------------------------------------------------------------------------
# API key generation
# ---------------------------------------------------------------------------
def generate_api_key() -> str:
    """Generate a secure API key for programmatic access."""
    return f"sk-{secrets.token_urlsafe(48)}"


# ---------------------------------------------------------------------------
# Encryption helper (for sensitive field encryption at rest)
# ---------------------------------------------------------------------------
from cryptography.fernet import Fernet  # noqa: E402


def _fernet() -> Fernet:
    """Build a Fernet cipher from the secret key (SHA256-derived)."""
    import base64
    import hashlib

    digest = hashlib.sha256(settings.secret_key.encode()).digest()
    key = base64.urlsafe_b64encode(digest)
    return Fernet(key)


def encrypt_value(value: str) -> str:
    """Encrypt a sensitive string value at rest."""
    return _fernet().encrypt(value.encode()).decode()


def decrypt_value(token: str) -> str:
    """Decrypt a value previously encrypted with `encrypt_value`."""
    return _fernet().decrypt(token.encode()).decode()

