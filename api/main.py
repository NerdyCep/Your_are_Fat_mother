import os
import time
import uuid
import json
from typing import Optional

import psycopg2
import psycopg2.extras
from fastapi import FastAPI, Request, HTTPException, Header
from pydantic import BaseModel
from kafka import KafkaProducer

from admin_api import router as admin_router  # <— импортируем
app = FastAPI()
app.include_router(admin_router)

# -------------------------------------------------------------------
# Конфигурация
# -------------------------------------------------------------------

DB_DSN = os.getenv(
    "DB_DSN",
    "dbname=payments user=postgres host=postgres password=postgres"
)

KAFKA_BOOTSTRAP = os.getenv("KAFKA_BOOTSTRAP", "kafka:9092")

# Kafka producer
producer = KafkaProducer(
    bootstrap_servers=[KAFKA_BOOTSTRAP],
    value_serializer=lambda v: json.dumps(v).encode("utf-8"),
)


# -------------------------------------------------------------------
# Модели
# -------------------------------------------------------------------

class PaymentRequest(BaseModel):
    amount: int
    currency: str
    order_id: Optional[str] = None

# -------------------------------------------------------------------
# DB helpers
# -------------------------------------------------------------------

def get_merchant_by_api_key(api_key: str):
    """Возвращает мерчанта по API-ключу"""
    conn = psycopg2.connect(DB_DSN)
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT id FROM merchants WHERE api_key = %s LIMIT 1", (api_key,))
            row = cur.fetchone()
            return dict(row) if row else None
    finally:
        conn.close()


def get_payment_by_idempotency(merchant_id: str, idempotency_key: str):
    """Вернёт платеж если уже существует для пары (merchant_id, idempotency_key)"""
    if not idempotency_key:
        return None
    conn = psycopg2.connect(DB_DSN)
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT payment_id, status
                FROM payments
                WHERE merchant_id = %s AND idempotency_key = %s
                LIMIT 1
                """,
                (merchant_id, idempotency_key),
            )
            row = cur.fetchone()
            return dict(row) if row else None
    finally:
        conn.close()


def insert_payment(p: dict):
    """Вставка платежа. При конфликте по уникальному индексу бросит исключение"""
    conn = psycopg2.connect(DB_DSN)
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO payments
                       (payment_id, merchant_id, amount, currency, status,
                        order_id, idempotency_key, created_at, updated_at)
                    VALUES
                       (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    """,
                    (
                        p["payment_id"],
                        p["merchant_id"],
                        p["amount"],
                        p["currency"],
                        p["status"],
                        p.get("order_id"),
                        p.get("idempotency_key"),
                        p["created_at"],
                        p["updated_at"],
                    ),
                )
    finally:
        conn.close()


def get_payment(payment_id: str):
    """Вернёт платёж по ID"""
    conn = psycopg2.connect(DB_DSN)
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT payment_id, merchant_id, amount, currency, status,
                       order_id, idempotency_key, created_at, updated_at
                FROM payments
                WHERE payment_id = %s
                """,
                (payment_id,),
            )
            row = cur.fetchone()
            return dict(row) if row else None
    finally:
        conn.close()

# -------------------------------------------------------------------
# API
# -------------------------------------------------------------------

@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/v1/payments")
async def create_payment(
    req: PaymentRequest,
    request: Request,
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
):
    # 1) валидация
    if req.amount <= 0:
        raise HTTPException(status_code=400, detail="Amount must be > 0")
    if not req.currency:
        raise HTTPException(status_code=400, detail="Currency required")

    # 2) авторизация мерчанта
    api_key = request.headers.get("X-API-Key")
    if not api_key:
        raise HTTPException(status_code=401, detail="Missing X-API-Key")

    m = get_merchant_by_api_key(api_key)
    if not m:
        raise HTTPException(status_code=401, detail="Invalid API key")

    merchant_id = m["id"]

    # 3) быстрый путь идемпотентности
    if idempotency_key:
        existing = get_payment_by_idempotency(merchant_id, idempotency_key)
        if existing:
            return {
                "payment_id": existing["payment_id"],
                "status": existing["status"],
            }

    # 4) создаём новый платёж
    pid = str(uuid.uuid4())
    now = int(time.time())
    payment_row = {
        "payment_id": pid,
        "merchant_id": merchant_id,
        "amount": req.amount,
        "currency": req.currency,
        "status": "processing",
        "order_id": req.order_id,
        "idempotency_key": idempotency_key,
        "created_at": now,
        "updated_at": now,
    }

    created_new = True
    try:
        insert_payment(payment_row)
    except Exception:
        if idempotency_key:
            existing = get_payment_by_idempotency(merchant_id, idempotency_key)
            if existing:
                created_new = False
                pid = existing["payment_id"]
            else:
                raise
        else:
            raise

    # 5) публикуем событие только если платёж новый
    if created_new:
        event = {
            "event_type": "payment.requested",
            "payment_id": pid,
            "merchant_id": merchant_id,
            "amount": req.amount,
            "currency": req.currency,
            "created_at": now,
        }
        producer.send("payments", event)
        producer.flush()

    return {"payment_id": pid, "status": "processing"}


@app.get("/v1/payments/{payment_id}")
async def get_payment_api(payment_id: str):
    p = get_payment(payment_id)
    if not p:
        raise HTTPException(status_code=404, detail="Payment not found")
    return p


