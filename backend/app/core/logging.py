"""Structured logging configuration using JSON formatter.

Provides request/response logging middleware and a JSON log formatter
for consistent, machine-parseable logs.
"""
from __future__ import annotations

import json
import logging
import sys
import time
from datetime import datetime, timezone
from typing import Any

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.config import get_settings

settings = get_settings()


class JSONFormatter(logging.Formatter):
    """Custom logging formatter that outputs JSON lines."""

    def format(self, record: logging.LogRecord) -> str:
        log_entry: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }

        # Include exception info if present
        if record.exc_info:
            log_entry["exception"] = self.formatException(record.exc_info)

        # Include extra fields (request_id, user_id, etc.)
        for key, value in record.__dict__.items():
            if key not in ("args", "asctime", "created", "exc_info", "exc_text", "filename",
                           "funcName", "levelname", "levelno", "lineno", "module", "msecs",
                           "message", "msg", "name", "pathname", "process", "processName",
                           "relativeCreated", "stack_info", "thread", "threadName", "taskName"):
                log_entry[key] = value

        return json.dumps(log_entry, default=str)


def setup_logging(level: str | None = None) -> None:
    """Configure application-wide structured logging."""
    log_level = level or ("DEBUG" if settings.debug else "INFO")
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JSONFormatter())

    root_logger = logging.getLogger()
    root_logger.handlers = []
    root_logger.addHandler(handler)
    # Root stays at INFO regardless of app debug mode: DEBUG here would also
    # apply to every third-party library's logger (aiosqlite, urllib3,
    # huggingface_hub, ...), flooding stdout with per-operation chatter that
    # adds real I/O overhead and drowns out the app's own logs.
    root_logger.setLevel("INFO")

    # Set specific loggers
    logging.getLogger("uvicorn.access").setLevel(log_level)
    logging.getLogger("app").setLevel(log_level)


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Middleware that logs all HTTP requests and responses."""

    async def dispatch(self, request: Request, call_next: Any) -> Response:
        start_time = time.perf_counter()
        logger = logging.getLogger("app.access")

        # Generate or extract request ID
        request_id = request.headers.get("X-Request-ID")
        if not request_id:
            import uuid

            request_id = str(uuid.uuid4())

        request.state.request_id = request_id

        body = b""
        if request.method in ("POST", "PUT", "PATCH"):
            try:
                body = await request.body()
            except Exception:
                pass

        logger.info(
            "Request started",
            extra={
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "query": str(request.query_params),
                "client": request.client.host if request.client else None,
                "body_size": len(body),
            },
        )

        try:
            response = await call_next(request)
            response.headers["X-Request-ID"] = request_id
        except Exception as exc:
            logger.exception(
                "Request failed",
                extra={
                    "request_id": request_id,
                    "method": request.method,
                    "path": request.url.path,
                },
            )
            raise exc

        duration_ms = (time.perf_counter() - start_time) * 1000
        logger.info(
            "Request completed",
            extra={
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
                "duration_ms": round(duration_ms, 2),
            },
        )
        return response

