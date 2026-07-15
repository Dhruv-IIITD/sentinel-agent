export type Approval = {
  id: string;
  thread_id: string;
  tool_name: string;
  tool_args: Record<string, unknown>;
  risk_tier: string | null;
  policy_citation: string | null;
  status: string;
  created_at: string | null;
};

export type AuditRow = {
  thread_id: string;
  event_type: string;
  actor: string;
  tool_name: string | null;
  idempotency_key: string | null;
  created_at?: string;
};

export type Order = {
  id: number;
  amount: number;
  status: string;
  item_description: string;
  customer_name: string | null;
  customer_email: string | null;
  delivered_at: string | null;
};

export type NewOrder = {
  name: string;
  email: string;
  item: string;
  amount: number;
  status?: string;
  delivered_days_ago?: number | null;
};

export type CreatedOrder = {
  order: Order;
  customer: { id: number; name: string; email: string };
  verify: { order_id: number; email: string };
};

export type TokenResp = { token: string; url: string; room: string; thread_id: string };

/** An approval call: rings a real phone when a SIP trunk is set, otherwise the
 *  room is live and the approver joins from the browser. */
export type ApprovalCall = TokenResp & { dialed: boolean; phone: string | null };

export type Preview = {
  outcomes: {
    approve: { executes: boolean; effects?: Record<string, unknown> };
    reject: { executes: boolean; message?: string };
  };
};

export type Counterfactual = {
  outcomes: Record<string, { reply: string; effects: Record<string, unknown> }>;
};

export type Decision = { decision: "approve" | "reject" | "modify"; reason?: string; modified_args?: unknown; decided_by?: string };

export type Metrics = {
  actions: {
    auto_executed: number;
    executed_after_approval: number;
    declined_by_human: number;
    reversed: number;
  };
  autonomy_rate: number | null;
  override_rate: number | null;
  approvals: { pending: number; decided: number; rejected: number; modified: number };
  time_to_decision_s: { p50: number | null; p95: number | null; max: number | null };
  tool_latency_ms: { p50: number | null; p95: number | null };
};

async function req<T>(url: string, init?: RequestInit): Promise<T> {
  const r = await fetch(url, {
    ...init,
    headers: init?.body ? { "Content-Type": "application/json", ...init?.headers } : init?.headers,
  });
  if (!r.ok) {
    const detail = await r.text().catch(() => "");
    throw new Error(detail || `${r.status} ${r.statusText}`);
  }
  return r.json() as Promise<T>;
}

export const api = {
  approvals: () => req<Approval[]>("/approvals"),
  audit: (limit = 40) => req<AuditRow[]>(`/audit?limit=${limit}`),
  metrics: () => req<Metrics>("/metrics"),
  orders: () => req<Order[]>("/store/orders"),
  createOrder: (body: NewOrder) =>
    req<CreatedOrder>("/store/orders", { method: "POST", body: JSON.stringify(body) }),
  decide: (id: string, body: Decision) =>
    req<{ status: string; reply?: string }>(`/approvals/${id}/decision`, {
      method: "POST",
      body: JSON.stringify({ decided_by: "manager", ...body }),
    }),
  preview: (id: string) => req<Preview>(`/approvals/${id}/preview`),
  counterfactual: (threadId: string) =>
    req<Counterfactual>(`/threads/${threadId}/counterfactual`, { method: "POST" }),
  compensate: (key: string, reason: string) =>
    req<{ status: string }>(`/compensate/${key}`, { method: "POST", body: JSON.stringify({ reason }) }),
  chat: (message: string, thread_id: string) =>
    req<{ status: string; reply?: string; approvals?: Approval[] }>("/chat", {
      method: "POST",
      body: JSON.stringify({ message, thread_id }),
    }),
  token: () => req<TokenResp>("/voice/token", { method: "POST", body: JSON.stringify({ name: "Caller" }) }),
  approvalCall: (id: string) =>
    req<ApprovalCall>(`/voice/approval-call/${id}`, { method: "POST", body: JSON.stringify({}) }),
};

/** Tools whose effect can be undone through the idempotency ledger. */
export const COMPENSABLE = new Set(["issue_refund", "cancel_order", "apply_credit"]);
