"""Model router - resolves providers and handles fallback chains.

The router dynamically selects the best available provider/model based on
the requested provider, model, and availability. It implements a fallback
chain: primary -> fallback -> offline -> graceful failure.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, AsyncIterator

from app.core.config import get_settings
from app.core.exceptions import ProviderError, ServiceUnavailableError
from app.llm.base import LLMRequest, ModelResponse
from app.llm.providers import GeminiProvider, GroqProvider, OpenAIProvider

logger = logging.getLogger("app")
settings = get_settings()

# Applied per attempt/chunk in generate/generate_with_tools/stream below.
# No provider SDK sets its own request timeout, so without this a hung
# (not erroring, just silent) provider blocks on the SDK's own default -
# often several minutes - before the fallback chain gets to try the next
# one, which defeats the point of having a fallback chain at all.
_PROVIDER_TIMEOUT_SECONDS = 45

# How long a provider that just failed (bad key, no credits, rate-limited,
# ...) is skipped in *later* fallback chains. A dead provider fails fast
# (no timeout to wait out), so this isn't about the current request - it's
# about not spending a network round-trip on a provider that's overwhelmingly
# likely to fail again on the very next message too. Short enough that a
# transient blip (a momentary 429) self-heals within a couple of messages.
_COOLDOWN_SECONDS = 120


def _all_failed_message(chain: list[str]) -> str:
    """User-facing message when every provider in the chain has failed.

    Deliberately doesn't include the raw exception text - that's logged
    server-side (see the per-provider `logger.warning` calls) and passed
    separately as `details` for API clients, but the chat UI renders this
    message directly in the conversation, and provider SDK errors can be
    long, technical, or (in edge cases) echo back request internals that
    have no business being shown to the end user.
    """
    if not chain:
        return "No AI provider is configured. Add an API key to start chatting."
    return (
        "All AI providers are temporarily unavailable (rate-limited, out of "
        "quota, or unreachable). Please try again in a moment."
    )


class ModelRouter:
    """Routes LLM requests to the appropriate provider with fallbacks."""

    _PROVIDER_MAP = {
        "openai": OpenAIProvider,
        "groq": GroqProvider,
        "gemini": GeminiProvider,
        "openrouter": lambda: OpenAIProvider(
            api_key=settings.openrouter_api_key,
            base_url=settings.openrouter_base_url,
            name="openrouter",
        ),
    }

    def __init__(self) -> None:
        self._providers = self._build_providers()
        # Provider name -> monotonic timestamp its cooldown ends. Not a hard
        # exclusion (see build_fallback_chain) - just deprioritized so a
        # provider that failed on the last message doesn't eat a network
        # round-trip on every message after it too, while a wrong guess
        # (cooldown outlives the actual outage) still self-heals as soon as
        # every other provider is also unavailable.
        self._cooldown_until: dict[str, float] = {}

    def _mark_failed(self, name: str) -> None:
        self._cooldown_until[name] = time.monotonic() + _COOLDOWN_SECONDS

    def _mark_recovered(self, name: str) -> None:
        self._cooldown_until.pop(name, None)

    def _is_cooling_down(self, name: str) -> bool:
        return time.monotonic() < self._cooldown_until.get(name, 0.0)

    def _build_providers(self) -> dict[str, Any]:
        """Build and cache provider instances."""
        providers: dict[str, Any] = {}
        for name, factory in self._PROVIDER_MAP.items():
            try:
                provider = factory()
                if getattr(provider, "available", False):
                    providers[name] = provider
            except Exception as exc:  # noqa: BLE001
                logger.warning("Provider '%s' failed to initialize: %s", name, exc)
        return providers

    @property
    def available_providers(self) -> list[str]:
        """List names of available providers."""
        return list(self._providers.keys())

    def resolve(self, provider: str | None = None, model: str | None = None) -> tuple[Any, str]:
        """Resolve a provider instance and model name.

        Args:
            provider: Requested provider name (openai|groq|gemini|openrouter).
            model: Requested model name.

        Returns:
            (provider_instance, model_name)

        Raises:
            ServiceUnavailableError: If no provider is available.
        """
        requested = (provider or "").lower()
        if requested in self._providers:
            resolved_provider = self._providers[requested]
            resolved_model = model or self._default_model_for(requested)
            return resolved_provider, resolved_model

        # Fall back to the first available provider
        if self._providers:
            name = self.available_providers[0]
            return self._providers[name], model or self._default_model_for(name)

        raise ServiceUnavailableError("No LLM provider is available. Configure an API key.")

    def _default_model_for(self, provider: str) -> str:
        """Return the default model for a provider."""
        defaults = {
            "openai": settings.openai_model,
            "groq": settings.groq_model,
            "gemini": settings.gemini_model,
            "openrouter": settings.openrouter_model,
        }
        return defaults.get(provider, settings.openai_model)

    def build_fallback_chain(self, provider: str | None = None) -> list[str]:
        """Build the ordered fallback provider chain."""
        chain: list[str] = []
        if provider and provider in self._providers:
            chain.append(provider)
        chain.extend(
            p for p in settings.fallback_models if p in self._providers and p not in chain
        )
        # Any remaining provider is still better than giving up, so keep them as a
        # last resort - entries in fallback_models that name a model rather than a
        # provider are skipped above and would otherwise leave the chain too short.
        chain.extend(p for p in self.available_providers if p not in chain)

        # Providers on cooldown (failed very recently - bad key, no credits,
        # rate-limited) are moved to the end rather than dropped: still tried
        # if every healthy provider also fails, but no longer eat a request's
        # worth of latency ahead of providers actually likely to work.
        healthy = [p for p in chain if not self._is_cooling_down(p)]
        cooling_down = [p for p in chain if self._is_cooling_down(p)]
        return healthy + cooling_down

    def _supports_vision(self, provider_name: str) -> bool:
        """Whether a provider's currently-configured default model accepts images.

        Not every model a provider offers is multimodal (Groq's default
        llama-3.3-70b-versatile isn't, for example, even though Groq also
        hosts vision-capable models) - checked against the *resolved*
        default model specifically, not just "does this provider have any
        vision model anywhere in its list".
        """
        provider = self._providers.get(provider_name)
        if not provider:
            return False
        default_model = self._default_model_for(provider_name)
        models = provider.get_models()
        for m in models:
            if m.get("name") == default_model:
                return "image" in (m.get("capabilities") or [])
        # Default model isn't in the provider's own catalog (e.g. a custom
        # OPENAI_MODEL override) - fall back to "any vision model at all" as
        # a looser signal rather than assuming no support.
        return any("image" in (m.get("capabilities") or []) for m in models)

    def build_vision_fallback_chain(self, provider: str | None = None) -> list[str]:
        """Fallback chain restricted to providers whose default model supports images.

        Used instead of `build_fallback_chain` for requests carrying image
        attachments, so a vision request never lands on a text-only default
        model (which would either error or silently ignore the image).
        """
        return [p for p in self.build_fallback_chain(provider) if self._supports_vision(p)]

    async def generate(self, request: LLMRequest, provider: str | None = None) -> ModelResponse:
        """Generate a completion, trying the fallback chain on failure."""
        chain = self.build_fallback_chain(provider)
        last_error: Exception | None = None
        for prov_name in chain:
            try:
                prov = self._providers[prov_name]
                req = LLMRequest(
                    messages=request.messages,
                    model=request.model,
                    temperature=request.temperature,
                    max_tokens=request.max_tokens,
                    stream=False,
                    tools=request.tools,
                    tool_choice=request.tool_choice,
                    images=request.images,
                    metadata=request.metadata,
                )
                # No provider SDK here sets its own request timeout, so a
                # provider that hangs (rather than erroring) would otherwise
                # block on the SDK's default - often several minutes -
                # before this loop ever got a chance to try the next one.
                resp = await asyncio.wait_for(prov.generate(req), timeout=_PROVIDER_TIMEOUT_SECONDS)
                resp.provider = prov_name
                self._mark_recovered(prov_name)
                return resp
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                self._mark_failed(prov_name)
                logger.warning("Provider '%s' failed: %s", prov_name, exc)
        raise ProviderError(_all_failed_message(chain), details={"last_error": str(last_error)})

    async def generate_vision(self, request: LLMRequest, provider: str | None = None) -> ModelResponse:
        """Generate a completion for a request carrying image attachments.

        Mirrors `generate`, but tries only providers whose default model is
        actually multimodal (see `build_vision_fallback_chain`) - falling
        through the normal chain would otherwise let a vision request land
        on a text-only model, which either 400s or silently answers as if
        the image were never sent.
        """
        chain = self.build_vision_fallback_chain(provider)
        if not chain:
            raise ProviderError(
                "No configured AI provider supports image input. "
                "Configure an OpenAI, Gemini, or OpenRouter API key to enable vision."
            )
        last_error: Exception | None = None
        for prov_name in chain:
            try:
                prov = self._providers[prov_name]
                req = LLMRequest(
                    messages=request.messages,
                    model=request.model,
                    temperature=request.temperature,
                    max_tokens=request.max_tokens,
                    stream=False,
                    images=request.images,
                    metadata=request.metadata,
                )
                resp = await asyncio.wait_for(prov.generate(req), timeout=_PROVIDER_TIMEOUT_SECONDS)
                resp.provider = prov_name
                self._mark_recovered(prov_name)
                return resp
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                self._mark_failed(prov_name)
                logger.warning("Vision provider '%s' failed: %s", prov_name, exc)
        raise ProviderError(_all_failed_message(chain), details={"last_error": str(last_error)})

    async def generate_with_tools(
        self, request: LLMRequest, provider: str | None = None
    ) -> ModelResponse:
        """Generate with tool calling, trying the fallback chain."""
        chain = self.build_fallback_chain(provider)
        last_error: Exception | None = None
        for prov_name in chain:
            try:
                prov = self._providers[prov_name]
                resp = await asyncio.wait_for(
                    prov.generate_with_tools(request), timeout=_PROVIDER_TIMEOUT_SECONDS
                )
                resp.provider = prov_name
                self._mark_recovered(prov_name)
                return resp
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                self._mark_failed(prov_name)
                logger.warning("Tool-calling provider '%s' failed: %s", prov_name, exc)
        raise ProviderError(_all_failed_message(chain), details={"last_error": str(last_error)})

    async def stream(
        self, request: LLMRequest, provider: str | None = None
    ) -> AsyncIterator[ModelResponse]:
        """Stream a completion, trying the fallback chain on failure.

        Each individual chunk gets its own timeout budget (not the stream as
        a whole, which is unbounded by design) - a provider that stops
        sending data mid-stream is indistinguishable from one that's just
        thinking, so this is the only way to catch a stall without also
        misfiring on a normal, valid pause between chunks.
        """
        chain = self.build_fallback_chain(provider)
        last_error: Exception | None = None
        for prov_name in chain:
            try:
                prov = self._providers[prov_name]
                agen = prov.stream(request)
                try:
                    while True:
                        try:
                            chunk = await asyncio.wait_for(agen.__anext__(), timeout=_PROVIDER_TIMEOUT_SECONDS)
                        except StopAsyncIteration:
                            break
                        chunk.provider = prov_name
                        yield chunk
                    self._mark_recovered(prov_name)
                    return
                finally:
                    await agen.aclose()
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                self._mark_failed(prov_name)
                logger.warning("Streaming provider '%s' failed: %s", prov_name, exc)
        raise ProviderError(_all_failed_message(chain), details={"last_error": str(last_error)})

    def list_models(self) -> list[dict[str, Any]]:
        """List all available models across providers."""
        models: list[dict[str, Any]] = []
        for name, provider in self._providers.items():
            try:
                for model in provider.get_models():
                    model["is_available"] = True
                    models.append(model)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Could not list models for '%s': %s", name, exc)
        return models
