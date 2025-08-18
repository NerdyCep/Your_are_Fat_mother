# High Risk Payment Aggregator

## Быстрый старт локально с Docker Compose

1. Склонировать репозиторий:

```bash
git clone https://github.com/NerdyCep/Your_are_Fat_mother.git
cd Your_are_Fat_mother/infra

Запустить окружение:
docker compose up -d --build

Применить миграции (создать таблицы):
⚠️ Пока автоматических миграций нет, создаём схему вручную (один раз после чистого старта):
docker compose exec -T postgres psql -U postgres -d payments <<'SQL'
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

CREATE TABLE IF NOT EXISTS merchants (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  webhook_url TEXT NOT NULL,
  api_secret  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS payments (
  payment_id       UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  merchant_id      UUID REFERENCES merchants(id) ON DELETE RESTRICT,
  amount           INTEGER NOT NULL CHECK (amount > 0),
  currency         TEXT    NOT NULL,
  status           TEXT    NOT NULL CHECK (status IN ('new','processing','approved','declined','failed')),
  idempotency_key  TEXT UNIQUE,
  created_at       BIGINT  NOT NULL DEFAULT (EXTRACT(EPOCH FROM NOW()))
);

CREATE TABLE IF NOT EXISTS webhook_outbox (
  payment_id UUID PRIMARY KEY REFERENCES payments(payment_id) ON DELETE CASCADE,
  delivered  BOOLEAN NOT NULL DEFAULT FALSE
);

INSERT INTO merchants (id, webhook_url, api_secret)
VALUES (uuid_generate_v4(), 'http://merchant_webhook:8080/webhook', 'secret')
ON CONFLICT DO NOTHING;
SQL

API будет доступен на http://localhost:8000
Можно отправлять платежи на POST /payments
Connector и симулятор эквайера запустятся автоматически в контейнерах.

Структура проекта
api/ — API сервис
connector/ — Kafka consumer, отправка платежей в эквайер
acquirer_simulator/ — тестовый эквайер
merchant_webhook/ — тестовый приёмник вебхуков
webhook_dispatcher/ — сервис отправки вебхуков
infra/ — инфраструктура Docker Compose
migrations/ — SQL миграции (пока вручную)

Пример запроса
curl -X POST http://localhost:8000/payments \
  -H "Content-Type: application/json" \
  -H "X-API-Key: sk_live_0b85ac22a90a4019b0e79d07b672cf34" \
  -H "Idempotency-Key: idem-123" \
  -d '{"amount":100,"currency":"USD","order_id":"test"}'

Тестирование нагрузки
Для запуска встроенного теста:
./load_test.sh

Troubleshooting: Postgres / миграции / schema not found
Если при запуске сервисов или тестов видишь:
ERROR:  relation "payments" does not exist

или Postgres падает, действуй так:
1. Полный сброс окружения
cd infra
docker compose down -v
rm -rf ./postgres-data   # если используется bind-mount
docker compose up -d --build

2. Создать схему БД
Выполни SQL из раздела «Применить миграции» выше.
3. Проверить API
curl http://localhost:8000/health
# должен вернуть {"status":"ok"}
4. Запуск тестов
./load_test.sh
5. Типичные ошибки
relation "payments" does not exist → повтори шаг 2 (создай схему).
curl: (56) Recv failure: Connection reset by peer на /health → Postgres не поднялся, сделай шаг 1.
404 на /v1/payments → уточни префикс эндпоинтов (/payments vs /v1/payments).
💡 В будущем можно автоматизировать миграции:
через Alembic (alembic upgrade head в контейнере api),
или через init SQL (infra/postgres-init.sql, монтируемый в /docker-entrypoint-initdb.d/).

---

Хочешь, я ещё сделаю для тебя минимальный SQL-файл `infra/postgres-init.sql`, чтобы он 