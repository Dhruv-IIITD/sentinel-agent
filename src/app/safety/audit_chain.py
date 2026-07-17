"""Deterministic hashing for the append-only audit chain."""

from __future__ import annotations

import hashlib
import json

_HASH_FIELDS = {"entry_hash", "prev_hash"}


def canonical(row: dict) -> str:
    """Serialize stored audit content without the chain-link fields."""
    content = {key: value for key, value in row.items() if key not in _HASH_FIELDS}
    return json.dumps(content, sort_keys=True, default=str, separators=(",", ":"))


def chain_hash(prev_hash: str | None, row: dict) -> str:
    """Hash one row onto its predecessor, or onto the genesis marker."""
    payload = (prev_hash or "GENESIS") + canonical(row)
    return hashlib.sha256(payload.encode()).hexdigest()
