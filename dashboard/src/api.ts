// dashboard/src/api.ts
export type PaymentStatus = "new" | "processing" | "approved" | "declined" | "failed";
export type RefundStatus  = "requested" | "succeeded" | "failed";

export type Payment = {
  payment_id: string;
  merchant_id: string | null;
  amount: number;
  currency: string;
  status: PaymentStatus;
  idempotency_key: string | null;
  created_at: number;       // epoch (seconds)
  merchant_webhook_url?: string | null;
};

export type Merchant = {
  id: string;
  webhook_url: string;
  api_secret: string;
  api_key?: string | null;
};

export type Refund = {
  refund_id: string;
  payment_id: string;
  amount: number;
  currency: string;
  status: RefundStatus;
  reason?: string | null;
  created_at: number;
};

export type Stats = {
  counts_by_status: Record<string, number>;
  merchants_total: number;
  payments_total: number;
};

export type PaymentsResponse = {
  items: Payment[];
  total: number;
  limit: number;
  offset: number;
};

export type RefundsResponse = {
  items: Refund[];
  total: number;
  limit: number;
  offset: number;
};

const API_BASE = "/api/admin-api";

const TOKEN_KEY = "ADMIN_TOKEN";
export const api = {
  setToken(t: string) { localStorage.setItem(TOKEN_KEY, t); },
  getToken(): string | null { return localStorage.getItem(TOKEN_KEY); },
};

function authHeaders(): HeadersInit {
  const t = api.getToken();
  return t ? { Authorization: `Bearer ${t}` } : {};
}

async function http<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers || {}),
      ...authHeaders(),
    },
  });
  if (!res.ok) {
    const msg = await res.text();
    throw new Error(`${res.status} ${res.statusText}: ${msg}`);
  }
  if (res.status === 204) return undefined as unknown as T;
  return res.json() as Promise<T>;
}

function toQuery(params: Record<string, unknown>) {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === null || v === "") continue;
    q.set(k, String(v));
  }
  return q.toString();
}

// Merchants
export function listMerchants(): Promise<Merchant[]> { return http<Merchant[]>("/merchants"); }
export function createMerchant(webhook_url: string, api_secret: string, api_key?: string): Promise<Merchant> {
  return http<Merchant>("/merchants", { method:"POST", body: JSON.stringify({ webhook_url, api_secret, api_key }) });
}
export function updateMerchant(id: string, patch: Partial<Pick<Merchant, "webhook_url" | "api_secret" | "api_key">>): Promise<Merchant> {
  return http<Merchant>(`/merchants/${id}`, { method:"PATCH", body: JSON.stringify(patch) });
}
export function deleteMerchant(id: string): Promise<void> { return http<void>(`/merchants/${id}`, { method:"DELETE" }); }

// Payments
export function listPayments(params: {
  q?: string;
  merchant_id?: string;
  status?: PaymentStatus;
  currency?: string;
  amount_min?: number;
  amount_max?: number;
  created_from?: number;
  created_to?: number;
  sort?: "created_at" | "amount";
  order?: "asc" | "desc";
  limit?: number;
  offset?: number;
} = {}): Promise<PaymentsResponse> {
  const qs = toQuery(params);
  return http<PaymentsResponse>(`/payments?${qs}`);
}
export function getPayment(id: string): Promise<Payment> {
  return http<Payment>(`/payments/${id}`);
}
export function updatePaymentStatus(id: string, status: PaymentStatus): Promise<Payment> {
  return http<Payment>(`/payments/${id}`, { method:"PATCH", body: JSON.stringify({ status }) });
}
export function resendWebhook(id: string): Promise<{status: string}> {
  return http<{status:string}>(`/payments/${id}/resend-webhook`, { method:"POST" });
}

// Refunds
export function listRefunds(params: {
  payment_id?: string;
  status?: RefundStatus;
  created_from?: number;
  created_to?: number;
  limit?: number;
  offset?: number;
  order?: "asc"|"desc";
} = {}): Promise<RefundsResponse> {
  const qs = toQuery(params);
  return http<RefundsResponse>(`/refunds?${qs}`);
}
export function listRefundsByPayment(payment_id: string, limit=100): Promise<RefundsResponse> {
  return http<RefundsResponse>(`/payments/${payment_id}/refunds?limit=${limit}`);
}
export function createRefund(payment_id: string, amount: number, reason?: string, result?: RefundStatus): Promise<Refund> {
  return http<Refund>(`/payments/${payment_id}/refunds`, {
    method: "POST",
    body: JSON.stringify({ amount, reason, result })
  });
}
export function simulateRefund(payment_id: string, amount: number, reason?: string, success = true): Promise<Refund> {
  return http<Refund>(`/payments/${payment_id}/simulate-refund`, {
    method: "POST",
    body: JSON.stringify({ amount, reason, success })
  });
}

// Stats
export function getStats(): Promise<Stats> { return http<Stats>("/stats"); }
