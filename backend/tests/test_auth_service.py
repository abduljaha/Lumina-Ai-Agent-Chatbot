" ""Tests for the authentication service."""
from __future__ import annotations

import pytest

from app.core.exceptions import AuthenticationError, ConflictError
from app.services.auth import AuthService


@pytest.mark.asyncio
async def test_register_user(test_user, client) -> None:
    """Test registering a new user."""
    response = await client.post("/api/v1/auth/register", json=test_user)
    assert response.status_code == 201
    data = response.json()
    assert data["email"] == test_user["email"]
    assert data["username"] == test_user["username"]


@pytest.mark.asyncio
async def test_register_duplicate_email(test_user, client) -> None:
    """Test registering with a duplicate email raises ConflictError."""
    await client.post("/api/v1/auth/register", json=test_user)
    response = await client.post("/api/v1/auth/register", json=test_user)
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_login_success(test_user, client) -> None:
    """Test successful login returns a token pair."""
    await client.post("/api/v1/auth/register", json=test_user)
    response = await client.post(
        "/api/v1/auth/login",
        json={"email": test_user["email"], "password": test_user["password"]},
    )
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert "refresh_token" in data


@pytest.mark.asyncio
async def test_login_wrong_password(test_user, client) -> None:
    """Test login with wrong password fails."""
    await client.post("/api/v1/auth/register", json=test_user)
    response = await client.post(
        "/api/v1/auth/login",
        json={"email": test_user["email"], "password": "WrongPass123"},
    )
    assert response.status_code == 401
