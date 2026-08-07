"""Centralized exception hierarchy and global handlers.

All application-specific errors derive from `AppException` and are mapped
to appropriate HTTP responses by the global exception handler.
"""
from __future__ import annotations

from typing import Any

from fastapi import Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


class AppException(Exception):
    """Base application exception with an HTTP status code and error code."""

    def __init__(
        self,
        message: str,
        status_code: int = status.HTTP_400_BAD_REQUEST,
        error_code: str = "app_error",
        details: dict[str, Any] | None = None,
    ) -> None:
        self.message = message
        self.status_code = status_code
        self.error_code = error_code
        self.details = details or {}
        super().__init__(message)


class AuthenticationError(AppException):
    """Raised when authentication fails."""

    def __init__(self, message: str = "Authentication failed", details: dict[str, Any] | None = None) -> None:
        super().__init__(message, status.HTTP_401_UNAUTHORIZED, "authentication_error", details)


class AuthorizationError(AppException):
    """Raised when the user lacks permission for an action."""

    def __init__(self, message: str = "Insufficient permissions", details: dict[str, Any] | None = None) -> None:
        super().__init__(message, status.HTTP_403_FORBIDDEN, "authorization_error", details)


class NotFoundError(AppException):
    """Raised when a requested resource does not exist."""

    def __init__(self, message: str = "Resource not found", details: dict[str, Any] | None = None) -> None:
        super().__init__(message, status.HTTP_404_NOT_FOUND, "not_found", details)


class ConflictError(AppException):
    """Raised when a resource conflicts with an existing one."""

    def __init__(self, message: str = "Resource conflict", details: dict[str, Any] | None = None) -> None:
        super().__init__(message, status.HTTP_409_CONFLICT, "conflict", details)


class ValidationError(AppException):
    """Raised when input validation fails at the domain level."""

    def __init__(self, message: str = "Validation failed", details: dict[str, Any] | None = None) -> None:
        super().__init__(message, status.HTTP_422_UNPROCESSABLE_ENTITY, "validation_error", details)


class RateLimitExceededError(AppException):
    """Raised when a rate limit is exceeded."""

    def __init__(self, message: str = "Rate limit exceeded", details: dict[str, Any] | None = None) -> None:
        super().__init__(message, status.HTTP_429_TOO_MANY_REQUESTS, "rate_limit_exceeded", details)


class ProviderError(AppException):
    """Raised when an LLM provider fails."""

    def __init__(self, message: str = "LLM provider error", details: dict[str, Any] | None = None) -> None:
        super().__init__(message, status.HTTP_502_BAD_GATEWAY, "provider_error", details)


class ServiceUnavailableError(AppException):
    """Raised when a downstream service is unavailable."""

    def __init__(self, message: str = "Service unavailable", details: dict[str, Any] | None = None) -> None:
        super().__init__(message, status.HTTP_503_SERVICE_UNAVAILABLE, "service_unavailable", details)


# ---------------------------------------------------------------------------
# Global exception handler
# ---------------------------------------------------------------------------
def register_exception_handlers(app: Any) -> None:
    """Attach global exception handlers to the FastAPI application."""

    @app.exception_handler(AppException)
    async def app_exception_handler(request: Request, exc: AppException) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "success": False,
                "error": {
                    "code": exc.error_code,
                    "message": exc.message,
                    "details": exc.details,
                },
            },
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={
                "success": False,
                "error": {
                    "code": "validation_error",
                    "message": "Request validation failed",
                    "details": {"errors": exc.errors()},
                },
            },
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(
        request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "success": False,
                "error": {
                    "code": "http_error",
                    "message": str(exc.detail),
                    "details": {},
                },
            },
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        import logging

        logger = logging.getLogger("app")
        logger.exception("Unhandled exception: %s", exc)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "success": False,
                "error": {
                    "code": "internal_server_error",
                    "message": "An unexpected error occurred",
                    "details": {},
                },
            },
        )

