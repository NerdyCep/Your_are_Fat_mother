import asyncio
import aiokafka
import asyncpg
import aiohttp
import json
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("connector_worker")

KAFKA_TOPIC = "payments"
KAFKA_BOOTSTRAP = "localhost:9092"
POSTGRES_DSN = "postgresql://user:password@localhost/payments"
ACQUIRER_URL = "http://localhost:8001/process_payment"  # симулятор эквайера

async def process_payment(message, pg_pool, session):
    payment = json.loads(message.value.decode())
    idempotency_key = payment["idempotency_key"]

    async with pg_pool.acquire() as conn:
        record = await conn.fetchrow("SELECT status FROM payments WHERE idempotency_key=$1", idempotency_key)
        if not record:
            logger.warning(f"Платеж не найден: {idempotency_key}")
            return
        if record["status"] != "pending":
            logger.info(f"Платеж уже обработан: {idempotency_key} статус {record['status']}")
            return

        # Отправляем платеж в эквайер
        try:
            async with session.post(ACQUIRER_URL, json=payment, timeout=10) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    status = data.get("status", "failed")
                else:
                    status = "failed"
        except Exception as e:
            logger.error(f"Ошибка при отправке в эквайер: {e}")
            status = "failed"

        # Обновляем статус платежа
        await conn.execute("UPDATE payments SET status=$1, updated_at=NOW() WHERE idempotency_key=$2", status, idempotency_key)
        logger.info(f"Платеж {idempotency_key} обновлён статусом {status}")

async def main():
    pg_pool = await asyncpg.create_pool(dsn=POSTGRES_DSN)
    consumer = aiokafka.AIOKafkaConsumer(
        KAFKA_TOPIC,
        bootstrap_servers=KAFKA_BOOTSTRAP,
        group_id="payment_connector_group"
    )
    await consumer.start()

    async with aiohttp.ClientSession() as session:
        try:
            async for message in consumer:
                await process_payment(message, pg_pool, session)
        finally:
            await consumer.stop()
            await pg_pool.close()

if __name__ == "__main__":
    asyncio.run(main())
