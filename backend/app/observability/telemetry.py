"""Tracing and metrics via OpenTelemetry and LangSmith."""
from __future__ import annotations

import logging

from app.core.config import get_settings

logger = logging.getLogger("app")
settings = get_settings()


def setup_tracing() -> None:
    """Configure OpenTelemetry tracing and LangSmith integration."""
    # LangSmith
    if settings.langchain_api_key:
        try:
            import os

            os.environ["LANGCHAIN_TRACING_V2"] = "true" if settings.langchain_tracing_v2 else "false"
            os.environ["LANGCHAIN_API_KEY"] = settings.langchain_api_key
            os.environ["LANGCHAIN_PROJECT"] = settings.langchain_project
            logger.info("LangSmith tracing enabled for project '%s'", settings.langchain_project)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to configure LangSmith: %s", exc)

    # OpenTelemetry
    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        resource = Resource.create({"service.name": settings.app_name})
        provider = TracerProvider(resource=resource)
        exporter = OTLPSpanExporter(endpoint=settings.otel_exporter_otlp_endpoint, insecure=True)
        provider.add_span_processor(BatchSpanProcessor(exporter))
        trace.set_tracer_provider(provider)
        logger.info("OpenTelemetry tracing enabled at %s", settings.otel_exporter_otlp_endpoint)
    except Exception as exc:  # noqa: BLE001
        logger.warning("OpenTelemetry not configured: %s", exc)


def get_tracer(name: str = "app"):
    """Return a tracer for manual instrumentation."""
    try:
        from opentelemetry import trace

        return trace.get_tracer(name)
    except Exception:  # noqa: BLE001
        return None
