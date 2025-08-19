// dashboard/src/main.tsx
import React from "react";
import { createRoot } from "react-dom/client";
import {
  api, Payment, Merchant, Stats, PaymentStatus, Refund,
  listMerchants, createMerchant, updateMerchant, deleteMerchant,
  listPayments, getPayment, updatePaymentStatus, resendWebhook, getStats,
  listRefundsByPayment, createRefund, simulateRefund
} from "./api";

type Tab = "payments" | "merchants" | "stats";

function useTab(): [Tab, (t: Tab)=>void] {
  const [tab, setTab] = React.useState<Tab>("payments");
  React.useEffect(() => {
    const onClick = (e: MouseEvent) => {
      const el = (e.target as HTMLElement | null)?.closest("a[data-tab]") as HTMLAnchorElement | null;
      if (el) {
        e.preventDefault();
        document.querySelectorAll("nav a").forEach(a => a.classList.remove("active"));
        el.classList.add("active");
        setTab(el.dataset.tab as Tab);
      }
    };
    document.addEventListener("click", onClick);
    return () => document.removeEventListener("click", onClick);
  }, []);
  return [tab, setTab];
}

function Login({ onOk }: { onOk: () => void }) {
  const [t, setT] = React.useState<string>(api.getToken() || "");
  return (
    <div className="card">
      <h3>Admin Token</h3>
      <p className="muted">Введи значение env <code>ADMIN_TOKEN</code> (по умолчанию <code>dev-admin</code>).</p>
      <div className="row">
        <input value={t} onChange={e => setT(e.target.value)} placeholder="dev-admin" style={{minWidth:280}}/>
        <button onClick={() => { api.setToken(t.trim()); onOk(); }}>Save</button>
      </div>
    </div>
  );
}

function useDebounced<T>(value: T, ms = 400) {
  const [v, setV] = React.useState(value);
  React.useEffect(() => {
    const id = setTimeout(() => setV(value), ms);
    return () => clearTimeout(id);
  }, [value, ms]);
  return v;
}

function addDays(d: Date, days: number) {
  const x = new Date(d);
  x.setDate(x.getDate() + days);
  return x;
}
function isoLocal(d: Date) {
  const pad = (n:number)=>String(n).padStart(2,"0");
  const yyyy = d.getFullYear();
  const mm = pad(d.getMonth()+1);
  const dd = pad(d.getDate());
  const hh = pad(d.getHours());
  const mi = pad(d.getMinutes());
  return `${yyyy}-${mm}-${dd}T${hh}:${mi}`;
}

function Json({ v }: { v: unknown }) {
  return <pre style={{margin:0, whiteSpace:"pre-wrap"}}>{JSON.stringify(v, null, 2)}</pre>;
}

function Payments() {
  // filters/state
  const [q, setQ] = React.useState("");
  const [merchantId, setMerchantId] = React.useState("");
  const [status, setStatus] = React.useState<PaymentStatus | "">("");
  const [currency, setCurrency] = React.useState("");
  const [amountMin, setAmountMin] = React.useState<number | "">("");
  const [amountMax, setAmountMax] = React.useState<number | "">("");
  const [createdFrom, setCreatedFrom] = React.useState("");
  const [createdTo, setCreatedTo] = React.useState("");
  const [sort, setSort] = React.useState<"created_at"|"amount">("created_at");
  const [order, setOrder] = React.useState<"asc"|"desc">("desc");
  const [limit, setLimit] = React.useState(25);
  const [offset, setOffset] = React.useState(0);

  const [items, setItems] = React.useState<Payment[]>([]);
  const [total, setTotal] = React.useState(0);
  const [loading, setLoading] = React.useState(false);
  const [err, setErr] = React.useState<string | null>(null);

  const [details, setDetails] = React.useState<Payment | null>(null);
  const [refunds, setRefunds] = React.useState<Refund[]>([]);
  const [refundAmount, setRefundAmount] = React.useState<number | "">("");
  const [refundReason, setRefundReason] = React.useState("");

  const debouncedQ = useDebounced(q, 400);

  // epoch seconds
  const epochFrom = React.useMemo(() => createdFrom ? Math.floor(new Date(createdFrom).getTime() / 1000) : undefined, [createdFrom]);
  const epochTo   = React.useMemo(() => createdTo ? Math.floor(new Date(createdTo).getTime() / 1000) : undefined, [createdTo]);

  React.useEffect(() => { setOffset(0); }, [
    debouncedQ, merchantId, status, currency, amountMin, amountMax, createdFrom, createdTo, sort, order, limit
  ]);

  async function load() {
    setLoading(true);
    setErr(null);
    try {
      const data = await listPayments({
        q: debouncedQ || undefined,
        merchant_id: merchantId || undefined,
        status: (status || undefined) as any,
        currency: currency ? currency.toUpperCase() : undefined,
        amount_min: amountMin === "" ? undefined : Number(amountMin),
        amount_max: amountMax === "" ? undefined : Number(amountMax),
        created_from: epochFrom,
        created_to: epochTo,
        sort, order, limit, offset
      });
      setItems(data.items);
      setTotal(data.total);
    } catch (e:any) {
      setErr(e.message || String(e));
    } finally { setLoading(false); }
  }
  React.useEffect(() => { void load(); }, [
    debouncedQ, merchantId, status, currency, amountMin, amountMax, epochFrom, epochTo, sort, order, limit, offset
  ]);

  const totalPages = Math.max(1, Math.ceil(total / limit));
  const currentPage = Math.floor(offset / limit) + 1;

  function setPreset(days: number) {
    const now = new Date();
    const from = addDays(now, -days);
    setCreatedFrom(isoLocal(from));
    setCreatedTo(isoLocal(now));
  }

  function refundedSum(list: Refund[]) {
    return list.filter(r => r.status === "succeeded").reduce((s, r) => s + r.amount, 0);
  }
  function remain(p: Payment, list: Refund[]) {
    return p.amount - refundedSum(list);
  }

  async function openDetails(id: string) {
    const [p, r] = await Promise.all([getPayment(id), listRefundsByPayment(id, 200)]);
    setDetails(p);
    const rs = r.items.sort((a,b)=>b.created_at - a.created_at);
    setRefunds(rs);
    setRefundAmount("");
    setRefundReason("");
    (document.getElementById("payment-modal") as HTMLDialogElement | null)?.showModal();
  }

  async function doRefund(simulate?: "succeed"|"fail") {
    if (!details) return;
    const amount = refundAmount === "" ? 0 : Number(refundAmount);
    if (amount <= 0) return alert("Amount must be > 0");
    try {
      let res: Refund;
      if (simulate === "succeed" || simulate === "fail") {
        const success = simulate === "succeed";
        res = await simulateRefund(details.payment_id, amount, refundReason || undefined, success);
      } else {
        res = await createRefund(details.payment_id, amount, refundReason || undefined, "succeeded");
      }
      const r = await listRefundsByPayment(details.payment_id, 200);
      setRefunds(r.items.sort((a,b)=>b.created_at - a.created_at));
      setRefundAmount("");
      setRefundReason("");
      alert(`Refund ${res.status}: ${res.amount} ${res.currency}`);
    } catch (e:any) {
      alert(e.message || String(e));
    }
  }

  return (
    <div className="card">
      <h3>Payments & Refunds</h3>

      <div className="row" style={{flexWrap:"wrap", alignItems:"center"}}>
        <input placeholder="Search (payment_id / idem / currency)" value={q} onChange={e=>setQ(e.target.value)} />
        <input placeholder="Merchant ID (UUID)" value={merchantId} onChange={e=>setMerchantId(e.target.value)} />
        <select value={status} onChange={e=>setStatus((e.target.value || "") as any)}>
          <option value="">— status —</option>
          {(["new","processing","approved","declined","failed"] as PaymentStatus[]).map(s => <option key={s} value={s}>{s}</option>)}
        </select>
        <input placeholder="Currency (USD)" value={currency} onChange={e=>setCurrency(e.target.value.toUpperCase())} />
        <input type="number" placeholder="Amount ≥" value={amountMin} onChange={e=>setAmountMin(e.target.value === "" ? "" : Number(e.target.value))}/>
        <input type="number" placeholder="Amount ≤" value={amountMax} onChange={e=>setAmountMax(e.target.value === "" ? "" : Number(e.target.value))}/>
      </div>

      <div className="row" style={{flexWrap:"wrap", marginTop:8, alignItems:"center"}}>
        <label>From: <input type="datetime-local" value={createdFrom} onChange={e=>setCreatedFrom(e.target.value)} /></label>
        <label>To: <input type="datetime-local" value={createdTo} onChange={e=>setCreatedTo(e.target.value)} /></label>
        <div className="row">
          <button onClick={()=>setPreset(1)}>24h</button>
          <button onClick={()=>setPreset(7)}>7d</button>
          <button onClick={()=>setPreset(30)}>30d</button>
          <button onClick={()=>{ setCreatedFrom(""); setCreatedTo(""); }}>Clear</button>
        </div>
        <label>Sort:
          <select value={sort} onChange={e=>setSort(e.target.value as any)}>
            <option value="created_at">created_at</option>
            <option value="amount">amount</option>
          </select>
        </label>
        <label>Order:
          <select value={order} onChange={e=>setOrder(e.target.value as any)}>
            <option value="desc">desc</option>
            <option value="asc">asc</option>
          </select>
        </label>
        <button onClick={()=>void load()} disabled={loading}>{loading ? "Loading..." : "Apply"}</button>
        <span className="muted" style={{marginLeft:"auto"}}>Found: {total}</span>
        {err && <span style={{color:"crimson"}}>{err}</span>}
      </div>

      <div style={{overflowX:"auto", marginTop:12}}>
        <table>
          <thead>
            <tr>
              <th>Payment</th><th>Amount</th><th>Curr</th><th>Status</th><th>Idempotency</th><th>Merchant</th><th>Created</th><th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {items.map(p => (
              <tr key={p.payment_id}>
                <td>
                  <a href="#" onClick={(e)=>{e.preventDefault(); void openDetails(p.payment_id);}}>
                    <code title={p.payment_id}>{p.payment_id.slice(0,8)}…</code>
                  </a>
                </td>
                <td>{p.amount}</td>
                <td>{p.currency}</td>
                <td>
                  <select value={p.status} onChange={async (e) => {
                    const np = await updatePaymentStatus(p.payment_id, e.target.value as PaymentStatus);
                    (document.activeElement as HTMLElement | null)?.blur();
                    setItems(prev => prev.map(x => x.payment_id===p.payment_id ? np : x));
                  }}>
                    {(["new","processing","approved","declined","failed"] as PaymentStatus[]).map(s => <option key={s} value={s}>{s}</option>)}
                  </select>
                </td>
                <td className="muted">{p.idempotency_key || "—"}</td>
                <td className="muted" title={p.merchant_webhook_url || ""}>{p.merchant_webhook_url || "—"}</td>
                <td className="muted">{new Date(p.created_at*1000).toISOString().replace("T"," ").replace(".000Z"," UTC")}</td>
                <td>
                  <button onClick={async ()=>{ await resendWebhook(p.payment_id); alert("Webhook queued"); }}>Resend webhook</button>
                </td>
              </tr>
            ))}
            {items.length===0 && !loading && <tr><td colSpan={8} className="muted">No data</td></tr>}
          </tbody>
        </table>
      </div>

      <div className="row" style={{alignItems:"center", marginTop:12}}>
        <span>Per page:</span>
        <select value={limit} onChange={e=>setLimit(Number(e.target.value))}>
          {[10,25,50,100,200].map(n => <option key={n} value={n}>{n}</option>)}
        </select>
        <button onClick={()=>setOffset(Math.max(0, offset - limit))} disabled={offset===0 || loading}>← Prev</button>
        <span>Page {currentPage} / {Math.max(1, Math.ceil(total/limit))}</span>
        <button onClick={()=>setOffset(offset + limit)} disabled={offset + limit >= total || loading}>Next →</button>
      </div>

      {/* Modal: details + refunds */}
      <dialog id="payment-modal" style={{border:"none", borderRadius:12, width:"min(900px, 95vw)"}}>
        <div style={{padding:"12px 16px", borderBottom:"1px solid #eee", display:"flex", justifyContent:"space-between"}}>
          <strong>Transaction details & refunds</strong>
          <button onClick={() => (document.getElementById("payment-modal") as HTMLDialogElement).close()}>✕</button>
        </div>
        <div style={{padding:"12px 16px"}}>
          {!details ? <p className="muted">Loading…</p> : (
            <>
              <div className="row" style={{flexWrap:"wrap"}}>
                <div className="card" style={{padding:"8px 12px"}}>
                  <div className="muted">Payment</div>
                  <div><code>{details.payment_id}</code></div>
                </div>
                <div className="card" style={{padding:"8px 12px"}}>
                  <div className="muted">Status</div>
                  <div>{details.status}</div>
                </div>
                <div className="card" style={{padding:"8px 12px"}}>
                  <div className="muted">Amount</div>
                  <div style={{fontWeight:700}}>{details.amount} {details.currency}</div>
                </div>
                <div className="card" style={{padding:"8px 12px"}}>
                  <div className="muted">Refunded</div>
                  <div style={{fontWeight:700}}>{refundedSum(refunds)} {details.currency}</div>
                </div>
                <div className="card" style={{padding:"8px 12px"}}>
                  <div className="muted">Remaining</div>
                  <div style={{fontWeight:700}}>{remain(details, refunds)} {details.currency}</div>
                </div>
              </div>

              <h4 style={{margin:"12px 0 6px"}}>Create refund</h4>
              <div className="row" style={{alignItems:"center", flexWrap:"wrap"}}>
                <input type="number" placeholder="Amount" value={refundAmount}
                       onChange={e=>setRefundAmount(e.target.value === "" ? "" : Number(e.target.value))} />
                <input placeholder="Reason (optional)" value={refundReason} onChange={e=>setRefundReason(e.target.value)} />
                <button disabled={details.status!=="approved" || remain(details, refunds)<=0}
                        onClick={()=>void doRefund()}>
                  Refund (real)
                </button>
                <button disabled={details.status!=="approved" || remain(details, refunds)<=0}
                        onClick={()=>void doRefund("succeed")}>
                  Simulate success
                </button>
                <button disabled={details.status!=="approved"}
                        onClick={()=>void doRefund("fail")}>
                  Simulate fail
                </button>
              </div>
              {details.status!=="approved" && <p className="muted">Refunds доступны только для платежей со статусом <b>approved</b>.</p>}

              <h4 style={{margin:"12px 0 6px"}}>Refunds</h4>
              <div style={{overflowX:"auto"}}>
                <table>
                  <thead><tr><th>Refund</th><th>Amount</th><th>Status</th><th>Reason</th><th>Created</th></tr></thead>
                  <tbody>
                    {refunds.map(r => (
                      <tr key={r.refund_id}>
                        <td><code>{r.refund_id.slice(0,8)}…</code></td>
                        <td>{r.amount} {r.currency}</td>
                        <td>{r.status}</td>
                        <td className="muted">{r.reason || "—"}</td>
                        <td className="muted">{new Date(r.created_at*1000).toISOString().replace("T"," ").replace(".000Z"," UTC")}</td>
                      </tr>
                    ))}
                    {refunds.length===0 && <tr><td colSpan={5} className="muted">No refunds</td></tr>}
                  </tbody>
                </table>
              </div>

              <details style={{marginTop:12}}>
                <summary>Raw payment</summary>
                <Json v={details} />
              </details>
            </>
          )}
        </div>
      </dialog>
    </div>
  );
}

function Merchants() {
  const [items, setItems] = React.useState<Merchant[]>([]);
  const [form, setForm] = React.useState<{webhook_url:string; api_secret:string; api_key?:string}>({
    webhook_url: "http://merchant_webhook:8080/webhook",
    api_secret: "secret"
  });
  const [loading, setLoading] = React.useState<boolean>(false);

  const load = React.useCallback(async () => setItems(await listMerchants()), []);
  React.useEffect(() => { void load(); }, [load]);

  return (
    <div className="card">
      <h3>Merchants</h3>

      <div className="row" style={{marginBottom:12}}>
        <input style={{minWidth:340}} placeholder="webhook_url"
               value={form.webhook_url}
               onChange={e=>setForm(f=>({...f, webhook_url: e.target.value}))}/>
        <input style={{minWidth:200}} placeholder="api_secret"
               value={form.api_secret}
               onChange={e=>setForm(f=>({...f, api_secret: e.target.value}))}/>
      <input style={{minWidth:220}} placeholder="api_key (optional)"
               value={form.api_key || ""}
               onChange={e=>setForm(f=>({...f, api_key: e.target.value}))}/>
        <button disabled={loading} onClick={async ()=>{
          setLoading(true);
          try {
            await createMerchant(form.webhook_url, form.api_secret, form.api_key);
            setForm({webhook_url:"", api_secret:"", api_key:""});
            await load();
          } finally { setLoading(false); }
        }}>{loading ? "Adding..." : "Add"}</button>
      </div>

      <div style={{overflowX:"auto"}}>
        <table>
          <thead><tr><th>ID</th><th>Webhook URL</th><th>API Secret</th><th>API Key</th><th>Actions</th></tr></thead>
          <tbody>
            {items.map(m => (
              <tr key={m.id}>
                <td><code title={m.id}>{m.id.slice(0,8)}…</code></td>
                <td><input value={m.webhook_url} onChange={e => setItems(prev => prev.map(x => x.id===m.id ? {...x, webhook_url:e.target.value} : x))} /></td>
                <td><input value={m.api_secret} onChange={e => setItems(prev => prev.map(x => x.id===m.id ? {...x, api_secret:e.target.value} : x))} /></td>
                <td><input value={m.api_key || ""} onChange={e => setItems(prev => prev.map(x => x.id===m.id ? {...x, api_key:e.target.value} : x))} /></td>
                <td className="row">
                  <button onClick={async ()=>{
                    const cur = items.find(x=>x.id===m.id)!;
                    await updateMerchant(m.id, { webhook_url: cur.webhook_url, api_secret: cur.api_secret, api_key: cur.api_key });
                    window.alert("Saved");
                  }}>Save</button>
                  <button onClick={async ()=>{
                    if (!window.confirm("Delete merchant? (only if no payments)")) return;
                    try { await deleteMerchant(m.id); await load(); }
                    catch (e:any) { window.alert(e.message); }
                  }}>Delete</button>
                </td>
              </tr>
            ))}
            {items.length===0 && <tr><td colSpan={5} className="muted">No merchants</td></tr>}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function StatsView() {
  const [stats, setStats] = React.useState<Stats | null>(null);
  const [err, setErr] = React.useState<string | null>(null);
  const [loading, setLoading] = React.useState<boolean>(false);

  const load = React.useCallback(async () => {
    setLoading(true);
    setErr(null);
    try {
      const s = await getStats();
      setStats(s);
    } catch (e:any) {
      setErr(e.message || String(e));
      setStats(null);
    } finally {
      setLoading(false);
    }
  }, []);

  React.useEffect(() => { void load(); }, [load]);

  return (
    <div className="card">
      <h3>Stats</h3>
      {loading && <p className="muted">Loading…</p>}
      {!loading && err && (
        <div style={{color:"crimson"}}>
          Ошибка загрузки статистики: {err}
          <div><button onClick={()=>void load()}>Retry</button></div>
        </div>
      )}
      {!loading && !err && stats && (
        <>
          <p>Total merchants: <b>{stats.merchants_total}</b></p>
          <p>Total payments: <b>{stats.payments_total}</b></p>
          <div className="row">
            {Object.entries(stats.counts_by_status).map(([s,c]) => (
              <div key={s} className="card" style={{padding:"8px 12px"}}>
                <div className="muted">{s}</div>
                <div style={{fontSize:22, fontWeight:700}}>{c}</div>
              </div>
            ))}
          </div>
          <div className="row" style={{marginTop:8}}>
            <button onClick={()=>void load()}>Reload</button>
          </div>
        </>
      )}
    </div>
  );
}

function App() {
  const [tab] = useTab();
  const hasToken = !!api.getToken();
  return (
    <>
      {!hasToken && <Login onOk={()=>location.reload()} />}
      {hasToken && (
        <>
          {tab==="payments" && <Payments />}
          {tab==="merchants" && <Merchants />}
          {tab==="stats" && <StatsView />}
        </>
      )}
    </>
  );
}

const rootEl = document.getElementById("root");
if (!rootEl) throw new Error("#root not found");
createRoot(rootEl).render(<App />);
