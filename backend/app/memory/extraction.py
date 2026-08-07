"""Personal-information extraction for global, cross-thread user memory.

Heuristic, pattern-based (matching the style already used for intent
detection) rather than an extra LLM call per turn - keeps this fast and free
of added per-message latency. Anything captured here is written as ENTITY or
USER_PREFERENCE memory, which `MemoryManager.retrieve_for_context` already
pulls for *every* thread the user has (it queries by user_id, not
thread_id), so a fact learned in one conversation is available in all of the
user's other conversations too.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# Captures the value after the trigger phrase, stopping at sentence-ending
# punctuation or a conjunction/"but" so trailing clauses don't get swallowed
# (e.g. "my name is Sarah and I live in Hyderabad" should split into two facts).
_STOP = r"(?:[.,!?;]|\s+(?:and|but|who|which|that)\b|$)"


@dataclass(frozen=True)
class ExtractedFact:
    """A single piece of personal information pulled from a message."""

    kind: str  # "entity" | "preference"
    key: str | None  # entity key (e.g. "name"), None for preferences
    value: str


_NAME_PATTERNS = [
    re.compile(rf"\bmy name is\s+([a-z][a-z' -]{{1,40}}?){_STOP}", re.IGNORECASE),
    re.compile(rf"\byou can call me\s+([a-z][a-z' -]{{1,40}}?){_STOP}", re.IGNORECASE),
    re.compile(rf"\bcall me\s+([a-z][a-z' -]{{1,40}}?){_STOP}", re.IGNORECASE),
    re.compile(rf"\bi am called\s+([a-z][a-z' -]{{1,40}}?){_STOP}", re.IGNORECASE),
]

# "I'm X" / "I am X" is by far the most common way people actually introduce
# themselves ("i'm abdul"), but it's also how half of ordinary conversation
# starts ("i'm tired", "i'm not sure") - so this pattern is only trusted when
# the captured word isn't one of these common non-name follow-ups.
_NAME_INTRO_PATTERN = re.compile(rf"\bi(?:'m|\s+am|m)\b\s+([a-z][a-z'-]{{1,30}}?){_STOP}", re.IGNORECASE)
# Also applied to _NAME_PATTERNS matches (not just the intro pattern) - e.g.
# "call me at 9876543210" would otherwise extract "At" as a name.
_NAME_INTRO_STOPWORDS = {
    "not", "just", "still", "also", "a", "an", "the", "no", "so", "very",
    "really", "kind", "sort", "trying", "going", "looking", "wondering",
    "thinking", "feeling", "having", "working", "writing", "reading",
    "learning", "using", "testing", "building", "coding", "here", "back",
    "new", "sure", "tired", "sorry", "good", "fine", "okay", "ok", "glad",
    "happy", "sad", "mad", "upset", "angry", "afraid", "scared", "worried",
    "nervous", "curious", "interested", "excited", "ready", "done",
    "confused", "lost", "stuck", "busy", "free", "available", "online",
    "hungry", "thirsty", "bored", "gonna", "about", "at", "on", "via",
    "through", "calling",
}

# "my age is 23" is explicit and safe on its own; "I'm 23" alone is too
# ambiguous (could be a quantity, a time, anything), so that form is only
# trusted when qualified with "years old".
_AGE_PATTERNS = [
    re.compile(r"\bmy age is\s+(\d{1,3})\b", re.IGNORECASE),
    re.compile(r"\bi(?:'m|\s+am)\s+(\d{1,3})\s*(?:years?|yrs?)\s*old\b", re.IGNORECASE),
    re.compile(r"\bi(?:'m|\s+am)\s+(\d{1,3})\s*(?:years?|yrs?)\s*young\b", re.IGNORECASE),
]

_LOCATION_PATTERNS = [
    re.compile(rf"\bi live in\s+([a-z][a-z\s,'-]{{1,60}}?){_STOP}", re.IGNORECASE),
    re.compile(rf"\bi'?m from\s+([a-z][a-z\s,'-]{{1,60}}?){_STOP}", re.IGNORECASE),
    re.compile(rf"\bi am from\s+([a-z][a-z\s,'-]{{1,60}}?){_STOP}", re.IGNORECASE),
    re.compile(rf"\bi'?m based in\s+([a-z][a-z\s,'-]{{1,60}}?){_STOP}", re.IGNORECASE),
    re.compile(rf"\bmy (?:current )?location is\s+([a-z][a-z\s,'-]{{1,60}}?){_STOP}", re.IGNORECASE),
    # Unqualified "I'm in X" is too ambiguous ("I'm in trouble", "I'm in a
    # meeting") to trust as a location - only "currently" narrows it enough.
    re.compile(rf"\bi'?m currently (?:in|at)\s+([a-z][a-z\s,'-]{{1,60}}?){_STOP}", re.IGNORECASE),
]

_OCCUPATION_PATTERNS = [
    re.compile(rf"\bi work as\s+(?:an?\s+)?([a-z][a-z\s'-]{{1,60}}?){_STOP}", re.IGNORECASE),
    re.compile(rf"\bmy job is\s+([a-z][a-z\s'-]{{1,60}}?){_STOP}", re.IGNORECASE),
    re.compile(rf"\bmy profession is\s+([a-z][a-z\s'-]{{1,60}}?){_STOP}", re.IGNORECASE),
    re.compile(rf"\bi'?m a professional\s+([a-z][a-z\s'-]{{1,60}}?){_STOP}", re.IGNORECASE),
    re.compile(rf"\bi work at\s+([a-z][a-z0-9\s&'-]{{1,60}}?){_STOP}", re.IGNORECASE),
    re.compile(rf"\bi'?m an?\s+([a-z][a-z\s'-]{{1,60}}?)\s+by profession{_STOP}", re.IGNORECASE),
]

# Digits with common separators - "my number is 98765 43210", "+91-9876543210".
_PHONE_PATTERNS = [
    re.compile(r"\bmy (?:phone|mobile|cell|contact)\s*number is\s+([+\d][\d \-()]{6,18}\d)", re.IGNORECASE),
    re.compile(r"\bmy number is\s+([+\d][\d \-()]{6,18}\d)", re.IGNORECASE),
    re.compile(r"\bmy (?:phone|mobile|cell) is\s+([+\d][\d \-()]{6,18}\d)", re.IGNORECASE),
    re.compile(r"\b(?:call|reach|contact) me at\s+([+\d][\d \-()]{6,18}\d)", re.IGNORECASE),
    re.compile(r"\bmy (?:contact|phone) (?:number|no\.?) is\s+([+\d][\d \-()]{6,18}\d)", re.IGNORECASE),
]

# A plain address legitimately contains commas ("12 MG Road, Hyderabad"), so
# unlike _STOP this doesn't break at every comma - only at sentence-ending
# punctuation/conjunctions, or a comma that starts a new self-disclosure
# clause ("...Hyderabad, my gender is male" must not swallow the rest).
_ADDRESS_STOP = r"(?:[.!?;]|,\s*(?=(?:my|i)\b)|\s+(?:and|but|who|which|that)\b|$)"

# Distinct from _LOCATION_PATTERNS ("I live in Hyderabad" = city) - this is
# for a full street/postal address ("I live at 12 MG Road, ...").
_ADDRESS_PATTERNS = [
    re.compile(rf"\bmy address is\s+([a-z0-9][a-z0-9\s,.'#-]{{3,100}}?){_ADDRESS_STOP}", re.IGNORECASE),
    re.compile(rf"\bi live at\s+([a-z0-9][a-z0-9\s,.'#-]{{3,100}}?){_ADDRESS_STOP}", re.IGNORECASE),
]

# Self-terminating (the domain's own dots are part of the required shape),
# so this deliberately does NOT use _STOP - _STOP treats "." as a stop
# character, which would truncate "x@example.com" to "x@example".
_EMAIL_PATTERNS = [
    re.compile(r"\bmy email(?:\s*address)? is\s+([\w.+-]+@[\w-]+\.[\w.-]+)", re.IGNORECASE),
]

# Generic "my <field> is <value>" catch-all for profile fields that don't
# need bespoke phrasing/validation logic (unlike name/age/phone/address,
# which have their own patterns above and are deliberately excluded here to
# avoid a second, cruder match competing with them). Adding a new global
# profile field going forward is just one alias entry, not a new regex.
_GENERIC_FIELD_ALIASES = {
    "date of birth": "birthday",
    "birthday": "birthday",
    "dob": "birthday",
    "gender": "gender",
    "sex": "gender",
    "nationality": "nationality",
    "blood group": "blood_group",
    "marital status": "marital_status",
    "employer": "employer",
    "company": "employer",
}
_GENERIC_FIELD_PATTERN = re.compile(
    r"\bmy\s+("
    + "|".join(re.escape(k) for k in sorted(_GENERIC_FIELD_ALIASES, key=len, reverse=True))
    + rf")\s+is\s+([a-z0-9][a-z0-9\s,.@+'-]{{0,80}}?){_STOP}",
    re.IGNORECASE,
)


def _extract_generic_fields(text: str) -> list[ExtractedFact]:
    """Match any `_GENERIC_FIELD_ALIASES` field mentioned as "my X is Y"."""
    facts: list[ExtractedFact] = []
    for match in _GENERIC_FIELD_PATTERN.finditer(text):
        key = _GENERIC_FIELD_ALIASES.get(match.group(1).lower())
        value = match.group(2).strip().rstrip(",")
        if not key or not value:
            continue
        facts.append(ExtractedFact(kind="entity", key=key, value=value))
    return facts


_LIKE_PATTERNS = [
    (re.compile(rf"\bi (?:really )?love\s+([a-z][a-z\s'-]{{1,60}}?){_STOP}", re.IGNORECASE), "Loves"),
    (re.compile(rf"\bi (?:really )?like\s+([a-z][a-z\s'-]{{1,60}}?){_STOP}", re.IGNORECASE), "Likes"),
    (re.compile(rf"\bi enjoy\s+([a-z][a-z\s'-]{{1,60}}?){_STOP}", re.IGNORECASE), "Enjoys"),
    (re.compile(rf"\bi prefer\s+([a-z][a-z\s'-]{{1,60}}?){_STOP}", re.IGNORECASE), "Prefers"),
    (re.compile(rf"\bi hate\s+([a-z][a-z\s'-]{{1,60}}?){_STOP}", re.IGNORECASE), "Dislikes"),
    (re.compile(rf"\bi dislike\s+([a-z][a-z\s'-]{{1,60}}?){_STOP}", re.IGNORECASE), "Dislikes"),
]


def _first_match(text: str, patterns: list[re.Pattern[str]]) -> str | None:
    for pattern in patterns:
        match = pattern.search(text)
        if match:
            value = match.group(1).strip().rstrip(",")
            if value:
                return value
    return None


def extract_personal_info(text: str) -> list[ExtractedFact]:
    """Pull explicit personal-information statements out of a user message.

    Covers identity facts (name, age, city/location, phone, address,
    occupation) - these are written as global ENTITY memory, visible in
    every thread. Everything else the user says stays scoped to the
    conversation (SHORT_TERM memory, per-thread) rather than being promoted
    here.

    Deliberately conservative - only matches direct self-disclosure ("my
    name is...", "I live in...") rather than guessing from context, so it
    doesn't misfire on ordinary conversation ("I'm tired", "I'm a bit lost").
    """
    facts: list[ExtractedFact] = []

    name = _first_match(text, _NAME_PATTERNS)
    if name and name.split()[0].lower() in _NAME_INTRO_STOPWORDS:
        name = None
    if not name:
        match = _NAME_INTRO_PATTERN.search(text)
        if match:
            candidate = match.group(1).strip().rstrip(",")
            if candidate and candidate.split()[0].lower() not in _NAME_INTRO_STOPWORDS:
                name = candidate
    if name:
        facts.append(ExtractedFact(kind="entity", key="name", value=name.title()))

    age = _first_match(text, _AGE_PATTERNS)
    if age:
        facts.append(ExtractedFact(kind="entity", key="age", value=age))

    location = _first_match(text, _LOCATION_PATTERNS)
    if location:
        facts.append(ExtractedFact(kind="entity", key="location", value=location.title()))

    occupation = _first_match(text, _OCCUPATION_PATTERNS)
    if occupation:
        facts.append(ExtractedFact(kind="entity", key="occupation", value=occupation.strip()))

    phone = _first_match(text, _PHONE_PATTERNS)
    if phone:
        facts.append(ExtractedFact(kind="entity", key="phone", value=phone.strip()))

    address = _first_match(text, _ADDRESS_PATTERNS)
    if address:
        facts.append(ExtractedFact(kind="entity", key="address", value=address.strip()))

    email = _first_match(text, _EMAIL_PATTERNS)
    if email:
        facts.append(ExtractedFact(kind="entity", key="email", value=email.strip()))

    facts.extend(_extract_generic_fields(text))

    for pattern, label in _LIKE_PATTERNS:
        match = pattern.search(text)
        if match:
            value = match.group(1).strip().rstrip(",")
            if value:
                facts.append(ExtractedFact(kind="preference", key=None, value=f"{label}: {value}"))

    return facts
