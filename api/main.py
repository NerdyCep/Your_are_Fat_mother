from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field
from uuid import UUID, uuid4
from datetime import datetime
import asyncio
import aiokafka
import asyncpg
import aioredis

app = FastAPI(title="High Risk Payment Aggregator API")

# Подключения к сервисам (будут инициализированы в startup)
kafka_producer = None
pg_pool = None
redis = None

TOPIC = "payments"

class PaymentRequest(BaseModel):
    idempotency_key: UUID = Field(..., description="Уникальный ключ идемпотентности")
    amount: float = Field(..., gt=0, description="Сумма платежа")
    currency: str = Field(..., min_length=3, max_length=3, description="Валюта платежа")
    user_id: str = Field(..., description="ID пользователя казино")
    card_number: str = Field(..., min_length=12, max_length=19, description="Номер карты")
    card_expiry: str = Field(..., regex=r"^(0[1-9]|1[0-2])\/?([0-9]{2})$", description="Срок действия карты MM/YY")
    cvv: str = Field(..., min_length=3, max_length=4, description="CVV карты")

@app.on_event("startup")
async def startup_event():
    global kafka_producer, pg_pool, redis
    kafka_producer = aiokafka.AIOKafkaProducer(
        bootstrap_servers='localhost:9092',
        client_id="payment_api"
    )
    await kafka_producer.start()
    pg_pool = await asyncpg.create_pool(dsn="postgresql://user:password@localhost/payments")
    redis = await aioredis.create_redis_pool("redis://localhost")

@app.on_event("shutdown")
async def shutdown_event():
    global kafka_producer, pg_pool, redis
    await kafka_producer.stop()
    await pg_pool.close()
    redis.close()
    await redis.wait_closed()

@app.post("/payments", status_code=202)
async def create_payment(payment: PaymentRequest, request: Request):
    # Проверка идемпотентности в Postgres
    async with pg_pool.acquire() as conn:
        exists = await conn.fetchval("SELECT 1 FROM payments WHERE idempotency_key=$1", str(payment.idempotency_key))
        if exists:
            raise HTTPException(status_code=409, detail="Платеж с таким idempotency_key уже существует")

        # Проверка rate limiting по user_id в Redis (например, не больше 10 запросов в минуту)
        key = f"rate_limit:{payment.user_id}"
        count = await redis.incr(key)
        if count == 1:
            await redis.expire(key, 60)
        if count > 10:
            raise HTTPException(status_code=429, detail="Превышен лимит запросов")

        # Добавляем платеж в базу в статусе "pending"
        await conn.execute("""
            INSERT INTO payments (idempotency_key, amount, currency, user_id, card_number, card_expiry, cvv, status, created_at)
            VALUES ($1,$2,$3,$4,$5,$6,$7,'pending',NOW())
        """,
            str(payment.idempotency_key),
            payment.amount,
            payment.currency,
            payment.user_id,
            payment.card_number,
            payment.card_expiry,
            payment.cvv
        )

    # Отправляем в Kafka
    await kafka_producer.send_and_wait(TOPIC, payment.json().encode("utf-8"))

    return {"status": "accepted", "idempotency_key": payment.idempotency_key}

@app.get("/payments/{idempotency_key}")
async def get_payment_status(idempotency_key: UUID):
    async with pg_pool.acquire() as conn:
        record = await conn.fetchrow("SELECT * FROM payments WHERE idempotency_key=$1", str(idempotency_key))
        if not record:
            raise HTTPException(status_code=404, detail="Платеж не найден")

        return {
            "idempotency_key": record["idempotency_key"],
            "amount": record["amount"],
            "currency": record["currency"],
            "user_id": record["user_id"],
            "status": record["status"],
            "created_at": record["created_at"].isoformat(),
            "updated_at": record["updated_at"].isoformat() if record["updated_at"] else None
        }
