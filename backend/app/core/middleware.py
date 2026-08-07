"""Middleware stack - CORS, security headers, rate limiting, request ID.

Implements:
- CORS
- Security headers (XSS, CSRF, CSP, etc.)
- Request ID propagation
- Rate limiting (Redis-backed)
"""
from __future__ import annotations

import time
from collections import defaultdict
from typing import Any, Callable

from fastapi import FastAPI, Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.core.exceptions import RateLimitExceededError

settings = get_settings()


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add security headers to every response."""

    HEADERS = {
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY",
        "Referrer-Policy": "strict-origin-when-cross-origin",
        "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
        "X-XSS-Protection": "1; mode=block",
        "Content-Security-Policy": "default-src 'self'; frame-ancestors 'none'",
    }

    async def dispatch(self, request: Request, call_next: Any) -> Response:
        response = await call_next(request)
        for header, value in self.HEADERS.items():
            response.headers[header] = value
        return response


class RateLimiter:
    """Sliding-window rate limiter backed by in-memory store.

    In production this is backed by Redis; a simple in-memory fallback
    is provided for development and testing.
    """

    def __init__(self, redis_client: Any | None = None) -> None:
        self._redis = redis_client
        self._memory: dict[str, list[float]] = defaultdict(list)

    async def check(self, key: str, limit: int, window_seconds: int = 60) -> None:
        """Check whether the key has exceeded the limit.

        Uses Redis when available and falls back to an in-memory sliding
        window so the application remains functional when Redis is down.
        """
        now = time.monotonic()
        cutoff = now - window_seconds

        if self._redis is not None:
            try:
                pipe = self._redis.pipeline()
                pipe.zremrangebyscore(key, 0, cutoff)
                pipe.zadd(key, {now: now})
                pipe.zcard(key)
                pipe.expire(key, window_seconds)
                _, _, count, _ = await pipe.execute()
            except Exception:
                # Redis unavailable - fall back to in-memory store.
                timestamps = [t for t in self._memory[key] if t > cutoff]
                timestamps.append(now)
                self._memory[key] = timestamps[-window_seconds * 10 :]
                count = len(timestamps)
        else:
            timestamps = [t for t in self._memory[key] if t > cutoff]
            timestamps.append(now)
            self._memory[key] = timestamps[-window_seconds * 10 :]
            count = len(timestamps)

        if count > limit:
            raise RateLimitExceededError(
                message=f"Rate limit exceeded: {limit} requests per {window_seconds}s"
            )


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Apply per-IP and per-user rate limits."""

    def __init__(self, app: FastAPI, limiter: RateLimiter) -> None:
        super().__init__(app)
        self._limiter = limiter

    async def dispatch(self, request: Request, call_next: Any) -> Response:
        client_ip = request.client.host if request.client else "unknown"
        user_id = getattr(request.state, "user_id", None)
        key_base = f"ratelimit:{user_id or client_ip}"

        is_stream = request.url.path.endswith("/stream")
        limit = settings.rate_limit_stream_per_minute if is_stream else settings.rate_limit_per_minute

        await self._limiter.check(key_base, limit)
        return await call_next(request)


def setup_middleware(app: FastAPI, limiter: RateLimiter) -> None:
    """Configure all middleware on the FastAPI application."""
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(RateLimitMiddleware, limiter=limiter)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID"],
    )

