"""LLM-driven extraction of long-term profile facts from a conversation turn.

Runs as a background task after each chat turn (see chat.py), independent of
the fast regex-based extraction in extraction.py. The regex pass covers
common, cheaply-recognizable phrasings with zero added latency; this pass
catches everything else by asking the model itself to decide what's worth
remembering - including corrections to existing facts and explicit
"forget X" requests, which no fixed pattern list can anticipate.
"""
from __future__ import annotations

import json
import logging

from app.llm.base import LLMRequest
from app.llm.router import ModelRouter

logger = logging.getLogger("app")

_SYSTEM_PROMPT = (
    "You maintain a user's long-term profile memory for an AI assistant. Given "
    "the latest exchange and the facts already on file, decide whether anything "
    "STABLE and LONG-TERM about the user was newly stated, corrected, or should "
    "be forgotten.\n"
    "Stable facts: name, age, date of birth, gender, address, phone number, "
    "email, occupation, employer, home location/city, timezone, language, and "
    "similar durable personal details, plus lasting preferences (e.g. dietary "
    "restrictions, communication style).\n"
    "Do NOT record: one-off requests, questions, opinions about the current "
    "topic, or anything not durably true about the user going forward. Only "
    "record facts the user stated about THEMSELVES, never facts about other "
    "people, places, or things they merely mentioned.\n"
    "If the user asks to be forgotten, corrects a wrong fact, or says something "
    "no longer applies (e.g. \"I don't live there anymore\"), list that key "
    'under "deletions" - do not just leave it unchanged.\n\n'
    "Respond with ONLY a JSON object of this exact shape, nothing else:\n"
    '{"updates": [{"key": "location", "value": "Mumbai"}], "deletions": ["old_key"]}\n'
    "Use empty arrays when there is nothing to change. Keys are short lowercase "
    'snake_case identifiers (e.g. "occupation", "phone", "employer").'
)


def _build_user_prompt(conversation: str, existing_facts: dict[str, str]) -> str:
    facts_text = "\n".join(f"- {k}: {v}" for k, v in existing_facts.items()) or "(none yet)"
    return (
        f"Facts already on file:\n{facts_text}\n\n"
        f"Latest exchange:\n{conversation}\n\n"
        "What updates or deletions, if any, should be made?"
    )


def _strip_code_fence(raw: str) -> str:
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.lower().startswith("json"):
            raw = raw[4:]
    return raw.strip()


async def llm_extract_profile_updates(
    router: ModelRouter,
    conversation: str,
    existing_facts: dict[str, str],
) -> tuple[list[dict[str, str]], list[str]]:
    """Ask the model to decide on profile updates/deletions for this turn.

    Returns (updates, deletions) - updates is a list of {"key", "value"}
    dicts, deletions is a list of keys to remove. Returns ([], []) on any
    failure (malformed output, provider error) rather than raising - this
    always runs as best-effort background enrichment, never something a
    chat turn's success depends on.
    """
    request = LLMRequest(
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": _build_user_prompt(conversation, existing_facts)},
        ],
        temperature=0.0,
        max_tokens=400,
        stream=False,
    )
    try:
        # Groq first (fast, cheap) - this is a background enrichment pass,
        # not the user-facing reply, so it shouldn't compete for the same
        # latency budget as the visible answer, or fall back through every
        # provider (that's only worth doing for the reply itself).
        response = await router.generate(request, provider="groq")
        data = json.loads(_strip_code_fence(response.content))
        updates = [
            {"key": str(u["key"]).strip().lower().replace(" ", "_"), "value": str(u["value"]).strip()}
            for u in data.get("updates", [])
            if isinstance(u, dict) and u.get("key") and u.get("value")
        ]
        deletions = [
            str(k).strip().lower().replace(" ", "_") for k in data.get("deletions", []) if k
        ]
        return updates, deletions
    except Exception as exc:  # noqa: BLE001
        logger.warning("LLM profile extraction failed: %s", exc)
        return [], []
