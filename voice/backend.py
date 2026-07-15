"""Thin async HTTP client for the backend's voice RPC surface.

Pattern A (see docs/VOICE_PLAN.md): the voice worker keeps the conversational
loop fast and calls the backend for facts. Reads are plain HTTP — nothing here
runs the LangGraph graph, which is what keeps it out of the latency hot path.
"""

from __future__ import annotations

import httpx


class Backend:
    def __init__(self, base_url: str, timeout: float = 5.0) -> None:
        self._client = httpx.AsyncClient(base_url=base_url.rstrip("/"), timeout=timeout)

    async def aclose(self) -> None:
        await self._client.aclose()

    # Every order-scoped call carries the thread_id: the backend enforces the identity
    # gate itself (see api/voice.py::_require_verified), so these will 403 if the caller
    # on this thread never proved they own the order — even if the agent forgets to check.

    async def verify_identity(self, thread_id: str, order_id: int, email_or_name: str) -> dict:
        r = await self._client.post(
            "/voice/verify_identity",
            json={"thread_id": thread_id, "order_id": order_id, "email_or_name": email_or_name},
        )
        r.raise_for_status()
        return r.json()

    async def get_order(self, thread_id: str, order_id: int) -> dict:
        r = await self._client.get(f"/voice/order/{order_id}", params={"thread_id": thread_id})
        r.raise_for_status()
        return r.json()

    async def track_shipment(self, thread_id: str, order_id: int) -> dict:
        r = await self._client.get(f"/voice/shipment/{order_id}", params={"thread_id": thread_id})
        r.raise_for_status()
        return r.json()

    async def refund_eligibility(
        self, thread_id: str, order_id: int, amount: float | None = None
    ) -> dict:
        params: dict = {"thread_id": thread_id}
        if amount is not None:
            params["amount"] = amount
        r = await self._client.get(f"/voice/refund_eligibility/{order_id}", params=params)
        r.raise_for_status()
        return r.json()

    async def search_policy(self, q: str, k: int = 2) -> dict:
        r = await self._client.get("/voice/policy", params={"q": q, "k": k})
        r.raise_for_status()
        return r.json()

    # --- actions (these go through the LangGraph risk gate) ---

    async def request_action(self, thread_id: str, tool: str, args: dict) -> dict:
        r = await self._client.post(
            "/voice/action",
            json={"thread_id": thread_id, "tool": tool, "args": args},
        )
        r.raise_for_status()
        return r.json()

    async def action_status(self, approval_id: str) -> dict:
        r = await self._client.get(f"/voice/action/{approval_id}")
        r.raise_for_status()
        return r.json()

    # --- the approval call (a human decides, by voice) ---

    async def get_approval(self, approval_id: str) -> dict | None:
        r = await self._client.get(f"/approvals/{approval_id}")
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return r.json()

    async def submit_decision(
        self, approval_id: str, decision: str, reason: str = "", decided_by: str = "phone-approver"
    ) -> dict:
        r = await self._client.post(
            f"/approvals/{approval_id}/decision",
            json={"decision": decision, "reason": reason, "decided_by": decided_by},
        )
        r.raise_for_status()
        return r.json()
