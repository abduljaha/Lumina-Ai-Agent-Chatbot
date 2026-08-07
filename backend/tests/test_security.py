"""Tests for security utilities (password hashing, JWT tokens)."""
from __future__ import annotations

import pytest
from jose import JWTError

from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
    verify_token,
)


@pytest.fixture
def user_id() -> str:
    """Provide a test user id."""
    return "test-user-id-123"


def test_hash_password() -> None:
    """Test that passwords are hashed and verified correctly."""
    hashed = hash_password("StrongPass123")
    assert hashed != "StrongPass123"
    assert verify_password("StrongPass123", hashed)
    assert not verify_password("WrongPass", hashed)


def test_create_and_decode_access_token(user_id: str) -> None:
    """Test access token creation and decoding."""
    token = create_access_token(user_id)
    payload = decode_token(token)
    assert payload["sub"] == user_id
    assert payload["type"] == "access"


def test_create_and_decode_refresh_token(user_id: str) -> None:
    """Test refresh token creation and decoding."""
    token = create_refresh_token(user_id)
    payload = decode_token(token)
    assert payload["sub"] == user_id
    assert payload["type"] == "refresh"


def test_verify_token_type(user_id: str) -> None:
    """Test that verify_token enforces token type."""
    access = create_access_token(user_id)
    refresh = create_refresh_token(user_id)

    # Correct type passes
    verify_token(access, expected_type="access")
    verify_token(refresh, expected_type="refresh")

    # Wrong type raises ValueError
    with pytest.raises(ValueError):
        verify_token(access, expected_type="refresh")


def test_invalid_token_raises() -> None:
    """Test that an invalid token raises JWTError."""
    with pytest.raises(JWTError):
        decode_token("invalid.token.here")
