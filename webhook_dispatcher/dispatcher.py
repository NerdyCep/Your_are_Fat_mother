import os, time, json, hmac, hashlib
import psycopg2, psycopg2.extras
import requests

DB_DSN = os.getenv("DB_DSN", "postgresql://postgres:postgres@postgres:5432/payments")

def pg():
    return psycopg2.connect(DB_DSN)

def init():
    conn = pg(); cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS webhook_outbox (
      payment_id TEXT PRIMARY KEY,
      delivered BOOLEAN DEFAULT FALSE,
      attempts INT DEFAULT 0,
      last_attempt BIGINT
    );""")
    conn.commit(); cur.close(); conn.close()

def sign(secret: str, body_bytes: bytes) -> str:
    return hmac.new(secret.encode(), body_bytes, hashlib.sha256).hexdigest()

def fetch_ready(limit=50):
    conn = pg()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    cur.execute("""
      SELECT p.payment_id, p.merchant_id, p.amount, p.currency, p.status, p.created_at,
             m.webhook_url, m.api_secret
      FROM payments p
      JOIN merchants m ON m.id = p.merchant_id
      LEFT JOIN webhook_outbox o ON o.payment_id = p.payment_id
      WHERE p.status IN ('approved','declined')
        AND (o.payment_id IS NULL OR o.delivered = FALSE)
      ORDER BY p.created_at DESC
      LIMIT %s
    """, (limit,))
    rows = cur.fetchall()
    cur.close(); conn.close()
    return [dict(r) for r in rows]

def mark_attempt(payment_id: str, delivered: bool):
    conn = pg(); cur = conn.cursor()
    ts = int(time.time())
    cur.execute("""
      INSERT INTO webhook_outbox(payment_id, delivered, attempts, last_attempt)
      VALUES (%s, %s, 1, %s)
      ON CONFLICT (payment_id)
      DO UPDATE SET
        attempts = webhook_outbox.attempts + 1,
        delivered = EXCLUDED.delivered,
        last_attempt = EXCLUDED.last_attempt
    """, (payment_id, delivered, ts))
    conn.commit(); cur.close(); conn.close()

def main():
    init()
    print("[webhook_dispatcher] started")
    while True:
        batch = fetch_ready()
        if not batch:
            time.sleep(2); continue

        for rec in batch:
            payload = {
                "payment_id": rec["payment_id"],
                "merchant_id": rec["merchant_id"],
                "amount": rec["amount"],
                "currency": rec["currency"],
                "status": rec["status"],
                "created_at": rec["created_at"]
            }
            body = json.dumps(payload).encode("utf-8")
            sig = sign(rec["api_secret"], body)
            headers = {"Content-Type": "application/json", "X-Signature": sig}
            url = rec["webhook_url"]

            ok = False
            for attempt in range(5):  # до 5 попыток с бэкофом
                try:
                    r = requests.post(url, data=body, headers=headers, timeout=10)
                    if 200 <= r.status_code < 300:
                        ok = True
                        break
                    else:
                        print(f"[webhook_dispatcher] {rec['payment_id']} -> HTTP {r.status_code}")
                except Exception as e:
                    print(f"[webhook_dispatcher] error: {e}")
                time.sleep(2 * (attempt + 1))

            mark_attempt(rec["payment_id"], ok)
        time.sleep(1)

if __name__ == "__main__":
    main()
