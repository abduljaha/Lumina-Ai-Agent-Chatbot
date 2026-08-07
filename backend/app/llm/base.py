"""Base LLM provider interface and message types."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Protocol

from app.core.config import get_settings

settings = get_settings()


@dataclass
class ModelResponse:
    """Standardized response from an LLM provider."""

    content: str
    model: str
    provider: str
    usage: dict[str, int] = field(default_factory=dict)
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    latency_ms: int = 0
    cost: float = 0.0
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class LLMRequest:
    """Request to an LLM provider."""

    messages: list[dict[str, Any]]
    model: str | None = None
    temperature: float = 0.7
    max_tokens: int = 2048
    stream: bool = False
    tools: list[dict[str, Any]] | None = None
    tool_choice: str | None = None
    images: list[str] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class BaseLLMProvider(Protocol):
    """Protocol for all LLM providers."""

    name: str
    available: bool

    async def generate(self, request: LLMRequest) -> ModelResponse:
        """Generate a non-streaming completion."""
        ...

    async def stream(self, request: LLMRequest) -> AsyncIterator[ModelResponse]:
        """Stream a completion token-by-token."""
        ...

    async def generate_with_tools(self, request: LLMRequest) -> ModelResponse:
        """Generate a completion with tool calling support."""
        ...

    def get_models(self) -> list[dict[str, Any]]:
        """List available models for this provider."""
        ...
