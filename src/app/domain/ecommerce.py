"""The domain Store — business operations, the idempotency ledger, and audit.

Two interchangeable implementations behind one `Store` protocol:

* `MemoryStore` — in-process dicts, seeded with the demo data. Lets the whole
  agent graph run and be tested without a database (dev/CI). It is the *tested
  reference implementation* of the exactly-once semantics.
* `PostgresStore` — SQLAlchemy-backed, for production. Effect + ledger insert
  happen in a single transaction so a side effect and its idempotency record
  commit atomically.

Every mutating method takes an `ExecCtx` carrying the idempotency key; a repeated
key returns the stored result (flagged ``idempotent_replay``) instead of running
the effect again.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Protocol, runtime_checkable

from ..payments import MockPaymentProvider, PaymentProvider, build_payment_provider
from ..safety.idempotency import args_hash

# Maps a human's decision verb to the stored approval status.
_DECISION_TO_STATUS = {"approve": "approved", "reject": "rejected", "modify": "modified"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class ExecCtx:
    """Execution context threaded into a mutation: who/where + the dedupe key."""

    thread_id: str
    idempotency_key: str | None = None


@runtime_checkable
class Store(Protocol):
    # --- reads (no side effects) ---
    async def get_order(self, order_id: int) -> dict: ...
    async def check_inventory(self, sku: str) -> dict: ...
    async def track_shipment(self, order_id: int) -> dict: ...

    # --- catalog: see & create the data the agent operates on ---
    # Without these the store is an invisible fixture; with them it is an operations
    # system you can look at and add to (e.g. register yourself, then call in).
    async def list_customers(self) -> list[dict]: ...
    async def list_orders(self) -> list[dict]: ...
    async def get_customer_360(self, order_id: int) -> dict: ...
    async def list_products(self) -> list[dict]: ...
    async def get_product(self, product_id: int) -> dict | None: ...
    async def create_product(
        self, sku: str, name: str, price: float, description: str = "", emoji: str = "",
    ) -> dict: ...
    async def get_customer_by_email(self, email: str) -> dict | None: ...
    async def create_customer(self, name: str, email: str) -> dict: ...
    async def create_order(
        self, customer_id: int, item_description: str, amount: float,
        status: str = "delivered", delivered_at: str | None = None,
        product_id: int | None = None,
    ) -> dict: ...

    # --- mutations (exactly-once via ctx) ---
    async def update_address(self, order_id: int, new_address: str, ctx: ExecCtx | None) -> dict: ...
    async def add_note(self, order_id: int, note: str, author: str, ctx: ExecCtx | None) -> dict: ...
    async def issue_refund(self, order_id: int, amount: float, reason: str, ctx: ExecCtx | None) -> dict: ...
    async def cancel_order(self, order_id: int, reason: str, ctx: ExecCtx | None) -> dict: ...
    async def apply_credit(self, customer_id: int, amount: float, reason: str, ctx: ExecCtx | None) -> dict: ...

    # --- audit ---
    async def write_audit(self, **fields) -> None: ...
    async def list_audit(self, thread_id: str | None = None, limit: int = 100) -> list[dict]: ...
    async def verify_audit_chain(self) -> dict: ...

    # --- compensation / rollback ---
    async def compensate(self, idempotency_key: str, actor: str = "human", reason: str = "") -> dict: ...

    # --- dry-run (outcome preview, no side effects) ---
    async def dry_run(self, tool_name: str, args: dict) -> dict: ...

    # --- approval queue (what the dashboard reads) ---
    async def create_approvals(self, thread_id: str, checkpoint_id: str | None, items: list[dict]) -> list[dict]: ...
    async def list_approvals(self, status: str | None = None, thread_id: str | None = None) -> list[dict]: ...
    async def get_approval(self, approval_id: str) -> dict | None: ...
    async def decide_approval(self, approval_id: str, decision: str, modified_args: dict | None,
                              reason: str | None, decided_by: str | None) -> dict | None: ...
    async def mark_escalated(
        self, approval_id: str, at: datetime | None = None,
    ) -> dict | None: ...


# ---------------------------------------------------------------------------
# In-memory implementation (dev / tests)
# ---------------------------------------------------------------------------


class MemoryStore:
    """Dict-backed Store, seeded with the DESIGN.md demo data."""

    def __init__(
        self, seed: bool = True, payments: PaymentProvider | None = None,
    ) -> None:
        self.payments = payments or MockPaymentProvider()
        self.customers: dict[int, dict] = {}
        self.products: dict[int, dict] = {}
        self.orders: dict[int, dict] = {}
        self.refunds: list[dict] = []
        self.credits: list[dict] = []
        self.notes: list[dict] = []
        self.executions: dict[str, dict] = {}  # idempotency ledger
        self._external_locks: dict[str, asyncio.Lock] = {}
        self.audit: list[dict] = []
        self._last_audit_hash: str | None = None
        self.approvals: dict[str, dict] = {}
        if seed:
            self._seed()

    def _seed(self) -> None:
        now = datetime.now(timezone.utc)
        self.customers = {
            1: {"id": 1, "name": "Alice Rivera", "email": "alice@example.com"},
            2: {"id": 2, "name": "Bob Chen", "email": "bob@example.com"},
        }
        self.products = {
            1: {
                "id": 1, "sku": "CERAMIC-DINNER-SET", "name": "Ceramic dinner set",
                "price": 180.0, "active": True, "description": "", "emoji": "🍽️",
            },
            2: {
                "id": 2, "sku": "BLUETOOTH-SPEAKER", "name": "Bluetooth speaker",
                "price": 39.99, "active": True, "description": "", "emoji": "🔊",
            },
            3: {
                "id": 3, "sku": "STANDING-DESK", "name": "Standing desk",
                "price": 640.0, "active": True, "description": "", "emoji": "🪑",
            },
        }
        self.orders = {
            4471: {
                "id": 4471, "customer_id": 1, "product_id": 1,
                "amount": 180.0, "status": "delivered",
                "item_description": "Ceramic dinner set",
                "shipping_address": "12 Oak St, Portland OR",
                "payment_ref": "mock_pi_4471",
                "delivered_at": (now - timedelta(days=3)).isoformat(),
            },
            4472: {
                "id": 4472, "customer_id": 2, "product_id": 2,
                "amount": 39.99, "status": "delivered",
                "item_description": "Bluetooth speaker",
                "shipping_address": "5 Pine Ave, Austin TX",
                "payment_ref": "mock_pi_4472",
                "delivered_at": (now - timedelta(days=10)).isoformat(),
            },
            4473: {
                "id": 4473, "customer_id": 1, "product_id": 3,
                "amount": 640.0, "status": "in_transit",
                "item_description": "Standing desk",
                "shipping_address": "12 Oak St, Portland OR",
                "payment_ref": "mock_pi_4473",
                "delivered_at": None,
            },
        }

    # ---- idempotency helper ----
    def _once(self, ctx: ExecCtx | None, tool_name: str, args: dict, make) -> dict:
        key = ctx.idempotency_key if ctx else None
        if key is not None and key in self.executions:
            return {**self.executions[key]["result"], "idempotent_replay": True}
        result = make()
        if key is not None and "error" not in result:
            self.executions[key] = {
                "tool_name": tool_name, "args": args, "result": result,
                "compensated": False, "thread_id": ctx.thread_id if ctx else "",
            }
        return result

    async def _once_external(self, ctx: ExecCtx | None, tool_name: str, args: dict, make) -> dict:
        """Keep an awaited provider call behind the same keyed ledger check."""
        key = ctx.idempotency_key if ctx else None
        if key is None:
            return await make()
        lock = self._external_locks.setdefault(key, asyncio.Lock())
        async with lock:
            if key in self.executions:
                return {**self.executions[key]["result"], "idempotent_replay": True}
            result = await make()
            if "error" not in result:
                self.executions[key] = {
                    "tool_name": tool_name, "args": args, "result": result,
                    "compensated": False, "thread_id": ctx.thread_id,
                }
            return result

    # ---- reads ----
    async def get_order(self, order_id: int) -> dict:
        o = self.orders.get(order_id)
        if not o:
            return {"error": f"order {order_id} not found"}
        cust = self.customers.get(o["customer_id"], {})
        return {**o, "customer_name": cust.get("name"), "customer_email": cust.get("email")}

    async def check_inventory(self, sku: str) -> dict:
        return {"sku": sku, "in_stock": 42, "warehouse": "PDX-1"}

    async def track_shipment(self, order_id: int) -> dict:
        o = self.orders.get(order_id)
        if not o:
            return {"error": f"order {order_id} not found"}
        status = "delivered" if o["status"] == "delivered" else "in_transit"
        return {"order_id": order_id, "status": status, "carrier": "UPS"}

    # ---- catalog ----
    def _order_with_customer(self, o: dict) -> dict:
        c = self.customers.get(o["customer_id"], {})
        return {**o, "customer_name": c.get("name"), "customer_email": c.get("email")}

    async def list_customers(self) -> list[dict]:
        return [dict(c) for c in sorted(self.customers.values(), key=lambda c: c["id"])]

    async def list_orders(self) -> list[dict]:
        return [self._order_with_customer(o) for o in sorted(self.orders.values(), key=lambda o: o["id"])]

    async def get_customer_360(self, order_id: int) -> dict:
        order = self.orders.get(order_id)
        if order is None:
            return {"error": f"order {order_id} not found"}

        customer_id = order["customer_id"]
        customer_orders = sorted(
            (o for o in self.orders.values() if o["customer_id"] == customer_id),
            key=lambda o: o["id"],
        )
        order_ids = {o["id"] for o in customer_orders}
        customer = self.customers[customer_id]
        return {
            "customer": {
                "id": customer["id"], "name": customer["name"], "email": customer["email"],
            },
            "orders": [
                {
                    "id": o["id"], "item_description": o["item_description"],
                    "amount": o["amount"], "status": o["status"],
                    "delivered_at": o.get("delivered_at"),
                }
                for o in customer_orders
            ],
            "refunds": [
                {
                    "order_id": refund["order_id"], "amount": refund["amount"],
                    "status": refund["status"], "reason": refund["reason"],
                    "provider": refund.get("provider"),
                }
                for refund in self.refunds
                if refund["order_id"] in order_ids
            ],
            "notes": [
                {
                    "order_id": note["order_id"], "note": note["note"],
                    "author": note["author"],
                }
                for note in self.notes
                if note["order_id"] in order_ids
            ],
        }

    async def list_products(self) -> list[dict]:
        return [dict(p) for p in sorted(self.products.values(), key=lambda p: p["id"])]

    async def get_product(self, product_id: int) -> dict | None:
        product = self.products.get(product_id)
        return dict(product) if product is not None else None

    async def create_product(self, sku, name, price, description="", emoji="") -> dict:
        if any(p["sku"] == sku for p in self.products.values()):
            return {"error": f"product SKU {sku} already exists"}
        pid = max(self.products, default=0) + 1
        row = {
            "id": pid, "sku": sku, "name": name, "price": float(price),
            "active": True, "description": description, "emoji": emoji,
        }
        self.products[pid] = row
        return dict(row)

    async def get_customer_by_email(self, email: str) -> dict | None:
        e = (email or "").strip().lower()
        return next((dict(c) for c in self.customers.values() if c["email"].lower() == e), None)

    async def create_customer(self, name: str, email: str) -> dict:
        existing = await self.get_customer_by_email(email)
        if existing:  # email is the identity — reuse rather than duplicate
            return existing
        cid = max(self.customers, default=0) + 1
        row = {"id": cid, "name": name, "email": email}
        self.customers[cid] = row
        return dict(row)

    async def create_order(
        self, customer_id, item_description, amount, status="delivered", delivered_at=None,
        product_id=None,
    ) -> dict:
        if product_id is not None:
            product = self.products.get(product_id)
            if product is None:
                return {"error": f"product {product_id} not found"}
            item_description = product["name"]
            amount = product["price"]
        oid = max(self.orders, default=4470) + 1
        payment = await self.payments.create_payment(
            order_id=oid, amount=float(amount), description=item_description,
        )
        row = {
            "id": oid, "customer_id": customer_id, "product_id": product_id,
            "amount": float(amount),
            "status": status, "item_description": item_description,
            "shipping_address": "", "payment_ref": payment.get("payment_ref"),
            "delivered_at": delivered_at,
        }
        self.orders[oid] = row
        return self._order_with_customer(row)

    # ---- mutations ----
    async def update_address(self, order_id, new_address, ctx=None) -> dict:
        def make():
            o = self.orders.get(order_id)
            if not o:
                return {"error": f"order {order_id} not found"}
            o["shipping_address"] = new_address
            return {"order_id": order_id, "shipping_address": new_address, "updated": True}

        return self._once(ctx, "update_address", {"order_id": order_id, "new_address": new_address}, make)

    async def add_note(self, order_id, note, author, ctx=None) -> dict:
        def make():
            self.notes.append({"order_id": order_id, "note": note, "author": author})
            return {"order_id": order_id, "note_added": True}

        return self._once(ctx, "add_note", {"order_id": order_id, "note": note}, make)

    async def issue_refund(self, order_id, amount, reason, ctx=None) -> dict:
        async def make():
            o = self.orders.get(order_id)
            if not o:
                return {"error": f"order {order_id} not found"}
            provider_refund = await self.payments.refund(
                payment_ref=o.get("payment_ref"),
                amount=amount,
                idempotency_key=ctx.idempotency_key if ctx else None,
                reason=reason,
            )
            if "error" in provider_refund:
                return provider_refund
            rid = len(self.refunds) + 1
            provider = provider_refund.get("provider")
            provider_refund_id = provider_refund.get("refund_id")
            status = provider_refund.get("status", "issued")
            self.refunds.append(
                {"id": rid, "order_id": order_id, "amount": amount, "reason": reason,
                 "status": status, "idempotency_key": ctx.idempotency_key if ctx else None,
                 "provider": provider, "provider_refund_id": provider_refund_id}
            )
            return {
                "refund_id": rid, "order_id": order_id, "amount": amount, "status": status,
                "provider": provider, "provider_refund_id": provider_refund_id,
            }

        return await self._once_external(
            ctx, "issue_refund", {"order_id": order_id, "amount": amount}, make
        )

    async def cancel_order(self, order_id, reason, ctx=None) -> dict:
        def make():
            o = self.orders.get(order_id)
            if not o:
                return {"error": f"order {order_id} not found"}
            o["status"] = "cancelled"
            return {"order_id": order_id, "status": "cancelled", "reason": reason}

        return self._once(ctx, "cancel_order", {"order_id": order_id}, make)

    async def apply_credit(self, customer_id, amount, reason, ctx=None) -> dict:
        def make():
            cid = len(self.credits) + 1
            self.credits.append(
                {"id": cid, "customer_id": customer_id, "amount": amount, "reason": reason, "status": "applied"}
            )
            return {"credit_id": cid, "customer_id": customer_id, "amount": amount, "status": "applied"}

        return self._once(ctx, "apply_credit", {"customer_id": customer_id, "amount": amount}, make)

    async def write_audit(self, **fields) -> None:
        from ..safety.audit_chain import chain_hash
        from ..safety.guardrails import redact

        for key in ("args", "result"):
            if fields.get(key) is not None:
                fields[key] = redact(fields[key])
        row = dict(fields)
        row.setdefault("id", len(self.audit) + 1)
        row.setdefault("created_at", _now_iso())
        row["prev_hash"] = self._last_audit_hash
        row["entry_hash"] = chain_hash(self._last_audit_hash, row)
        self.audit.append(row)
        self._last_audit_hash = row["entry_hash"]

    async def list_audit(self, thread_id=None, limit=100) -> list[dict]:
        rows = self.audit if thread_id is None else [a for a in self.audit if a.get("thread_id") == thread_id]
        return list(rows[-limit:])

    async def verify_audit_chain(self) -> dict:
        from ..safety.audit_chain import chain_hash

        running_hash = None
        for index, row in enumerate(self.audit):
            expected = chain_hash(running_hash, row)
            if row.get("prev_hash") != running_hash or row.get("entry_hash") != expected:
                return {"intact": False, "entries": len(self.audit), "broken_at": index}
            running_hash = row["entry_hash"]
        return {"intact": True, "entries": len(self.audit), "broken_at": None}

    # ---- compensation / rollback ----
    async def compensate(self, idempotency_key, actor="human", reason="") -> dict:
        meta = self.executions.get(idempotency_key)
        if meta is None:
            return {"error": "no execution found for that idempotency key"}
        if meta["compensated"]:
            return {"status": "already_compensated", "idempotency_key": idempotency_key}

        tool = meta["tool_name"]
        undo = {"status": "compensated", "tool_name": tool}
        if tool == "issue_refund":
            # Stripe refunds are terminal; compensation records an internal reversal only.
            for r in self.refunds:
                if r.get("idempotency_key") == idempotency_key:
                    r["status"] = "reversed"
                    undo["reversed_refund_id"] = r["id"]
                    undo["amount"] = r["amount"]
                    if r.get("provider") == "stripe":
                        undo["note"] = (
                            "Stripe refunds are terminal; no external re-charge was issued."
                        )
        elif tool == "cancel_order":
            oid = meta["args"].get("order_id")
            o = self.orders.get(oid)
            if o:
                o["status"] = "active"
                undo["reinstated_order"] = oid
        elif tool == "apply_credit":
            cid = meta["result"].get("credit_id")
            for c in self.credits:
                if c.get("id") == cid:
                    c["status"] = "reversed"
                    undo["reversed_credit_id"] = cid
        else:
            return {"error": f"{tool} is not compensable"}

        meta["compensated"] = True
        await self.write_audit(
            thread_id=meta["thread_id"], event_type="compensated", actor=actor,
            tool_name=tool, args=meta["args"], result=undo,
            idempotency_key=idempotency_key, policy_ref=reason,
        )
        return undo

    # ---- approval queue ----
    async def create_approvals(self, thread_id, checkpoint_id, items) -> list[dict]:
        pending_tcids = {
            a["tool_call_id"] for a in self.approvals.values()
            if a["thread_id"] == thread_id and a["status"] == "pending"
        }
        created = []
        for item in items:
            if item["tool_call_id"] in pending_tcids:  # dedupe re-submits
                continue
            aid = uuid.uuid4().hex
            row = {
                "id": aid, "thread_id": thread_id, "checkpoint_id": checkpoint_id,
                "tool_call_id": item["tool_call_id"], "tool_name": item["tool"],
                "tool_args": item.get("args", {}), "risk_tier": item.get("risk_tier"),
                "policy_citation": item.get("justification"),
                "status": "pending", "modified_args": None, "reason": None,
                "decided_by": None, "decided_at": None, "escalated_at": None,
                "created_at": _now_iso(),
            }
            self.approvals[aid] = row
            created.append(row)
        return created

    async def list_approvals(self, status=None, thread_id=None) -> list[dict]:
        rows = list(self.approvals.values())
        if status is not None:
            rows = [r for r in rows if r["status"] == status]
        if thread_id is not None:
            rows = [r for r in rows if r["thread_id"] == thread_id]
        return sorted(rows, key=lambda r: r["created_at"])

    async def get_approval(self, approval_id) -> dict | None:
        return self.approvals.get(approval_id)

    async def decide_approval(self, approval_id, decision, modified_args, reason, decided_by) -> dict | None:
        row = self.approvals.get(approval_id)
        if row is None:
            return None
        row["status"] = _DECISION_TO_STATUS.get(decision, "approved")
        row["modified_args"] = modified_args
        row["reason"] = reason
        row["decided_by"] = decided_by
        row["decided_at"] = _now_iso()
        return row

    async def mark_escalated(self, approval_id, at=None) -> dict | None:
        row = self.approvals.get(approval_id)
        if row is None or row["status"] != "pending" or row.get("escalated_at") is not None:
            return None
        row["escalated_at"] = (at or datetime.now(timezone.utc)).isoformat()
        return row

    # ---- dry-run (execute against a throwaway clone) ----
    async def dry_run(self, tool_name, args) -> dict:
        import copy

        from ..tools.registry import REGISTRY

        spec = REGISTRY.get(tool_name)
        if spec is None:
            return {"error": f"unknown tool {tool_name}"}

        sandbox = MemoryStore(seed=False)
        sandbox.customers = copy.deepcopy(self.customers)
        sandbox.products = copy.deepcopy(self.products)
        sandbox.orders = copy.deepcopy(self.orders)
        sandbox.refunds = copy.deepcopy(self.refunds)
        sandbox.credits = copy.deepcopy(self.credits)
        sandbox.notes = copy.deepcopy(self.notes)

        before = {"refunds": len(sandbox.refunds), "credits": len(sandbox.credits), "notes": len(sandbox.notes)}
        try:
            result = await spec.executor(args, sandbox, None)  # ctx=None -> no ledger, sandbox only
        except Exception as exc:  # noqa: BLE001
            return {"error": f"dry-run failed: {exc}"}
        after = {"refunds": len(sandbox.refunds), "credits": len(sandbox.credits), "notes": len(sandbox.notes)}
        effects = {k: {"before": before[k], "after": after[k]} for k in before if before[k] != after[k]}
        return {"result": result, "effects": effects, "simulated": True}

    def clone(self) -> "MemoryStore":
        """A deep-copied sandbox — used for counterfactual branches / dry-runs."""
        import copy

        c = MemoryStore(seed=False)
        c.customers = copy.deepcopy(self.customers)
        c.products = copy.deepcopy(self.products)
        c.orders = copy.deepcopy(self.orders)
        c.refunds = copy.deepcopy(self.refunds)
        c.credits = copy.deepcopy(self.credits)
        c.notes = copy.deepcopy(self.notes)
        return c

    # ---- test/inspection helpers ----
    def refund_count(self) -> int:
        return len(self.refunds)


# ---------------------------------------------------------------------------
# Postgres implementation (production)
# ---------------------------------------------------------------------------


class PostgresStore:
    """SQLAlchemy-backed Store. Effect + idempotency-ledger insert are one tx."""

    def __init__(self, payments: PaymentProvider | None = None) -> None:
        self.payments = payments or MockPaymentProvider()

    async def _once(self, ctx: ExecCtx | None, tool_name: str, args_for_hash: dict, effect) -> dict:
        """Run ``effect(session)`` at most once per idempotency key, atomically."""
        from sqlalchemy import text
        from sqlalchemy.exc import IntegrityError

        from ..db.models import ToolExecution
        from ..db.session import session_scope

        key = ctx.idempotency_key if ctx else None
        try:
            async with session_scope() as s:
                if key is not None:
                    # Serialize the ledger check + external effect across API workers.
                    await s.execute(
                        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
                        {"key": key},
                    )
                    existing = await s.get(ToolExecution, key)
                    if existing is not None:
                        return {**(existing.result or {}), "idempotent_replay": True}
                result = await effect(s)
                if key is not None and "error" not in result:
                    s.add(ToolExecution(
                        idempotency_key=key,
                        thread_id=ctx.thread_id if ctx else "",
                        tool_name=tool_name,
                        args_hash=args_hash(args_for_hash),
                        result=result,
                    ))
                return result
        except IntegrityError:
            # A concurrent execution won the race on the same key — return its result.
            from ..db.session import session_scope as _scope

            async with _scope() as s:
                existing = await s.get(ToolExecution, key)  # type: ignore[arg-type]
                if existing is not None:
                    return {**(existing.result or {}), "idempotent_replay": True}
                raise

    async def get_order(self, order_id: int) -> dict:
        from ..db.models import Customer, Order
        from ..db.session import session_scope

        async with session_scope() as s:
            o = await s.get(Order, order_id)
            if o is None:
                return {"error": f"order {order_id} not found"}
            cust = await s.get(Customer, o.customer_id)
            return {
                "id": o.id, "customer_id": o.customer_id, "product_id": o.product_id,
                "amount": float(o.amount),
                "status": o.status, "item_description": o.item_description,
                "shipping_address": o.shipping_address, "payment_ref": o.payment_ref,
                "delivered_at": o.delivered_at.isoformat() if o.delivered_at else None,
                "customer_name": cust.name if cust else None,
                "customer_email": cust.email if cust else None,
            }

    async def check_inventory(self, sku: str) -> dict:
        return {"sku": sku, "in_stock": 42, "warehouse": "PDX-1"}

    async def track_shipment(self, order_id: int) -> dict:
        from ..db.models import Order
        from ..db.session import session_scope

        async with session_scope() as s:
            o = await s.get(Order, order_id)
            if o is None:
                return {"error": f"order {order_id} not found"}
            status = "delivered" if o.status == "delivered" else "in_transit"
            return {"order_id": order_id, "status": status, "carrier": "UPS"}

    # ---- catalog ----
    @staticmethod
    def _order_dict(o, cust) -> dict:
        return {
            "id": o.id, "customer_id": o.customer_id, "product_id": o.product_id,
            "amount": float(o.amount),
            "status": o.status, "item_description": o.item_description,
            "shipping_address": o.shipping_address, "payment_ref": o.payment_ref,
            "delivered_at": o.delivered_at.isoformat() if o.delivered_at else None,
            "customer_name": cust.name if cust else None,
            "customer_email": cust.email if cust else None,
        }

    async def list_customers(self) -> list[dict]:
        from sqlalchemy import select

        from ..db.models import Customer
        from ..db.session import session_scope

        async with session_scope() as s:
            rows = (await s.scalars(select(Customer).order_by(Customer.id))).all()
            return [{"id": r.id, "name": r.name, "email": r.email} for r in rows]

    async def list_orders(self) -> list[dict]:
        from sqlalchemy import select
        from sqlalchemy.orm import joinedload

        from ..db.models import Order
        from ..db.session import session_scope

        async with session_scope() as s:
            rows = (await s.scalars(
                select(Order).options(joinedload(Order.customer)).order_by(Order.id)
            )).all()
            return [self._order_dict(o, o.customer) for o in rows]

    async def get_customer_360(self, order_id: int) -> dict:
        from sqlalchemy import select

        from ..db.models import Customer, Order, OrderNote, Refund
        from ..db.session import session_scope

        async with session_scope() as s:
            order = await s.get(Order, order_id)
            if order is None:
                return {"error": f"order {order_id} not found"}

            customer = await s.get(Customer, order.customer_id)
            orders = (await s.scalars(
                select(Order).where(Order.customer_id == order.customer_id).order_by(Order.id)
            )).all()
            refunds = (await s.scalars(
                select(Refund)
                .join(Order, Refund.order_id == Order.id)
                .where(Order.customer_id == order.customer_id)
                .order_by(Refund.id)
            )).all()
            notes = (await s.scalars(
                select(OrderNote)
                .join(Order, OrderNote.order_id == Order.id)
                .where(Order.customer_id == order.customer_id)
                .order_by(OrderNote.id)
            )).all()
            return {
                "customer": {
                    "id": customer.id, "name": customer.name, "email": customer.email,
                },
                "orders": [
                    {
                        "id": o.id, "item_description": o.item_description,
                        "amount": float(o.amount), "status": o.status,
                        "delivered_at": o.delivered_at.isoformat() if o.delivered_at else None,
                    }
                    for o in orders
                ],
                "refunds": [
                    {
                        "order_id": refund.order_id, "amount": float(refund.amount),
                        "status": refund.status, "reason": refund.reason,
                        "provider": refund.provider,
                    }
                    for refund in refunds
                ],
                "notes": [
                    {
                        "order_id": note.order_id, "note": note.note, "author": note.author,
                    }
                    for note in notes
                ],
            }

    @staticmethod
    def _product_dict(product) -> dict:
        return {
            "id": product.id, "sku": product.sku, "name": product.name,
            "price": float(product.price), "active": product.active,
            "description": product.description, "emoji": product.emoji,
        }

    async def list_products(self) -> list[dict]:
        from sqlalchemy import select

        from ..db.models import Product
        from ..db.session import session_scope

        async with session_scope() as s:
            rows = (await s.scalars(select(Product).order_by(Product.id))).all()
            return [self._product_dict(product) for product in rows]

    async def get_product(self, product_id: int) -> dict | None:
        from ..db.models import Product
        from ..db.session import session_scope

        async with session_scope() as s:
            product = await s.get(Product, product_id)
            return self._product_dict(product) if product is not None else None

    async def create_product(self, sku, name, price, description="", emoji="") -> dict:
        from decimal import Decimal

        from sqlalchemy import select

        from ..db.models import Product
        from ..db.session import session_scope

        async with session_scope() as s:
            existing = (await s.scalars(select(Product).where(Product.sku == sku))).first()
            if existing is not None:
                return {"error": f"product SKU {sku} already exists"}
            product = Product(
                sku=sku, name=name, price=Decimal(str(price)),
                description=description, emoji=emoji,
            )
            s.add(product)
            await s.flush()
            return self._product_dict(product)

    async def get_customer_by_email(self, email: str) -> dict | None:
        from sqlalchemy import func, select

        from ..db.models import Customer
        from ..db.session import session_scope

        async with session_scope() as s:
            r = (await s.scalars(
                select(Customer).where(func.lower(Customer.email) == (email or "").strip().lower())
            )).first()
            return {"id": r.id, "name": r.name, "email": r.email} if r else None

    async def create_customer(self, name: str, email: str) -> dict:
        from ..db.models import Customer
        from ..db.session import session_scope

        existing = await self.get_customer_by_email(email)
        if existing:
            return existing
        async with session_scope() as s:
            c = Customer(name=name, email=email)
            s.add(c)
            await s.flush()
            return {"id": c.id, "name": c.name, "email": c.email}

    async def create_order(
        self, customer_id, item_description, amount, status="delivered", delivered_at=None,
        product_id=None,
    ) -> dict:
        from datetime import datetime
        from decimal import Decimal

        from ..db.models import Customer, Order, Product
        from ..db.session import session_scope

        dt = datetime.fromisoformat(delivered_at) if delivered_at else None
        async with session_scope() as s:
            if product_id is not None:
                product = await s.get(Product, product_id)
                if product is None:
                    return {"error": f"product {product_id} not found"}
                item_description = product.name
                amount = product.price
            o = Order(
                customer_id=customer_id, product_id=product_id,
                amount=Decimal(str(amount)), status=status,
                item_description=item_description, shipping_address="", delivered_at=dt,
            )
            s.add(o)
            await s.flush()
            payment = await self.payments.create_payment(
                order_id=o.id, amount=float(o.amount), description=o.item_description,
            )
            o.payment_ref = payment.get("payment_ref")
            cust = await s.get(Customer, customer_id)
            return self._order_dict(o, cust)

    async def update_address(self, order_id, new_address, ctx=None) -> dict:
        from ..db.models import Order

        async def effect(s):
            o = await s.get(Order, order_id)
            if o is None:
                return {"error": f"order {order_id} not found"}
            o.shipping_address = new_address
            return {"order_id": order_id, "shipping_address": new_address, "updated": True}

        return await self._once(ctx, "update_address", {"order_id": order_id, "new_address": new_address}, effect)

    async def add_note(self, order_id, note, author, ctx=None) -> dict:
        from ..db.models import OrderNote

        async def effect(s):
            s.add(OrderNote(order_id=order_id, note=note, author=author))
            return {"order_id": order_id, "note_added": True}

        return await self._once(ctx, "add_note", {"order_id": order_id, "note": note}, effect)

    async def issue_refund(self, order_id, amount, reason, ctx=None) -> dict:
        from decimal import Decimal

        from ..db.models import Order, Refund

        async def effect(s):
            o = await s.get(Order, order_id)
            if o is None:
                return {"error": f"order {order_id} not found"}
            provider_refund = await self.payments.refund(
                payment_ref=o.payment_ref,
                amount=amount,
                idempotency_key=ctx.idempotency_key if ctx else None,
                reason=reason,
            )
            if "error" in provider_refund:
                return provider_refund
            provider = provider_refund.get("provider")
            provider_refund_id = provider_refund.get("refund_id")
            status = provider_refund.get("status", "issued")
            r = Refund(
                order_id=order_id, amount=Decimal(str(amount)), reason=reason,
                provider=provider, provider_refund_id=provider_refund_id, status=status,
                idempotency_key=ctx.idempotency_key if ctx else None,
            )
            s.add(r)
            await s.flush()
            return {
                "refund_id": r.id, "order_id": order_id, "amount": amount, "status": status,
                "provider": provider, "provider_refund_id": provider_refund_id,
            }

        return await self._once(ctx, "issue_refund", {"order_id": order_id, "amount": amount}, effect)

    async def cancel_order(self, order_id, reason, ctx=None) -> dict:
        from ..db.models import Order

        async def effect(s):
            o = await s.get(Order, order_id)
            if o is None:
                return {"error": f"order {order_id} not found"}
            o.status = "cancelled"
            return {"order_id": order_id, "status": "cancelled", "reason": reason}

        return await self._once(ctx, "cancel_order", {"order_id": order_id}, effect)

    async def apply_credit(self, customer_id, amount, reason, ctx=None) -> dict:
        # No dedicated credits table yet; record via audit + ledger result.
        async def effect(_s):
            return {"customer_id": customer_id, "amount": amount, "reason": reason, "status": "applied"}

        return await self._once(ctx, "apply_credit", {"customer_id": customer_id, "amount": amount}, effect)

    @staticmethod
    def _audit_content(entry) -> dict:
        return {
            column.name: getattr(entry, column.name)
            for column in entry.__table__.columns
            if column.name not in {"prev_hash", "entry_hash"}
        }

    async def _append_audit(self, session, row: dict) -> None:
        from sqlalchemy import select

        from ..db.models import AuditLog
        from ..safety.audit_chain import chain_hash

        # Concurrent writers need a DB sequence/advisory lock to avoid sibling links.
        prev_hash = await session.scalar(
            select(AuditLog.entry_hash).order_by(AuditLog.id.desc()).limit(1)
        )
        entry = AuditLog(**row, prev_hash=prev_hash, entry_hash="")
        session.add(entry)
        await session.flush()
        entry.entry_hash = chain_hash(prev_hash, self._audit_content(entry))

    async def write_audit(self, **fields) -> None:
        from ..db.session import session_scope

        from ..safety.guardrails import redact

        allowed = {
            "thread_id", "event_type", "actor", "tool_name", "args", "result",
            "idempotency_key", "policy_ref", "latency_ms", "tokens",
        }
        row = {k: v for k, v in fields.items() if k in allowed}
        for key in ("args", "result"):
            if row.get(key) is not None:
                row[key] = redact(row[key])
        row.setdefault("thread_id", "")
        row.setdefault("event_type", "event")
        row.setdefault("actor", "system")
        async with session_scope() as s:
            await self._append_audit(s, row)

    async def list_audit(self, thread_id=None, limit=100) -> list[dict]:
        from sqlalchemy import select

        from ..db.models import AuditLog
        from ..db.session import session_scope

        async with session_scope() as s:
            stmt = select(AuditLog).order_by(AuditLog.id.desc()).limit(limit)
            if thread_id is not None:
                stmt = stmt.where(AuditLog.thread_id == thread_id)
            rows = (await s.scalars(stmt)).all()
            output = []
            for row in rows:
                content = self._audit_content(row)
                content["created_at"] = row.created_at.isoformat()
                content["prev_hash"] = row.prev_hash
                content["entry_hash"] = row.entry_hash
                output.append(content)
            return output

    async def verify_audit_chain(self) -> dict:
        from sqlalchemy import select

        from ..db.models import AuditLog
        from ..db.session import session_scope
        from ..safety.audit_chain import chain_hash

        async with session_scope() as s:
            rows = (await s.scalars(select(AuditLog).order_by(AuditLog.id))).all()
            running_hash = None
            for index, row in enumerate(rows):
                expected = chain_hash(running_hash, self._audit_content(row))
                if row.prev_hash != running_hash or row.entry_hash != expected:
                    return {"intact": False, "entries": len(rows), "broken_at": index}
                running_hash = row.entry_hash
            return {"intact": True, "entries": len(rows), "broken_at": None}

    # ---- compensation / rollback ----
    async def compensate(self, idempotency_key, actor="human", reason="") -> dict:
        from sqlalchemy import select

        from ..db.models import Order, Refund, ToolExecution
        from ..db.session import session_scope

        async with session_scope() as s:
            te = await s.get(ToolExecution, idempotency_key)
            if te is None:
                return {"error": "no execution found for that idempotency key"}
            if te.compensated:
                return {"status": "already_compensated", "idempotency_key": idempotency_key}

            undo = {"status": "compensated", "tool_name": te.tool_name}
            if te.tool_name == "issue_refund":
                # Stripe refunds are terminal; compensation records an internal reversal only.
                r = (await s.scalars(
                    select(Refund).where(Refund.idempotency_key == idempotency_key)
                )).first()
                if r is not None:
                    r.status = "reversed"
                    undo["reversed_refund_id"] = r.id
                    undo["amount"] = float(r.amount)
                    if r.provider == "stripe":
                        undo["note"] = (
                            "Stripe refunds are terminal; no external re-charge was issued."
                        )
            elif te.tool_name == "cancel_order":
                oid = (te.result or {}).get("order_id")
                o = await s.get(Order, oid) if oid else None
                if o is not None:
                    o.status = "active"
                    undo["reinstated_order"] = oid
            else:
                return {"error": f"{te.tool_name} is not compensable"}

            te.compensated = True
            await self._append_audit(s, {
                "thread_id": te.thread_id, "event_type": "compensated", "actor": actor,
                "tool_name": te.tool_name, "result": undo,
                "idempotency_key": idempotency_key, "policy_ref": reason,
            })
            return undo

    async def dry_run(self, tool_name, args) -> dict:
        # Predicted effects without touching the DB (a true sandbox would require
        # threading a rollback-only session through the executors).
        predicted = {
            "issue_refund": {"refunds": "+1"},
            "cancel_order": {"order_status": "-> cancelled"},
            "apply_credit": {"credits": "+1"},
            "update_address": {"order_address": "-> updated"},
            "add_note": {"notes": "+1"},
        }.get(tool_name, {})
        return {"result": {"preview": f"{tool_name} would run with {args}"},
                "effects": predicted, "simulated": True}

    # ---- approval queue ----
    @staticmethod
    def _ar_to_dict(ar) -> dict:
        return {
            "id": str(ar.id), "thread_id": ar.thread_id, "checkpoint_id": ar.checkpoint_id,
            "tool_call_id": ar.tool_call_id,
            "tool_name": ar.tool_name, "tool_args": ar.tool_args, "risk_tier": ar.risk_tier,
            "policy_citation": ar.policy_citation, "status": ar.status,
            "modified_args": ar.modified_args, "reason": ar.reason, "decided_by": ar.decided_by,
            "decided_at": ar.decided_at.isoformat() if ar.decided_at else None,
            "escalated_at": ar.escalated_at.isoformat() if ar.escalated_at else None,
            "created_at": ar.created_at.isoformat() if ar.created_at else None,
        }

    async def create_approvals(self, thread_id, checkpoint_id, items) -> list[dict]:
        from sqlalchemy import select

        from ..db.models import ApprovalRequest
        from ..db.session import session_scope

        created = []
        async with session_scope() as s:
            existing = (await s.scalars(
                select(ApprovalRequest.tool_call_id).where(
                    ApprovalRequest.thread_id == thread_id, ApprovalRequest.status == "pending"
                )
            )).all()
            pending_tcids = set(existing)
            for item in items:
                tcid = item["tool_call_id"]
                if tcid in pending_tcids:
                    continue
                ar = ApprovalRequest(
                    thread_id=thread_id, checkpoint_id=checkpoint_id, tool_call_id=tcid,
                    tool_name=item["tool"], tool_args=item.get("args", {}),
                    risk_tier=item.get("risk_tier", "high_stakes"),
                    policy_citation=item.get("justification"), status="pending",
                )
                s.add(ar)
                await s.flush()
                created.append(self._ar_to_dict(ar))
        return created

    async def list_approvals(self, status=None, thread_id=None) -> list[dict]:
        from sqlalchemy import select

        from ..db.models import ApprovalRequest
        from ..db.session import session_scope

        async with session_scope() as s:
            stmt = select(ApprovalRequest).order_by(ApprovalRequest.created_at)
            if status is not None:
                stmt = stmt.where(ApprovalRequest.status == status)
            if thread_id is not None:
                stmt = stmt.where(ApprovalRequest.thread_id == thread_id)
            rows = (await s.scalars(stmt)).all()
            return [self._ar_to_dict(r) for r in rows]

    async def get_approval(self, approval_id) -> dict | None:
        import uuid as _uuid

        from ..db.models import ApprovalRequest
        from ..db.session import session_scope

        async with session_scope() as s:
            ar = await s.get(ApprovalRequest, _uuid.UUID(approval_id))
            return self._ar_to_dict(ar) if ar is not None else None

    async def decide_approval(self, approval_id, decision, modified_args, reason, decided_by) -> dict | None:
        import uuid as _uuid
        from datetime import datetime, timezone

        from ..db.models import ApprovalRequest
        from ..db.session import session_scope

        async with session_scope() as s:
            ar = await s.get(ApprovalRequest, _uuid.UUID(approval_id))
            if ar is None:
                return None
            ar.status = _DECISION_TO_STATUS.get(decision, "approved")
            ar.modified_args = modified_args
            ar.reason = reason
            ar.decided_by = decided_by
            ar.decided_at = datetime.now(timezone.utc)
            await s.flush()
            return self._ar_to_dict(ar)

    async def mark_escalated(self, approval_id, at=None) -> dict | None:
        import uuid as _uuid

        from sqlalchemy import select

        from ..db.models import ApprovalRequest
        from ..db.session import session_scope

        escalated_at = at or datetime.now(timezone.utc)
        async with session_scope() as s:
            ar = await s.scalar(
                select(ApprovalRequest)
                .where(ApprovalRequest.id == _uuid.UUID(approval_id))
                .with_for_update()
            )
            if ar is None or ar.status != "pending" or ar.escalated_at is not None:
                return None
            ar.escalated_at = escalated_at
            await s.flush()
            return self._ar_to_dict(ar)


def build_store(settings, payments: PaymentProvider | None = None) -> Store:
    """Return the Store for the configured backend."""
    payments = payments or build_payment_provider(settings)
    if settings.database_configured:
        return PostgresStore(payments=payments)
    return MemoryStore(payments=payments)
