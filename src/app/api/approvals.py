"""Approval queue + the decision endpoint that resumes the paused graph.

The decision endpoint records the human's choice, then resumes the graph with
``Command(resume=...)`` once every action in the current interrupt is decided —
so it handles both the common single-action case and multiple gated actions in
one turn. The set of actions awaiting *this* interrupt is read from the live
graph state, so we never mix in decisions from an earlier interrupt.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from langgraph.types import Command
from pydantic import BaseModel

from .chat import finalize

router = APIRouter(tags=["approvals"])

_STATUS_TO_DECISION = {"approved": "approve", "rejected": "reject", "modified": "modify"}


class DecisionRequest(BaseModel):
    decision: str  # approve | reject | modify
    modified_args: dict | None = None
    reason: str | None = None
    decided_by: str = "manager"


def _to_resume_decision(row: dict) -> dict:
    d = {"decision": _STATUS_TO_DECISION.get(row["status"], "approve"), "decided_by": row.get("decided_by")}
    if row.get("modified_args"):
        d["modified_args"] = row["modified_args"]
    if row.get("reason"):
        d["reason"] = row["reason"]
    return d


@router.get("/approvals")
async def list_approvals(request: Request, status: str = "pending") -> list[dict]:
    return await request.app.state.store.list_approvals(status=status)


@router.get("/approvals/{approval_id}")
async def get_approval(approval_id: str, request: Request) -> dict:
    row = await request.app.state.store.get_approval(approval_id)
    if row is None:
        raise HTTPException(status_code=404, detail="approval not found")
    return row


@router.get("/approvals/{approval_id}/preview")
async def preview(approval_id: str, request: Request) -> dict:
    """Outcome preview: what each decision would do — computed by dry-running the
    action against a sandbox, so nothing is mutated. Lets an approver see the
    consequence of approve vs reject before choosing."""
    store = request.app.state.store
    row = await store.get_approval(approval_id)
    if row is None:
        raise HTTPException(status_code=404, detail="approval not found")

    approve = await store.dry_run(row["tool_name"], row["tool_args"])
    return {
        "approval_id": approval_id,
        "tool": row["tool_name"],
        "args": row["tool_args"],
        "justification": row.get("policy_citation"),
        "outcomes": {
            "approve": {"executes": True, **approve},
            "reject": {
                "executes": False,
                "message": f"{row['tool_name']} would be declined; the customer is informed and no side effect runs.",
            },
        },
    }


@router.post("/approvals/{approval_id}/decision")
async def decide(approval_id: str, body: DecisionRequest, request: Request) -> dict:
    graph = request.app.state.graph
    store = request.app.state.store

    if body.decision not in ("approve", "reject", "modify"):
        raise HTTPException(status_code=422, detail="decision must be approve|reject|modify")

    row = await store.get_approval(approval_id)
    if row is None:
        raise HTTPException(status_code=404, detail="approval not found")
    if row["status"] != "pending":
        raise HTTPException(status_code=409, detail=f"approval already {row['status']}")

    await store.decide_approval(approval_id, body.decision, body.modified_args, body.reason, body.decided_by)

    thread_id = row["thread_id"]
    cfg = {"configurable": {"thread_id": thread_id}}
    state = await graph.aget_state(cfg)

    # Which tool_call_ids are awaiting THIS interrupt?
    active_ids = [item["tool_call_id"] for intr in (state.interrupts or ()) for item in intr.value]
    if not active_ids:
        return {"thread_id": thread_id, "status": "resolved", "approval": await store.get_approval(approval_id)}

    rows = await store.list_approvals(thread_id=thread_id)
    by_tcid = {r["tool_call_id"]: r for r in rows}
    if any(by_tcid.get(tid, {}).get("status", "pending") == "pending" for tid in active_ids):
        pending = await store.list_approvals(status="pending", thread_id=thread_id)
        return {"thread_id": thread_id, "status": "awaiting_more_approvals", "approvals": pending}

    resume = {tid: _to_resume_decision(by_tcid[tid]) for tid in active_ids}
    result = await graph.ainvoke(Command(resume=resume), cfg)
    return await finalize(graph, store, thread_id, cfg, result)
