"""The policy engine — retrieved policy decides whether an action needs a human.

This is the fusion of RAG + agent + HITL: `decide_refund` retrieves the relevant
policy clause, extracts the live thresholds *from the retrieved text*, and
returns a structured decision plus the clause as the citation. Because the
thresholds come from the document (not hardcoded), editing `data/policies/*.md`
and rebuilding the engine changes routing behavior with no code change.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .retriever import PolicyRetriever, build_retriever

_REFUND_QUERY = "refund greater than amount requires manager approval within days of delivery"


@dataclass(frozen=True)
class PolicyDecision:
    needs_approval: bool
    reason: str
    citation: str
    tier_hint: str = "dynamic"


def _extract_money(text: str) -> float | None:
    vals = [float(m.replace(",", "")) for m in re.findall(r"\$\s*([\d,]+(?:\.\d+)?)", text)]
    return min(vals) if vals else None


def _extract_days(text: str) -> int | None:
    vals = [int(m) for m in re.findall(r"(\d+)\s*[- ]?\s*day", text.lower())]
    return min(vals) if vals else None


def _days_since(iso: str | None, now: datetime | None = None) -> int | None:
    if not iso:
        return None
    try:
        dt = datetime.fromisoformat(iso)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    now = now or datetime.now(timezone.utc)
    return (now - dt).days


def default_policy_dir() -> Path:
    return Path(__file__).resolve().parents[3] / "data" / "policies"


class PolicyEngine:
    """Interprets retrieved policy against a concrete action."""

    # Sensible fallbacks if the policy text can't be parsed.
    DEFAULT_THRESHOLD = 50.0
    DEFAULT_WINDOW_DAYS = 30

    def __init__(self, retriever: PolicyRetriever) -> None:
        self.retriever = retriever

    def decide_refund(
        self, amount: float, delivered_at_iso: str | None = None, now: datetime | None = None
    ) -> PolicyDecision:
        hits = self.retriever.search(_REFUND_QUERY, k=5)
        refund_hits = [h for h in hits if "refund" in (h.section or "").lower()] or hits
        corpus = " ".join(h.text for h in refund_hits)

        threshold = _extract_money(corpus)
        threshold = threshold if threshold is not None else self.DEFAULT_THRESHOLD
        window = _extract_days(corpus)
        window = window if window is not None else self.DEFAULT_WINDOW_DAYS
        citation = refund_hits[0].text if refund_hits else ""

        reasons: list[str] = []
        needs = False
        if amount > threshold:
            needs = True
            reasons.append(f"${amount:.2f} exceeds the ${threshold:.0f} auto-approve limit")
        days = _days_since(delivered_at_iso, now)
        if days is not None and days > window:
            needs = True
            reasons.append(f"{days} days since delivery is outside the {window}-day window")
        if not needs:
            reasons.append(f"${amount:.2f} is within the ${threshold:.0f} limit and {window}-day window")

        return PolicyDecision(needs, "; ".join(reasons), citation)


def build_policy_engine(path: str | Path | None = None, settings=None) -> PolicyEngine:
    from ..config import settings as app_settings
    from .ingest import load_policy_dir

    chunks = load_policy_dir(path or default_policy_dir())
    return PolicyEngine(build_retriever(chunks, settings or app_settings))
