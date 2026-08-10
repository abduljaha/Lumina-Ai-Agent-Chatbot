"""LLM node - generates the assistant's response."""
from __future__ import annotations

import json
import logging
import time
from typing import Any

from app.agents.prompts import (
    build_context_message,
    build_reflection_feedback_message,
    build_system_prompt,
    build_tool_results_message,
    build_user_prompt,
)
from app.llm.base import LLMRequest
from app.llm.router import ModelRouter
from app.llm.vision import parse_data_url

logger = logging.getLogger("app")

# Bounded so a model that keeps requesting tools (a dependent chain, or one
# that just won't stop) always ends the turn in a real answer rather than
# looping - or costing - indefinitely. 4 rounds comfortably covers realistic
# chains (e.g. geocode -> weather -> unit conversion) while keeping a
# runaway worst case at 4 extra LLM round-trips, not unbounded.
_MAX_TOOL_ROUNDS = 4


def _ocr_fallback_text(images: list[str]) -> str:
    """Best-effort local OCR over image attachments.

    Used only when no configured provider's default model supports vision
    (see `generate_vision`'s failure path below) - degrades a vision request
    to "at least extract any text in the image" rather than a hard error,
    on the same pytesseract path DocumentProcessor uses for image documents.
    """
    try:
        import base64
        import io

        import pytesseract
        from PIL import Image
    except ImportError:
        return ""

    extracted: list[str] = []
    for image in images:
        parsed = parse_data_url(image)
        if not parsed:
            continue
        try:
            _, data = parsed
            img = Image.open(io.BytesIO(base64.b64decode(data)))
            text = pytesseract.image_to_string(img).strip()
            if text:
                extracted.append(text)
        except Exception as exc:  # noqa: BLE001
            logger.warning("OCR fallback failed for an image attachment: %s", exc)
    return "\n\n".join(extracted)


class LLMNode:
    """Calls the LLM with the assembled context and tool results.

    Handles provider selection, fallback, and reflection feedback.
    """

    def __init__(self, router: ModelRouter, tool_registry: Any | None = None, tool_executor: Any | None = None) -> None:
        self._router = router
        # Optional: enables native LLM function-calling as a fallback for
        # live-data questions intent_detection's regex patterns don't
        # recognize (see __call__) - graceful no-op if not provided.
        self._tool_registry = tool_registry
        # Same executor instance ToolSelectionNode uses (shared via
        # AgentGraph/AppContainer) - gives native function-calling the same
        # timeout/retry/fallback/caching/rate-limiting, and means a tool
        # already called by the regex fast-path this turn is cache-hit, not
        # re-invoked, if the model's own tool-calling asks for it again.
        if tool_executor is None and tool_registry is not None:
            from app.tools.executor import ToolExecutor

            tool_executor = ToolExecutor(tool_registry)
        self._executor = tool_executor

    async def __call__(self, state: dict[str, Any]) -> dict[str, Any]:
        """Generate a response using the configured LLM."""
        messages = state.get("messages", [])
        context = state.get("context")
        tool_results = state.get("tool_results", [])
        reflection_feedback = state.get("reflection_feedback")
        requested_model = state.get("requested_model")
        provider = state.get("metadata", {}).get("provider")
        images = state.get("images") or []

        # Build the system prompt
        system_prompt = build_system_prompt(state)

        # Build messages for the LLM
        llm_messages = [{"role": "system", "content": system_prompt}]

        # Add conversation history
        for msg in messages:
            role = getattr(msg, "type", None) or getattr(msg, "role", "user")
            if role == "human":
                role = "user"
            elif role == "ai":
                role = "assistant"
            content = getattr(msg, "content", "")
            if role == "user":
                content = build_user_prompt(content)
            llm_messages.append({"role": role, "content": content})

        # Add context
        if context:
            llm_messages.append({"role": "system", "content": build_context_message(context)})

        # Add tool results
        if tool_results:
            llm_messages.append({"role": "system", "content": build_tool_results_message(tool_results)})

        # Add reflection feedback on retry
        if reflection_feedback:
            llm_messages.append(
                {"role": "system", "content": build_reflection_feedback_message(reflection_feedback)}
            )

        request = LLMRequest(
            messages=llm_messages,
            model=requested_model,
            temperature=0.7,
            max_tokens=2048,
            stream=False,
            images=images or None,
        )

        start = time.perf_counter()
        used_tool_results = tool_results

        if images:
            # Vision requests skip tool-calling entirely - describing an
            # image, extracting its text, or reasoning about a scene doesn't
            # need a tool, and mixing image attachments with function-calling
            # is flaky across providers. Routed through `generate_vision`,
            # which only tries providers whose model actually accepts images
            # (see ModelRouter.build_vision_fallback_chain) rather than the
            # normal chain, which could otherwise land on a text-only model.
            try:
                response = await self._router.generate_vision(request, provider=provider)
            except Exception as exc:  # noqa: BLE001
                # No vision-capable provider configured/reachable - degrade
                # to local OCR over the image(s) plus a normal text-only
                # call, so the user still gets an answer (just without true
                # scene understanding) instead of a hard failure.
                logger.warning("Vision generation unavailable, falling back to OCR + text: %s", exc)
                ocr_text = _ocr_fallback_text(images)
                fallback_messages = llm_messages + [
                    {
                        "role": "system",
                        "content": (
                            "No vision-capable model is available. Text extracted via OCR from "
                            f"the attached image(s):\n\n{ocr_text}"
                            if ocr_text
                            else "No vision-capable model is available, and no text could be "
                            "extracted from the attached image(s). Let the user know you "
                            "can't see images right now."
                        ),
                    }
                ]
                fallback_request = LLMRequest(
                    messages=fallback_messages, model=requested_model, temperature=0.7, max_tokens=2048
                )
                response = await self._router.generate(fallback_request, provider=provider)

            latency = int((time.perf_counter() - start) * 1000)
            return {
                "generation": response.content,
                "current_model": response.model,
                "current_provider": response.provider,
                "latency_ms": latency,
                "token_usage": response.usage,
                "cost": response.cost,
                "tool_results": used_tool_results,
                "model_attempts": state.get("model_attempts", 0) + 1,
            }

        # Offer native function-calling only as a fallback: when the fast
        # regex path (intent_detection -> tool_selection) already ran a tool
        # this turn, its result is already in `tool_results`/context above,
        # so re-offering tools would just invite a redundant/duplicate call.
        # Also capped to the first pass (model_attempts == 0), not
        # reflection retries, so a bad first answer can't oscillate into
        # repeated tool-calling rounds.
        offer_tools = (
            self._tool_registry is not None
            and not tool_results
            and state.get("model_attempts", 0) == 0
        )
        if offer_tools:
            request.tools = self._tool_registry.to_openai_schemas()

        # Try with tools first, fall back to plain generation
        try:
            response = await self._router.generate_with_tools(request, provider=provider)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Tool-calling generation failed, falling back: %s", exc)
            response = await self._router.generate(request, provider=provider)

        latency = int((time.perf_counter() - start) * 1000)

        # The model decided a tool call was needed (only possible when
        # offer_tools was True). Tools stay offered across rounds - not just
        # one follow-up - so a genuinely DEPENDENT chain (e.g. resolve a
        # location, then use its coordinates in a second call) can complete;
        # bounded by _MAX_TOOL_ROUNDS so a model that won't stop asking for
        # tools can't loop indefinitely. Each round's tool calls run
        # concurrently via ToolExecutor (see _execute_tool_calls), and its
        # cache means asking for the same tool+args again - across rounds,
        # or repeating what the regex fast-path already ran - doesn't pay
        # for a second real call.
        round_messages = llm_messages
        rounds = 0
        while response.tool_calls and self._tool_registry is not None and rounds < _MAX_TOOL_ROUNDS:
            rounds += 1
            round_results = await self._execute_tool_calls(response.tool_calls, state)
            used_tool_results = used_tool_results + round_results
            round_messages = round_messages + [
                {"role": "system", "content": build_tool_results_message(round_results)}
            ]
            if rounds >= _MAX_TOOL_ROUNDS:
                break  # force the final untooled call below rather than asking again
            next_request = LLMRequest(
                messages=round_messages,
                model=requested_model,
                temperature=0.7,
                max_tokens=2048,
                stream=False,
                tools=self._tool_registry.to_openai_schemas(),
            )
            try:
                response = await self._router.generate_with_tools(next_request, provider=provider)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Tool-calling generation failed mid-chain, finishing without further tools: %s", exc)
                break
            latency = int((time.perf_counter() - start) * 1000)

        if rounds > 0 and response.tool_calls:
            # Loop ended by hitting the round cap (not by the model settling
            # on a real answer) - tools are withheld this time so the call
            # can't ask for yet another round; it must answer with whatever
            # context it has so the turn never ends without a real reply.
            final_request = LLMRequest(
                messages=round_messages, model=requested_model, temperature=0.7, max_tokens=2048, stream=False,
            )
            response = await self._router.generate(final_request, provider=provider)
            latency = int((time.perf_counter() - start) * 1000)

        return {
            "generation": response.content,
            "current_model": response.model,
            "current_provider": response.provider,
            "latency_ms": latency,
            "token_usage": response.usage,
            "cost": response.cost,
            "tool_results": used_tool_results,
            "model_attempts": state.get("model_attempts", 0) + 1,
        }

    async def _execute_tool_calls(
        self, tool_calls: list[dict[str, Any]], state: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """Run tool call(s) the model requested via native function-calling.

        Delegates to the same `ToolExecutor` `tool_selection.py` uses, so a
        model-requested tool gets identical timeout/retry/transient-fallback/
        caching/rate-limiting - and independent tools in the same round run
        concurrently instead of one after another.
        """
        calls: list[tuple[str, dict[str, Any]]] = []
        for call in tool_calls:
            name = call.get("name", "")
            raw_args = call.get("arguments")
            # OpenAI/Groq return `arguments` as a JSON-encoded string (per
            # the OpenAI function-calling contract), but Gemini's provider
            # already hands back a parsed dict (see gemini_provider.py's
            # _extract_tool_calls) - json.loads() on that raises TypeError,
            # not JSONDecodeError, so it needs its own branch, not just a
            # wider except.
            if isinstance(raw_args, dict):
                args = raw_args
            else:
                try:
                    args = json.loads(raw_args or "{}")
                except json.JSONDecodeError:
                    args = {}
            args.setdefault("user_id", state.get("user_id"))
            calls.append((name, args))

        if not calls:
            return []
        if self._executor is None:
            # No shared executor wired (e.g. a test constructing LLMNode
            # with a tool_registry but no executor) - execute directly,
            # concurrently, with no retry/cache/rate-limit rather than
            # silently dropping the requested tool calls.
            async def _invoke(name: str, args: dict[str, Any]) -> dict[str, Any]:
                try:
                    result = await self._tool_registry.invoke(name, **args)
                    result_dict = result.to_dict()
                except Exception as exc:  # noqa: BLE001
                    result_dict = {"success": False, "output": None, "error": str(exc), "metadata": {}}
                result_dict["tool"] = name
                return result_dict

            import asyncio

            return list(await asyncio.gather(*(_invoke(name, args) for name, args in calls)))

        return await self._executor.run_many(calls, user_id=state.get("user_id"))
