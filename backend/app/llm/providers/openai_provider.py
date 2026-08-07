"""OpenAI provider implementation."""
from __future__ import annotations

import time
from typing import Any, AsyncIterator

from app.core.config import get_settings
from app.llm.base import BaseLLMProvider, LLMRequest, ModelResponse
from app.llm.vision import attach_images_openai_format

settings = get_settings()


class OpenAIProvider:
    """Provider for OpenAI-compatible APIs (OpenAI, OpenRouter)."""

    # Class-level fallbacks so `available` can still be read before init in
    # any code that inspects the class itself, but a differently-named,
    # differently-keyed instance (e.g. OpenRouter) must override both below -
    # otherwise it silently reports OpenAI's key/name instead of its own.
    name = "openai"
    available: bool = bool(settings.openai_api_key)

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        name: str | None = None,
    ) -> None:
        self._api_key = api_key or settings.openai_api_key
        self._base_url = base_url
        if name:
            self.name = name
            self.available = bool(self._api_key)

    async def _client(self):
        from openai import AsyncOpenAI

        kwargs: dict[str, Any] = {"api_key": self._api_key, "max_retries": 0}
        if self._base_url:
            kwargs["base_url"] = self._base_url
        return AsyncOpenAI(**kwargs)

    async def generate(self, request: LLMRequest) -> ModelResponse:
        """Generate a non-streaming completion."""
        client = await self._client()
        start = time.perf_counter()
        messages = attach_images_openai_format(request.messages, request.images or [])
        resp = await client.chat.completions.create(
            model=request.model or settings.openai_model,
            messages=messages,
            temperature=request.temperature,
            max_tokens=request.max_tokens,
            stream=False,
        )
        latency = int((time.perf_counter() - start) * 1000)
        choice = resp.choices[0]
        return ModelResponse(
            content=choice.message.content or "",
            model=resp.model,
            provider=self.name,
            usage={
                "prompt_tokens": resp.usage.prompt_tokens if resp.usage else 0,
                "completion_tokens": resp.usage.completion_tokens if resp.usage else 0,
                "total_tokens": resp.usage.total_tokens if resp.usage else 0,
            },
            latency_ms=latency,
            raw=resp.model_dump(),
        )

    async def stream(self, request: LLMRequest) -> AsyncIterator[ModelResponse]:
        """Stream a completion token-by-token."""
        client = await self._client()
        start = time.perf_counter()
        stream = await client.chat.completions.create(
            model=request.model or settings.openai_model,
            messages=request.messages,
            temperature=request.temperature,
            max_tokens=request.max_tokens,
            stream=True,
        )
        async for chunk in stream:
            delta = chunk.choices[0].delta if chunk.choices else None
            if delta and delta.content:
                yield ModelResponse(
                    content=delta.content,
                    model=chunk.model,
                    provider=self.name,
                    latency_ms=int((time.perf_counter() - start) * 1000),
                )

    async def generate_with_tools(self, request: LLMRequest) -> ModelResponse:
        """Generate with tool calling support."""
        client = await self._client()
        start = time.perf_counter()
        messages = attach_images_openai_format(request.messages, request.images or [])
        kwargs: dict[str, Any] = {
            "model": request.model or settings.openai_model,
            "messages": messages,
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
            "stream": False,
        }
        if request.tools:
            kwargs["tools"] = request.tools
        if request.tool_choice:
            kwargs["tool_choice"] = request.tool_choice

        resp = await client.chat.completions.create(**kwargs)
        latency = int((time.perf_counter() - start) * 1000)
        choice = resp.choices[0]
        tool_calls = []
        if choice.message.tool_calls:
            tool_calls = [
                {
                    "id": tc.id,
                    "name": tc.function.name,
                    "arguments": tc.function.arguments,
                }
                for tc in choice.message.tool_calls
            ]
        return ModelResponse(
            content=choice.message.content or "",
            model=resp.model,
            provider=self.name,
            tool_calls=tool_calls,
            usage={
                "prompt_tokens": resp.usage.prompt_tokens if resp.usage else 0,
                "completion_tokens": resp.usage.completion_tokens if resp.usage else 0,
                "total_tokens": resp.usage.total_tokens if resp.usage else 0,
            },
            latency_ms=latency,
            raw=resp.model_dump(),
        )

    def get_models(self) -> list[dict[str, Any]]:
        """List available models."""
        return [
            {
                "name": "gpt-4o",
                "provider": self.name,
                "display_name": "GPT-4o",
                "description": "OpenAI's flagship multimodal model",
                "capabilities": ["text", "image", "streaming", "tools"],
                "context_window": 128000,
            },
            {
                "name": "gpt-4o-mini",
                "provider": self.name,
                "display_name": "GPT-4o mini",
                "description": "Fast, affordable OpenAI model",
                "capabilities": ["text", "image", "streaming", "tools"],
                "context_window": 128000,
            },
        ]
