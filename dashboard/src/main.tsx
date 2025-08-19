import React from "react";
import { createRoot } from "react-dom/client";
import { api, Payment, Merchant, Stats, PaymentStatus } from "./api";

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

function Payments() {
  const [items, setItems] = React.useState<Payment[]>([]);
  const [q, setQ] = React.useState<string>("");
  const [status, setStatus] = React.useState<PaymentStatus | "">("");
  const [loading, setLoading] = React.useState<boolean>(false);

  const statuses: PaymentStatus[] = ["new","processing","approved","declined","failed"];

  const load = React.useCallback(async () => {
    setLoading(true);
    try {
      const data = await api.listPayments(q || undefined, (status || undefined) as PaymentStatus | undefined);
      setItems(data);
    } finally { setLoading(false); }
  }, [q, status]);

  React.useEffect(() => { void load(); }, [load]);

  return (
    <div className="card">
      <div className="row" style={{alignItems:"center"}}>
        <input placeholder="Search (idempotency/currency)" value={q} onChange={e=>setQ(e.target.value)} />
        <select value={status} onChange={e=>setStatus((e.target.value || "") as PaymentStatus | "")}>
          <option value="">— status —</option>
          {statuses.map(s => <option key={s} value={s}>{s}</option>)}
        </select>
        <button onClick={()=>void load()} disabled={loading}>{loading ? "Loading..." : "Reload"}</button>
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
                <td><code>{p.payment_id.slice(0,8)}…</code></td>
                <td>{p.amount}</td>
                <td>{p.currency}</td>
                <td>
                  <select value={p.status} onChange={async (e) => {
                    const np = await api.updatePaymentStatus(p.payment_id, e.target.value as PaymentStatus);
                    setItems(prev => prev.map(x => x.payment_id===p.payment_id ? np : x));
                  }}>
                    {statuses.map(s => <option key={s} value={s}>{s}</option>)}
                  </select>
                </td>
                <td className="muted">{p.idempotency_key || "—"}</td>
                <td className="muted">{p.merchant_webhook_url || "—"}</td>
                <td className="muted">{new Date(p.created_at*1000).toISOString().replace("T"," ").replace(".000Z"," UTC")}</td>
                <td>
                  <button onClick={async ()=>{
                    await api.resendWebhook(p.payment_id);
                    window.alert("Webhook queued");
                  }}>Resend webhook</button>
                </td>
              </tr>
            ))}
            {items.length===0 && <tr><td colSpan={8} className="muted">No data</td></tr>}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function Merchants() {
  const [items, setItems] = React.useState<Merchant[]>([]);
  const [form, setForm] = React.useState<{webhook_url:string; api_secret:string}>({
    webhook_url: "http://merchant_webhook:8080/webhook",
    api_secret: "secret"
  });
  const [loading, setLoading] = React.useState<boolean>(false);

  const load = React.useCallback(async () => {
    const data = await api.listMerchants();
    setItems(data);
  }, []);
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
        <button disabled={loading} onClick={async ()=>{
          setLoading(true);
          try {
            await api.createMerchant(form.webhook_url, form.api_secret);
            setForm({webhook_url:"", api_secret:""});
            await load();
          } finally { setLoading(false); }
        }}>{loading ? "Adding..." : "Add"}</button>
      </div>

      <div style={{overflowX:"auto"}}>
        <table>
          <thead><tr><th>ID</th><th>Webhook URL</th><th>API Secret</th><th>Actions</th></tr></thead>
          <tbody>
            {items.map(m => (
              <tr key={m.id}>
                <td><code>{m.id.slice(0,8)}…</code></td>
                <td>
                  <input value={m.webhook_url} onChange={e => setItems(prev => prev.map(x => x.id===m.id ? {...x, webhook_url:e.target.value} : x))} />
                </td>
                <td>
                  <input value={m.api_secret} onChange={e => setItems(prev => prev.map(x => x.id===m.id ? {...x, api_secret:e.target.value} : x))} />
                </td>
                <td className="row">
                  <button onClick={async ()=>{
                    const cur = items.find(x=>x.id===m.id)!;
                    await api.updateMerchant(m.id, { webhook_url: cur.webhook_url, api_secret: cur.api_secret });
                    window.alert("Saved");
                  }}>Save</button>
                  <button onClick={async ()=>{
                    if (!window.confirm("Delete merchant? (only if no payments)")) return;
                    try { await api.deleteMerchant(m.id); await load(); }
                    catch (e:any) { window.alert(e.message); }
                  }}>Delete</button>
                </td>
              </tr>
            ))}
            {items.length===0 && <tr><td colSpan={4} className="muted">No merchants</td></tr>}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function StatsView() {
  const [stats, setStats] = React.useState<Stats | null>(null);
  const load = React.useCallback(async () => setStats(await api.getStats()), []);
  React.useEffect(() => { void load(); }, [load]);

  return (
    <div className="card">
      <h3>Stats</h3>
      {!stats ? <p className="muted">Loading…</p> : (
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
