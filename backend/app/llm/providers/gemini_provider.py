"""Google Gemini provider implementation."""
from __future__ import annotations

import asyncio
import threading
import time
from typing import Any, AsyncIterator

from app.core.config import get_settings
from app.llm.base import LLMRequest, ModelResponse
from app.llm.vision import parse_data_url

settings = get_settings()


def _to_gemini_contents(
    messages: list[dict[str, Any]], images: list[str] | None = None
) -> tuple[list[dict[str, Any]], str | None]:
    """Convert OpenAI-style chat messages to Gemini's `contents` + system instruction.

    Gemini has no "system" role in `contents` - system messages are passed
    separately via `system_instruction`. Assistant turns map to "model".
    `images` (data URLs) are attached as `inline_data` parts on the last
    user turn - Gemini's own multimodal format, distinct from OpenAI's
    `image_url` blocks (see app.llm.vision).
    """
    system_parts: list[str] = []
    contents: list[dict[str, Any]] = []
    for message in messages:
        role = message.get("role")
        text = message.get("content") or ""
        if role == "system":
            system_parts.append(text)
            continue
        gemini_role = "model" if role == "assistant" else "user"
        contents.append({"role": gemini_role, "parts": [{"text": text}]})

    if images:
        for entry in reversed(contents):
            if entry["role"] == "user":
                for image in images:
                    parsed = parse_data_url(image)
                    if parsed:
                        mime_type, data = parsed
                        entry["parts"].append({"inline_data": {"mime_type": mime_type, "data": data}})
                break

    return contents, ("\n".join(system_parts) if system_parts else None)


def _to_gemini_tools(tools: list[dict[str, Any]] | None) -> list[Any] | None:
    """Convert OpenAI-style function tool schemas to Gemini FunctionDeclarations."""
    if not tools:
        return None
    from google.genai import types

    declarations = []
    for tool in tools:
        fn = tool.get("function", tool)
        declarations.append(
            types.FunctionDeclaration(
                name=fn.get("name", ""),
                description=fn.get("description", ""),
                parameters=fn.get("parameters") or {"type": "object", "properties": {}},
            )
        )
    return [types.Tool(function_declarations=declarations)]


def _extract_tool_calls(response: Any) -> list[dict[str, Any]]:
    """Pull function calls out of a Gemini response, in the app's standard shape."""
    calls: list[dict[str, Any]] = []
    candidates = getattr(response, "candidates", None) or []
    for candidate in candidates:
        parts = getattr(getattr(candidate, "content", None), "parts", None) or []
        for part in parts:
            fc = getattr(part, "function_call", None)
            if fc:
                calls.append(
                    {
                        "id": fc.name,
                        "name": fc.name,
                        "arguments": dict(fc.args) if fc.args else {},
                    }
                )
    return calls


class GeminiProvider:
    """Provider for Google Gemini models."""

    name = "gemini"
    available: bool = bool(settings.gemini_api_key)

    def __init__(self, api_key: str | None = None) -> None:
        self._api_key = api_key or settings.gemini_api_key

    def _client(self):
        from google import genai

        return genai.Client(api_key=self._api_key)

    async def generate(self, request: LLMRequest) -> ModelResponse:
        """Generate a non-streaming completion."""
        from google.genai import types

        client = self._client()
        contents, system_instruction = _to_gemini_contents(request.messages, request.images)
        model = request.model or settings.gemini_model
        start = time.perf_counter()

        def _call():
            return client.models.generate_content(
                model=model,
                contents=contents,
                config=types.GenerateContentConfig(
                    temperature=request.temperature,
                    max_output_tokens=request.max_tokens,
                    system_instruction=system_instruction,
                ),
            )

        # The google-genai SDK is synchronous; running it inline here would
        # block the whole FastAPI event loop (every request, every user) for
        # the duration of each call.
        response = await asyncio.to_thread(_call)
        latency = int((time.perf_counter() - start) * 1000)
        usage = getattr(response, "usage_metadata", None)
        return ModelResponse(
            content=response.text or "",
            model=model,
            provider=self.name,
            latency_ms=latency,
            usage={"total_tokens": getattr(usage, "total_token_count", 0) or 0} if usage else {},
        )

    async def stream(self, request: LLMRequest) -> AsyncIterator[ModelResponse]:
        """Stream a completion without blocking the event loop.

        The SDK's stream is a synchronous iterator, so it's driven from a
        background thread and bridged back via an asyncio.Queue - consuming
        it with a plain `for` loop here would block the whole server on every
        chunk, not just the first call.
        """
        from google.genai import types

        client = self._client()
        contents, system_instruction = _to_gemini_contents(request.messages)
        model = request.model or settings.gemini_model
        start = time.perf_counter()

        loop = asyncio.get_event_loop()
        queue: asyncio.Queue = asyncio.Queue()
        SENTINEL = object()

        def _produce() -> None:
            try:
                response = client.models.generate_content_stream(
                    model=model,
                    contents=contents,
                    config=types.GenerateContentConfig(
                        temperature=request.temperature,
                        max_output_tokens=request.max_tokens,
                        system_instruction=system_instruction,
                    ),
                )
                for chunk in response:
                    if chunk.text:
                        loop.call_soon_threadsafe(queue.put_nowait, chunk.text)
            except Exception as exc:  # noqa: BLE001
                loop.call_soon_threadsafe(queue.put_nowait, exc)
            finally:
                loop.call_soon_threadsafe(queue.put_nowait, SENTINEL)

        threading.Thread(target=_produce, daemon=True).start()

        while True:
            item = await queue.get()
            if item is SENTINEL:
                return
            if isinstance(item, Exception):
                raise item
            yield ModelResponse(
                content=item,
                model=model,
                provider=self.name,
                latency_ms=int((time.perf_counter() - start) * 1000),
            )

    async def generate_with_tools(self, request: LLMRequest) -> ModelResponse:
        """Generate a completion with tool calling support."""
        from google.genai import types

        client = self._client()
        contents, system_instruction = _to_gemini_contents(request.messages, request.images)
        model = request.model or settings.gemini_model
        gemini_tools = _to_gemini_tools(request.tools)
        start = time.perf_counter()

        def _call():
            return client.models.generate_content(
                model=model,
                contents=contents,
                config=types.GenerateContentConfig(
                    temperature=request.temperature,
                    max_output_tokens=request.max_tokens,
                    system_instruction=system_instruction,
                    tools=gemini_tools,
                ),
            )

        response = await asyncio.to_thread(_call)
        latency = int((time.perf_counter() - start) * 1000)
        usage = getattr(response, "usage_metadata", None)
        return ModelResponse(
            content=response.text or "",
            model=model,
            provider=self.name,
            tool_calls=_extract_tool_calls(response),
            latency_ms=latency,
            usage={"total_tokens": getattr(usage, "total_token_count", 0) or 0} if usage else {},
        )

    def get_models(self) -> list[dict[str, Any]]:
        """List available models."""
        return [
            {
                "name": "gemini-2.5-flash",
                "provider": self.name,
                "display_name": "Gemini 2.5 Flash",
                "description": "Google's fast multimodal model",
                "capabilities": ["text", "image", "streaming", "tools"],
                "context_window": 1000000,
            },
            {
                # Google-maintained alias that always points at their current
                # recommended flash model, so it doesn't go stale the way a
                # pinned version number eventually does (gemini-1.5-* did).
                "name": "gemini-flash-latest",
                "provider": self.name,
                "display_name": "Gemini Flash (latest)",
                "description": "Always points at Google's current flash model",
                "capabilities": ["text", "image", "streaming", "tools"],
                "context_window": 1000000,
            },
        ]
