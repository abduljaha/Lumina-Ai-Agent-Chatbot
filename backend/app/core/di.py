"""Dependency Injection container.

Provides a centralized container for services, repositories, and
infrastructure components. Uses manual DI to keep the framework
dependencies minimal and testable.
"""
from __future__ import annotations

from typing import Any

from app.core.config import get_settings
from app.core.logging import setup_logging
from app.core.middleware import RateLimiter

settings = get_settings()


class Container:
    """Application service container for dependency injection.

    Services are registered lazily and resolved on first access.
    """

    def __init__(self) -> None:
        self._services: dict[str, Any] = {}
        self._redis = None
        self._limiter = None

    # ------------------------------------------------------------------
    # Infrastructure
    # ------------------------------------------------------------------
    @property
    def limiter(self) -> RateLimiter:
        """Return the rate limiter instance."""
        if self._limiter is None:
            self._limiter = RateLimiter(redis_client=self.redis)
        return self._limiter

    @property
    def redis(self) -> Any:
        """Return a Redis client (lazy)."""
        if self._redis is None:
            try:
                import redis.asyncio as aioredis
            except ImportError:
                return None

            self._redis = aioredis.from_url(
                settings.redis_url,
                encoding="utf-8",
                decode_responses=True,
            )
        return self._redis

    # ------------------------------------------------------------------
    # Service registration
    # ------------------------------------------------------------------
    def register(self, name: str, factory: Any) -> None:
        """Register a service factory by name."""
        self._services[name] = factory

    def get(self, name: str) -> Any:
        """Resolve a service by name. Raises KeyError if not registered."""
        if name not in self._services:
            raise KeyError(f"Service '{name}' is not registered")
        return self._services[name]

    def get_instance(self, name: str, *args: Any, **kwargs: Any) -> Any:
        """Resolve a service, calling its factory if it's callable."""
        service = self._services[name]
        if callable(service) and not isinstance(service, (str, int, float, bool, type)):
            return service(*args, **kwargs)
        return service

    def has(self, name: str) -> bool:
        """Check whether a service is registered."""
        return name in self._services

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    async def startup(self) -> None:
        """Initialize infrastructure on app startup.

        Redis is optional: if the connection fails, the application degrades
        gracefully to in-memory stores (rate limiting, caching) so the service
        can still start without external dependencies.
        """
        import logging

        logger = logging.getLogger("app")
        setup_logging()

        # Establish Redis connection (best-effort)
        if self._redis is not None:
            try:
                await self._redis.ping()
                logger.info("Redis connection established: %s", settings.redis_url)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Redis unavailable (%s). Running without Redis.", exc)
                # Do not raise - degrade gracefully to in-memory mode.

    async def shutdown(self) -> None:
        """Clean up resources on app shutdown."""
        if self._redis is not None:
            try:
                await self._redis.aclose()
            except Exception:  # noqa: BLE001
                pass


# Global container instance
container = Container()


def get_container() -> Container:
    """FastAPI dependency returning the global container."""
    return container
