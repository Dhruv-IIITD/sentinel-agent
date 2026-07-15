"""Guardrails: PII redaction for logs/traces.

Redaction is applied at the audit boundary so the stored record never contains
raw PII, while the live tool result the model sees is untouched. Patterns are
conservative (high-value, low false-positive) — emails, card-like digit runs,
and formatted phone numbers — so order ids and money amounts are not clobbered.
"""

from __future__ import annotations

import re

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_CARD = re.compile(r"\b(?:\d[ -]?){13,16}\b")
_PHONE = re.compile(r"\b(?:\+\d{1,3}[\s-]?)?(?:\(\d{3}\)|\d{3})[\s-]\d{3}[\s-]\d{4}\b")


def redact_text(s: str) -> str:
    s = _EMAIL.sub("[redacted-email]", s)
    s = _CARD.sub("[redacted-card]", s)
    s = _PHONE.sub("[redacted-phone]", s)
    return s


def redact(obj):
    """Recursively redact PII in strings within dicts/lists/strings."""
    if isinstance(obj, str):
        return redact_text(obj)
    if isinstance(obj, dict):
        return {k: redact(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [redact(v) for v in obj]
    return obj


# Phrases commonly seen in prompt-injection / social-engineering attempts.
_INJECTION_PATTERNS = [
    re.compile(p, re.IGNORECASE)
    for p in (
        r"ignore\b[\w\s]{0,25}\b(instructions|rules|policy)",
        r"disregard\b[\w\s]{0,25}\b(policy|instructions|rules)",
        r"\bsystem\s*:",
        r"admin override",
        r"\btest mode\b",
        r"(auto[- ]?approv|pre[- ]?approv)",
        r"no approval (is )?needed",
        r"bypass (all )?(checks|approval|review)",
        r"skip (the )?(human )?(review|approval)",
        r"you are (now )?(an? )?(admin|developer|authorized)",
    )
]


def looks_like_injection(text: str) -> bool:
    """Heuristic detector for manipulation attempts in user input.

    Defense-in-depth only: the *structural* defense is that policy + hard-cap
    routing gates high-stakes actions regardless of what the message says. This
    can additionally force escalation when triggered.
    """
    return any(p.search(text or "") for p in _INJECTION_PATTERNS)
