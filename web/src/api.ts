export type Approval = {
  id: string;
  thread_id: string;
  tool_name: string;
  tool_args: Record<string, unknown>;
  risk_tier: string | null;
  policy_citation: string | null;
  status: string;
  created_at: string | null;
  escalated_at: string | null;
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
  product_id: number | null;
  amount: number;
  status: string;
  item_description: string;
  customer_name: string | null;
  customer_email: string | null;
  delivered_at: string | null;
};

export type Product = {
  id: number;
  sku: string;
  name: string;
  price: number;
  active: boolean;
  description: string;
  emoji: string;
};

export type Customer360 = {
  customer: { id: number; name: string; email: string };
  orders: Array<{
    id: number;
    item_description: string;
    amount: number;
    status: string;
    delivered_at: string | null;
  }>;
  refunds: Array<{
    order_id: number;
    amount: number;
    status: string;
    reason: string;
    provider: string | null;
  }>;
  notes: Array<{ order_id: number; note: string; author: string }>;
};

export type Customer360Result = Customer360 | { error: string };

export type NewProduct = {
  sku: string;
  name: string;
  price: number;
  description?: string;
  emoji?: string;
};

export type NewOrder = {
  name: string;
  email: string;
  product_id?: number;
  item?: string;
  amount?: number;
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

export type AuthUser = {
  email: string;
  role: string;
  operator_approval_limit: number;
};

export type LoginResponse = {
  access_token: string;
  token_type: "bearer";
  role: string;
};

const TOKEN_KEY = "hitl-access-token";
export const AUTH_CLEARED_EVENT = "hitl-auth-cleared";

export function getAccessToken(): string | null {
  return window.localStorage.getItem(TOKEN_KEY);
}

export function setAccessToken(token: string): void {
  window.localStorage.setItem(TOKEN_KEY, token);
}

export function clearAccessToken(): void {
  window.localStorage.removeItem(TOKEN_KEY);
  window.dispatchEvent(new Event(AUTH_CLEARED_EVENT));
}

async function errorDetail(response: Response): Promise<string> {
  const body = await response.text().catch(() => "");
  if (!body) return `${response.status} ${response.statusText}`;
  try {
    const parsed = JSON.parse(body) as { detail?: unknown };
    if (typeof parsed.detail === "string") return parsed.detail;
  } catch {
    // The backend may return a plain-text error through a proxy.
  }
  return body;
}

async function req<T>(url: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers);
  if (init?.body && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
  const token = getAccessToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);

  const r = await fetch(url, {
    ...init,
    headers,
  });
  if (r.status === 401) clearAccessToken();
  if (!r.ok) {
    throw new Error(await errorDetail(r));
  }
  return r.json() as Promise<T>;
}

export const api = {
  login: (email: string, password: string) =>
    req<LoginResponse>("/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    }),
  me: () => req<AuthUser>("/auth/me"),
  approvals: () => req<Approval[]>("/approvals"),
  audit: (limit = 40) => req<AuditRow[]>(`/audit?limit=${limit}`),
  metrics: () => req<Metrics>("/metrics"),
  orders: () => req<Order[]>("/store/orders"),
  products: () => req<Product[]>("/store/products"),
  customer360: (orderId: number) =>
    req<Customer360Result>(`/store/customer-360/${orderId}`),
  createProduct: (body: NewProduct) =>
    req<Product>("/store/products", { method: "POST", body: JSON.stringify(body) }),
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
