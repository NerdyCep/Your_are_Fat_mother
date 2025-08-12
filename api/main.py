# api/main.py
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import uuid
import time
import json
import sqlite3
import os
from kafka import KafkaProducer
from typing import Optional

DB_PATH = "/data/payments.db"
os.makedirs("/data", exist_ok=True)


# ============================
# Инициализация SQLite
# ============================
def init_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS payments (
        payment_id TEXT PRIMARY KEY,
        merchant_id TEXT,
        amount INTEGER,
        currency TEXT,
        status TEXT,
        created_at INTEGER,
        updated_at INTEGER
    );
    """)
    conn.commit()
    conn.close()


init_db()

# ============================
# Инициализация FastAPI
# ============================
app = FastAPI(title="Payment Aggregator API (MVP)")

# ============================
# Конфигурация Kafka Producer
# ============================
bootstrap = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092")
producer = KafkaProducer(
    bootstrap_servers=bootstrap,
    value_serializer=lambda v: json.dumps(v).encode("utf-8"),
    api_version=(2, 0, 0)
)


# ============================
# Модели запросов
# ============================
class PaymentRequest(BaseModel):
    merchant_id: str
    amount: int  # в центах
    currency: str


class CallbackRequest(BaseModel):
    payment_id: str
    status: str


# ============================
# Создание платежа
# ============================
@app.post("/v1/payments")
async def create_payment(req: PaymentRequest):
    if req.amount <= 0:
        raise HTTPException(status_code=400, detail="Amount must be > 0")

    payment_id = str(uuid.uuid4())
    now = int(time.time())

    event = {
        "event_type": "payment.requested",
        "payment_id": payment_id,
        "merchant_id": req.merchant_id,
        "amount": req.amount,
        "currency": req.currency,
        "created_at": now
    }

    # Сохраняем в SQLite
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO payments(payment_id, merchant_id, amount, currency, status, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (payment_id, req.merchant_id, req.amount, req.currency, "processing", now, now))
    conn.commit()
    conn.close()

    # Отправляем в Kafka
    producer.send("payments", event)
    producer.flush()

    return {"payment_id": payment_id, "status": "processing"}


# ============================
# Callback от коннектора
# ============================
@app.post("/v1/payments/callback")
async def payment_callback(req: CallbackRequest):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    now = int(time.time())

    cur.execute(
        "UPDATE payments SET status=?, updated_at=? WHERE payment_id=?",
        (req.status, now, req.payment_id)
    )

    if cur.rowcount == 0:
        conn.close()
        raise HTTPException(status_code=404, detail="payment not found")

    conn.commit()
    conn.close()
    return {"ok": True}


# ============================
# Получить платеж
# ============================
@app.get("/v1/payments/{payment_id}")
async def get_payment(payment_id: str):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        SELECT payment_id, merchant_id, amount, currency, status, created_at, updated_at
        FROM payments WHERE payment_id=?
    """, (payment_id,))
    row = cur.fetchone()
    conn.close()

    if not row:
        raise HTTPException(status_code=404, detail="payment not found")

    return {
        "payment_id": row[0],
        "merchant_id": row[1],
        "amount": row[2],
        "currency": row[3],
        "status": row[4],
        "created_at": row[5],
        "updated_at": row[6]
    }


# ============================
# Healthcheck
# ============================
@app.get("/health")
async def health():
    return {"status": "ok"}
