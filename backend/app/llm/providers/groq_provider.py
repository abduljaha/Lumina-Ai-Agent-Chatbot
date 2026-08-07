"""Groq provider implementation (OpenAI-compatible)."""
from __future__ import annotations

import time
from typing import Any, AsyncIterator

from app.core.config import get_settings
from app.llm.base import LLMRequest, ModelResponse
from app.llm.vision import attach_images_openai_format

settings = get_settings()


class GroqProvider:
    """Provider for Groq's fast inference API."""

    name = "groq"
    available: bool = bool(settings.groq_api_key)

    def __init__(self, api_key: str | None = None) -> None:
        self._api_key = api_key or settings.groq_api_key

    async def _client(self):
        from openai import AsyncOpenAI

        return AsyncOpenAI(
            api_key=self._api_key,
            base_url="https://api.groq.com/openai/v1",
            # The router already falls back across providers on failure, so
            # the SDK's own default (2) internal retries just add redundant
            # delay before that fallback ever gets a chance to run.
            max_retries=0,
        )

    async def generate(self, request: LLMRequest) -> ModelResponse:
        """Generate a non-streaming completion."""
        client = await self._client()
        start = time.perf_counter()
        messages = attach_images_openai_format(request.messages, request.images or [])
        resp = await client.chat.completions.create(
            model=request.model or settings.groq_model,
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
        """Stream a completion."""
        client = await self._client()
        start = time.perf_counter()
        stream = await client.chat.completions.create(
            model=request.model or settings.groq_model,
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
            "model": request.model or settings.groq_model,
            "messages": messages,
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
            "stream": False,
        }
        if request.tools:
            kwargs["tools"] = request.tools
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
                "name": "llama-3.3-70b-versatile",
                "provider": self.name,
                "display_name": "Llama 3.3 70B",
                "description": "Fast Llama model via Groq",
                "capabilities": ["text", "streaming", "tools"],
                "context_window": 128000,
            },
            {
                "name": "llama-3.1-8b-instant",
                "provider": self.name,
                "display_name": "Llama 3.1 8B",
                "description": "Ultra-fast small model",
                "capabilities": ["text", "streaming", "tools"],
                "context_window": 128000,
            },
        ]
