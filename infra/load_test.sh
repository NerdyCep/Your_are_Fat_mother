# ---------- load_test.sh ----------
#!/usr/bin/env bash
set -euo pipefail

# >>>>>>>>>>>>>> НАСТРОЙКИ <<<<<<<<<<<<<<
API_KEY="${API_KEY:-sk_live_0b85ac22a90a4019b0e79d07b672cf34}"  # можно переопределить через окружение
API_URL="${API_URL:-http://localhost:8000}"
POSTGRES_CONT="${POSTGRES_CONT:-postgres}"                       # имя контейнера postgres
DB_NAME="${DB_NAME:-payments}"

echo "[i] API_URL=$API_URL"
echo "[i] API_KEY=$API_KEY"
echo "[i] POSTGRES_CONT=$POSTGRES_CONT DB_NAME=$DB_NAME"
echo

post_json='{"amount":101,"currency":"USD","order_id":"lt"}'

# Маленькая проверка API
echo "[i] Проверяю /health..."
curl -fsS "$API_URL/health" && echo -e "\n[i] /health OK\n" || { echo "[!] API недоступен"; exit 1; }

# ---------- ТЕСТ 1: ИДЕМПОТЕНТНОСТЬ (OD) ----------
echo "=== ТЕСТ 1: 200 параллельных запросов с одним Idempotency-Key ==="
IDEMP1="idem-same-key-$(date +%s)"
echo "[i] Idempotency-Key=$IDEMP1"

# 200 запросов, конкуренция 50. Если нет seq или xargs на mac — установи coreutils/brew (обычно уже есть).
seq 200 | xargs -I{} -P 50 sh -c \
"curl -s -o /dev/null -w '%{http_code}\n' \
  -X POST '$API_URL/v1/payments' \
  -H 'Content-Type: application/json' \
  -H 'X-API-Key: $API_KEY' \
  -H 'Idempotency-Key: $IDEMP1' \
  -d '$post_json' >/dev/null"

# Проверка в БД: COUNT должен быть 1
echo
echo "[i] Проверяю в БД, что запись по '$IDEMP1' одна:"
docker exec -it "$POSTGRES_CONT" psql -U postgres -d "$DB_NAME" -c \
"SELECT idempotency_key, COUNT(*) AS cnt
 FROM payments
 WHERE idempotency_key = '$IDEMP1'
 GROUP BY 1;"

# ---------- ТЕСТ 2: 100 UNIQUE KEY ----------
echo
echo "=== ТЕСТ 2: 100 запросов с уникальными Idempotency-Key ==="
added=0
for i in $(seq 1 100); do
  IDEMP2="idem-unique-$i-$(date +%s)"
  # отправляем асинхронно в фоне
  curl -s -o /dev/null -X POST "$API_URL/v1/payments" \
    -H "Content-Type: application/json" \
    -H "X-API-Key: $API_KEY" \
    -H "Idempotency-Key: $IDEMP2" \
    -d "$post_json" &
  added=$((added+1))
done
wait
echo "[i] Отправлено $added запросов. Проверяю, сколько их попало в БД..."

# Посчитаем, сколько различных ключей с нашим префиксом:
docker exec -it "$POSTGRES_CONT" psql -U postgres -d "$DB_NAME" -c \
"SELECT COUNT(*) AS unique_rows
 FROM payments
 WHERE idempotency_key LIKE 'idem-unique-%';"

# ---------- ТЕСТ 3 (ОПЦИОНАЛЬНО): oha длительный прогон ----------
echo
if command -v oha >/dev/null 2>&1; then
  echo "=== ТЕСТ 3: oha 60s (-c 10, -q 2) с уникальными ключами ==="
  # В oha можно шаблон {{i}} вписывать. Для идемпотентности лучше уникальные ключи
  oha -z 60s -c 10 -q 2 -m POST \
    -H "Content-Type: application/json" \
    -H "X-API-Key: $API_KEY" \
    -H "Idempotency-Key: oha-{{i}}-$(date +%s)" \
    -d "$post_json" \
    "$API_URL/v1/payments"
else
  echo "[i] oha не найден. Пропускаю тест 3. Установить: brew install oha"
fi

# ---------- СВОДНЫЕ ПРОВЕРКИ ----------
echo
echo "=== Сводка по статусам ==="
docker exec -it "$POSTGRES_CONT" psql -U postgres -d "$DB_NAME" -c \
"SELECT status, COUNT(*) 
 FROM payments 
 GROUP BY status 
 ORDER BY 2 DESC;"

echo
echo "=== TOP 10 последних платежей ==="
docker exec -it "$POSTGRES_CONT" psql -U postgres -d "$DB_NAME" -c \
"SELECT payment_id, amount, currency, status, to_timestamp(created_at) AS created
 FROM payments
 ORDER BY created_at DESC
 LIMIT 10;"

echo
echo "[✓] Нагрузочные тесты завершены."
# ---------- /load_test.sh ----------

