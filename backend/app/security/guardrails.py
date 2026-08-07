"""Security guardrails - prompt injection, jailbreak, content filtering.

Implements heuristic and pattern-based detection for common security
threats in LLM applications. In production these are backed by a
dedicated safety model or classifier.
"""
from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# Prompt injection patterns
# ---------------------------------------------------------------------------
_INJECTION_PATTERNS = [
    r"ignore\s+(all\s+)?(previous|prior|above)\s+(instructions|prompts|context)",
    r"disregard\s+(all\s+)?(earlier|previous)\s+(instructions|instructions)",
    r"you\s+are\s+now\s+(an?\s+)?\w+\s+without\s+(any\s+)?(rules|restrictions|limits)",
    r"forget\s+(everything|all)\s+(you|the system)\s+(know|learned)",
    r"reveal\s+(your\s+)?(system\s+)?prompt",
    r"act\s+as\s+(your\s+)?(developer|creator|programmer)",
    r"do\s+not\s+follow\s+your\s+(original|system)\s+instructions",
    r"override\s+(your\s+)?(system|previous)\s+instructions",
    r"what\s+are\s+your\s+(system|hidden)\s+instructions",
    r"print\s+(all\s+)?(your\s+)?(hidden|system)\s+prompt",
]

# ---------------------------------------------------------------------------
# Jailbreak patterns
# ---------------------------------------------------------------------------
_JAILBREAK_PATTERNS = [
    r"(?i)DAN\b",
    r"jailbreak\b",
    r"(?i)developer\s+mode",
    r"(?i)do\s+anything\s+now",
    r"(?i)unfiltered\s+mode",
    r"(?i)no\s+(rules|restrictions|filter)",
    r"(?i)bypass\s+(the\s+)?(filter|safety|guidelines)",
    r"(?i)evil\s+(mode|gpt|ersona)",
    r"(?i)opposite\s+persona",
    r"(?i)access\s+the\s+internet\s+to\s+search",
]

# ---------------------------------------------------------------------------
# Content filtering patterns (hate, violence, etc.)
# ---------------------------------------------------------------------------
_CONTENT_FILTER_PATTERNS = [
    r"\b(kill|murder|assassinate)\s+(him|her|them|people|a|the)\b",
    r"\b(torture|bomb|explosive)\b",
    r"\b(rape|child\s+abuse)\b",
    r"\b(how\s+to\s+(make|build|create)\s+(a\s+)?(bomb|weapon|explosive))\b",
]

# Compiled regexes
_INJECTION_RE = [re.compile(p, re.IGNORECASE) for p in _INJECTION_PATTERNS]
_JAILBREAK_RE = [re.compile(p, re.IGNORECASE) for p in _JAILBREAK_PATTERNS]
_CONTENT_RE = [re.compile(p, re.IGNORECASE) for p in _CONTENT_FILTER_PATTERNS]


def detect_prompt_injection(text: str) -> bool:
    """Detect if text contains prompt injection attempts."""
    return any(pattern.search(text) for pattern in _INJECTION_RE)


def contains_jailbreak_pattern(text: str) -> bool:
    """Detect if text contains jailbreak patterns."""
    return any(pattern.search(text) for pattern in _JAILBREAK_RE)


def is_content_filtered(text: str) -> bool:
    """Check if text requires content filtering."""
    return any(pattern.search(text) for pattern in _CONTENT_RE)


def sanitize_input(text: str, max_length: int = 10000) -> str:
    """Sanitize user input - strip control characters and limit length."""
    # Remove zero-width and control characters
    cleaned = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text)
    return cleaned[:max_length]
