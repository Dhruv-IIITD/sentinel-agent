"""Idempotency key derivation — the anchor for exactly-once side effects.

The key is derived from ``thread_id`` + the LLM ``tool_call_id``. Both are stable
across a pause/resume (they live in the persisted checkpoint), so a resumed —
or accidentally re-submitted — action maps to the *same* key and the ledger
dedupes it. A human "modify" changes the args but keeps the tool_call_id, so the
modified action still executes exactly once.
"""

from __future__ import annotations

import hashlib
import json


def idempotency_key(thread_id: str, tool_call_id: str) -> str:
    return hashlib.sha256(f"{thread_id}:{tool_call_id}".encode()).hexdigest()


def args_hash(args: dict) -> str:
    """Stable hash of tool args (audit/debug aid; not the idempotency anchor)."""
    payload = json.dumps(args, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode()).hexdigest()
