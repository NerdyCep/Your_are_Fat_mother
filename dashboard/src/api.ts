const API_BASE = "/api/admin-api"; // nginx проксирует /api -> http://api:8000

function token(): string | null {
  return localStorage.getItem("ADMIN_TOKEN");
}
function authHeaders(): HeadersInit {
  const t = token();
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

export type PaymentStatus = "new" | "processing" | "approved" | "declined" | "failed";

export type Payment = {
  payment_id: string;
  merchant_id: string | null;
  amount: number;
  currency: string;
  status: PaymentStatus;
  idempotency_key: string | null;
  created_at: number; // epoch sec
  merchant_webhook_url?: string | null;
};

export type Merchant = {
  id: string;
  webhook_url: string;
  api_secret: string;
};

export type Stats = {
  counts_by_status: Record<string, number>;
  merchants_total: number;
  payments_total: number;
};

export const api = {
  setToken(t: string) { localStorage.setItem("ADMIN_TOKEN", t); },
  getToken() { return token(); },

  listMerchants(): Promise<Merchant[]> { return http<Merchant[]>("/merchants"); },
  createMerchant(webhook_url: string, api_secret: string): Promise<Merchant> {
    return http<Merchant>("/merchants", { method: "POST", body: JSON.stringify({ webhook_url, api_secret }) });
  },
  updateMerchant(id: string, patch: Partial<Pick<Merchant, "webhook_url" | "api_secret">>): Promise<Merchant> {
    return http<Merchant>(`/merchants/${id}`, { method: "PATCH", body: JSON.stringify(patch) });
  },
  deleteMerchant(id: string): Promise<void> {
    return http<void>(`/merchants/${id}`, { method: "DELETE" });
  },

  listPayments(q?: string, status?: PaymentStatus, limit = 50, offset = 0): Promise<Payment[]> {
    const p = new URLSearchParams();
    if (q) p.set("q", q);
    if (status) p.set("status", status);
    p.set("limit", String(limit));
    p.set("offset", String(offset));
    return http<Payment[]>(`/payments?${p.toString()}`);
  },
  updatePaymentStatus(id: string, status: PaymentStatus): Promise<Payment> {
    return http<Payment>(`/payments/${id}`, { method: "PATCH", body: JSON.stringify({ status }) });
  },
  resendWebhook(id: string): Promise<{status: string}> {
    return http<{status: string}>(`/payments/${id}/resend-webhook`, { method: "POST" });
  },

  getStats(): Promise<Stats> { return http<Stats>("/stats"); }
};
