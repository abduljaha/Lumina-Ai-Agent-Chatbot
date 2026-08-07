"""Shared helpers for attaching images to LLM requests (vision models).

Images travel through the app as `data:<mime>;base64,<data>` URLs end to
end (that's what a browser's `FileReader.readAsDataURL()` produces
client-side, and what OpenAI-compatible `image_url` content parts accept
directly) - these helpers convert that one representation into whatever
shape each provider's API actually expects.
"""
from __future__ import annotations

import re
from typing import Any

_DATA_URL_RE = re.compile(r"^data:(?P<mime>[\w/+.-]+);base64,(?P<data>.+)$", re.DOTALL)


def parse_data_url(data_url: str) -> tuple[str, str] | None:
    """Split a `data:<mime>;base64,<data>` URL into (mime_type, base64_data).

    Returns None if `data_url` isn't a data URL (e.g. it's already a plain
    http(s) URL, which OpenAI-compatible APIs also accept as-is).
    """
    match = _DATA_URL_RE.match(data_url.strip())
    if not match:
        return None
    return match.group("mime"), match.group("data")


def attach_images_openai_format(messages: list[dict[str, Any]], images: list[str]) -> list[dict[str, Any]]:
    """Return a copy of `messages` with `images` attached to the last user turn.

    Converts that message's `content` from a plain string to OpenAI's
    multi-part vision format: a text block followed by one `image_url`
    block per image. Used by the OpenAI, OpenRouter, and Groq providers,
    which all speak this same OpenAI-compatible chat-completions shape.
    """
    if not images:
        return messages
    messages = [dict(m) for m in messages]
    for i in range(len(messages) - 1, -1, -1):
        if messages[i].get("role") == "user":
            text = messages[i].get("content") or ""
            messages[i]["content"] = [
                {"type": "text", "text": text},
                *[{"type": "image_url", "image_url": {"url": img}} for img in images],
            ]
            break
    return messages
