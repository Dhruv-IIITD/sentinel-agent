"""Execute the planned tool calls — idempotently — and emit tool results.

Separated from `human_approval` precisely because that node re-executes on
resume: all outward-facing effects live here, behind the idempotency ledger, so
a resumed refund fires exactly once. Approved/modified calls execute, rejected
calls become a synthetic "declined" tool message the model can respond to.
"""

from __future__ import annotations

import json
import time

from langchain_core.messages import ToolMessage

from ...constants import RiskTier
from ...domain.ecommerce import ExecCtx
from ...safety.idempotency import idempotency_key
from ...tools.registry import REGISTRY
from ..state import AgentState


def _tool_msg(plan: dict, result: dict) -> ToolMessage:
    return ToolMessage(content=json.dumps(result, default=str), tool_call_id=plan["id"], name=plan["name"])


async def _run_tool(store, thread_id: str, spec, plan: dict, args: dict, actor: str) -> dict:
    # Guardrail: validate args before any side effect.
    try:
        validated = spec.args_schema(**args).model_dump()
    except Exception as exc:  # noqa: BLE001
        return {"error": f"invalid arguments for {spec.name}: {exc}"}

    if spec.tier == RiskTier.READ:
        started = time.perf_counter()
        result = await spec.executor(validated, store, None)
        await store.write_audit(
            thread_id=thread_id, event_type="executed", actor=actor,
            tool_name=spec.name, args=validated, result=result,
            latency_ms=int((time.perf_counter() - started) * 1000),
        )
        return result

    key = idempotency_key(thread_id, plan["id"])
    ctx = ExecCtx(thread_id=thread_id, idempotency_key=key)
    started = time.perf_counter()
    result = await spec.executor(validated, store, ctx)
    await store.write_audit(
        thread_id=thread_id, event_type="executed", actor=actor,
        tool_name=spec.name, args=validated, result=result, idempotency_key=key,
        latency_ms=int((time.perf_counter() - started) * 1000),
    )
    return result


def make_execute_tools(store):
    async def execute_tools(state: AgentState, config=None) -> dict:
        thread_id = ""
        if config and isinstance(config, dict):
            thread_id = (config.get("configurable") or {}).get("thread_id", "")
        decisions = state.get("decisions") or {}
        out: list[ToolMessage] = []

        for plan in state.get("plans") or []:
            spec = REGISTRY.get(plan["name"])
            if spec is None:
                out.append(_tool_msg(plan, {"error": f"unknown tool {plan['name']}"}))
                continue

            if plan["needs_approval"]:
                dec = decisions.get(plan["id"])
                if dec is None:
                    continue  # defensive: routing guarantees a decision before we get here
                if dec.get("decision") == "reject":
                    await store.write_audit(
                        thread_id=thread_id, event_type="rejected", actor="human",
                        tool_name=plan["name"], args=plan["args"], policy_ref=plan.get("reason"),
                    )
                    out.append(_tool_msg(plan, {
                        "status": "declined",
                        "by": dec.get("decided_by"),
                        "reason": dec.get("reason", ""),
                    }))
                    continue
                args = dec.get("modified_args") or plan["args"]
                actor = "human"
            else:
                args = plan["args"]
                actor = "agent"

            result = await _run_tool(store, thread_id, spec, plan, args, actor)
            out.append(_tool_msg(plan, result))

        # Clear turn-scoped scratch so the next turn re-classifies cleanly.
        return {"messages": out, "plans": [], "decisions": {}}

    return execute_tools
