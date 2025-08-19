#!/usr/bin/env bash
set -euo pipefail

API_KEY="${API_KEY:-sk_live_0b85ac22a90a4019b0e79d07b672cf34}"
ADMIN_TOKEN="${ADMIN_TOKEN:-dev-admin}"

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
INFRA="$ROOT_DIR/infra"

echo "== 🧹 Полная очистка Docker и данных Postgres =="
cd "$INFRA"
docker compose down -v || true
rm -rf ./postgres-data

echo "== 🔧 Пересборка и запуск базовых сервисов (postgres, kafka) =="
docker compose up -d --build postgres kafka

echo "== ⏳ Ожидаю готовности Postgres..."
until docker compose exec -T postgres pg_isready -U postgres -d payments >/dev/null 2>&1; do
  sleep 1
done
echo "   Postgres OK"

echo "== ⏳ Ожидаю готовности Kafka..."
# ждём, когда скрипты Kafka заработают
until docker compose exec -T kafka bash -lc "/opt/bitnami/kafka/bin/kafka-topics.sh --bootstrap-server localhost:9092 --list >/dev/null 2>&1"; do
  sleep 2
done
echo "   Kafka OK"

echo "== 🗃️ Создаю тему Kafka 'payments' (если нет)..."
docker compose exec -T kafka bash -lc "/opt/bitnami/kafka/bin/kafka-topics.sh --create \
  --topic payments --if-not-exists --bootstrap-server localhost:9092 --replication-factor 1 --partitions 1" || true

echo "== 🐍 Пересборка API (важно: Dockerfile в api/ должен COPY . .)"
docker compose up -d --build api

echo "== 🧱 Накатываю схему БД..."
docker compose exec -T postgres psql -U postgres -d payments -v ON_ERROR_STOP=1 <<'SQL'
CREATE TABLE IF NOT EXISTS merchants (
  id UUID PRIMARY KEY,
  webhook_url TEXT NOT NULL,
  api_secret TEXT NOT NULL,
  api_key TEXT UNIQUE
);
ALTER TABLE merchants ALTER COLUMN api_key SET NOT NULL;

CREATE TABLE IF NOT EXISTS payments (
  payment_id UUID PRIMARY KEY,
  merchant_id UUID REFERENCES merchants(id) ON DELETE SET NULL,
  amount INTEGER NOT NULL,
  currency TEXT NOT NULL,
  status TEXT NOT NULL,
  order_id TEXT,
  idempotency_key TEXT,
  created_at BIGINT NOT NULL,
  updated_at BIGINT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS payments_uniq_idem
  ON payments(merchant_id, idempotency_key) WHERE idempotency_key IS NOT NULL;

CREATE TABLE IF NOT EXISTS webhook_outbox (
  payment_id UUID PRIMARY KEY REFERENCES payments(payment_id) ON DELETE CASCADE,
  delivered BOOLEAN NOT NULL DEFAULT FALSE
);
SQL

echo "== 🚀 Запускаю оставшиеся сервисы..."
docker compose up -d --build connector acquirer webhook_dispatcher merchant_webhook admin dashboard

echo "== ✅ Проверка /health API"
curl -fsS http://localhost:8000/health && echo

echo "== 👤 Создаю мерчанта с фиксированным API_KEY (или получаю существующего)..."
set +e
CREATE_OUT=$(curl -s -X POST http://localhost:8000/admin-api/merchants \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"webhook_url\":\"http://merchant_webhook:8080/webhook\",\"api_secret\":\"secret\",\"api_key\":\"$API_KEY\"}")
RET=$?
set -e

if [[ $RET -ne 0 || "$CREATE_OUT" == *"Integrity error"* || "$CREATE_OUT" == *"409"* ]]; then
  echo "   Мерчант с таким ключом уже существует — ок"
else
  echo "   Создан мерчант: $CREATE_OUT"
fi

echo "== 📋 Текущие мерчанты:"
curl -s -H "Authorization: Bearer $ADMIN_TOKEN" http://localhost:8000/admin-api/merchants | jq

echo "== 💳 Тестовый платёж (должен стать processing)..."
curl -s -X POST http://localhost:8000/v1/payments \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $API_KEY" \
  -H "Idempotency-Key: reset-check-$(date +%s)" \
  -d '{"amount":101,"currency":"USD","order_id":"ui"}' | jq

echo "== 🗄️ Проверяю записи в БД (TOP 5)..."
docker compose exec -T postgres psql -U postgres -d payments -c \
"SELECT payment_id, amount, currency, status, to_timestamp(created_at) AS created
 FROM payments ORDER BY created_at DESC LIMIT 5;"

echo "== 📊 /admin-api/stats напрямую и через фронтовый прокси..."
curl -s -H "Authorization: Bearer $ADMIN_TOKEN" http://localhost:8000/admin-api/stats | jq
curl -s -H "Authorization: Bearer $ADMIN_TOKEN" http://localhost:8081/api/admin-api/stats | jq

echo "== ✅ Готово. Открой UI: http://localhost:8081/ (введи токен $ADMIN_TOKEN)"
