# ---------- load_test.sh ----------
#!/usr/bin/env bash
set -euo pipefail

# >>>>>>>>>>>>>> НАСТРОЙКИ (переопределяй через env) <<<<<<<<<<<<<<
API_URL="${API_URL:-http://localhost:8000}"
API_KEY="${API_KEY:-sk_live_0b85ac22a90a4019b0e79d07b672cf34}"   # ключ мерчанта для /v1/payments
ADMIN_TOKEN="${ADMIN_TOKEN:-dev-admin}"                           # токен админ-API для /admin-api/*
POSTGRES_CONT="${POSTGRES_CONT:-postgres}"                        # имя сервиса/контейнера postgres
DB_NAME="${DB_NAME:-payments}"

post_json='{"amount":101,"currency":"USD","order_id":"lt"}'

echo "[i] API_URL=$API_URL"
echo "[i] API_KEY=$API_KEY"
echo "[i] ADMIN_TOKEN=$ADMIN_TOKEN"
echo "[i] POSTGRES_CONT=$POSTGRES_CONT DB_NAME=$DB_NAME"
echo

# helper: psql через docker compose (если не в infra/, попробуем docker exec)
psql_exec () {
  local sql="$1"
  if docker compose ps >/dev/null 2>&1; then
    docker compose exec -T "$POSTGRES_CONT" psql -U postgres -d "$DB_NAME" -c "$sql"
  else
    docker exec -i "$POSTGRES_CONT" psql -U postgres -d "$DB_NAME" -c "$sql"
  fi
}

# helper: проверить, что в merchants есть наш API_KEY; если нет — создать через админ-API
ensure_merchant () {
  echo "[i] Проверяю, что в БД есть мерчант с заданным API_KEY..."
  # попробуем получить список через админ-API (если токен ок)
  local list_code
  list_code=$(curl -s -o /tmp/merchants.json -w '%{http_code}' \
    -H "Authorization: Bearer $ADMIN_TOKEN" "$API_URL/admin-api/merchants" || true)

  if [[ "$list_code" == "200" ]]; then
    if grep -q "\"api_key\":\s*\"$API_KEY\"" /tmp/merchants.json; then
      echo "[i] Мерчант с API_KEY уже существует"
      return 0
    fi
    echo "[i] Мерчанта с таким ключом нет — создаю через админ-API..."
    local create_code
    create_code=$(curl -s -o /tmp/merchant_create.json -w '%{http_code}' \
      -X POST "$API_URL/admin-api/merchants" \
      -H "Authorization: Bearer $ADMIN_TOKEN" \
      -H "Content-Type: application/json" \
      -d "{\"webhook_url\":\"http://merchant_webhook:8080/webhook\",\"api_secret\":\"secret\",\"api_key\":\"$API_KEY\"}" || true)
    if [[ "$create_code" == "201" || "$create_code" == "409" ]]; then
      echo "[i] Мерчант создан или уже существовал (HTTP $create_code)"
    else
      echo "[!] Не удалось создать мерчанта через админ-API (HTTP $create_code), продолжаю без авто-создания."
      echo "    Ответ: $(cat /tmp/merchant_create.json)"
    fi
  else
    echo "[!] Админ-API недоступен или неверный токен (HTTP $list_code). Пропускаю авто-создание мерчанта."
  fi
}

# 0) Healthcheck API
echo "[i] Проверяю /health..."
curl -fsS "$API_URL/health" && echo -e "\n[i] /health OK\n" || { echo "[!] API недоступен"; exit 1; }

# 0.1) Убедимся, что есть мерчант с нужным API_KEY (опционально, если админ-API доступен)
ensure_merchant || true

# ---------- ТЕСТ 1: ИДЕМПОТЕНТНОСТЬ (один ключ) ----------
echo "=== ТЕСТ 1: 200 параллельных запросов с одним Idempotency-Key ==="
IDEMP1="idem-same-key-$(date +%s)"
echo "[i] Idempotency-Key=$IDEMP1"
echo "[i] Шлю 200 POST с конкуренцией 50, собираю распределение HTTP кодов..."

# выведем распределение HTTP-кодов
seq 200 | xargs -I{} -P 50 sh -c \
"curl -s -o /dev/null -w '%{http_code}\n' \
  -X POST '$API_URL/v1/payments' \
  -H 'Content-Type: application/json' \
  -H 'X-API-Key: $API_KEY' \
  -H 'Idempotency-Key: $IDEMP1' \
  -d '$post_json'" \
| sort | uniq -c

# Проверка в БД: COUNT должен быть 1
echo
echo "[i] Проверяю в БД, что запись по '$IDEMP1' одна:"
psql_exec "
SELECT idempotency_key, COUNT(*) AS cnt
FROM payments
WHERE idempotency_key = '$IDEMP1'
GROUP BY 1;"

# ---------- ТЕСТ 2: 100 уникальных ключей ----------
echo
echo "=== ТЕСТ 2: 100 запросов с уникальными Idempotency-Key ==="
added=0
for i in $(seq 1 100); do
  IDEMP2="idem-unique-$i-$(date +%s)"
  curl -s -o /dev/null -X POST "$API_URL/v1/payments" \
    -H "Content-Type: application/json" \
    -H "X-API-Key: $API_KEY" \
    -H "Idempotency-Key: $IDEMP2" \
    -d "$post_json" &
  added=$((added+1))
done
wait
echo "[i] Отправлено $added запросов. Проверяю, сколько их попало в БД..."
psql_exec "
SELECT COUNT(*) AS unique_rows
FROM payments
WHERE idempotency_key LIKE 'idem-unique-%';"

# ---------- ТЕСТ 3 (опционально): oha 60s ----------
echo
if command -v oha >/dev/null 2>&1; then
  echo "=== ТЕСТ 3: oha 60s (-c 10, -q 2) с уникальными ключами ==="
  oha -z 60s -c 10 -q 2 -m POST \
    -H "Content-Type: application/json" \
    -H "X-API-Key: $API_KEY" \
    -H "Idempotency-Key: oha-{{i}}-$(date +%s)" \
    -d "$post_json" \
    "$API_URL/v1/payments"
else
  echo "[i] oha не найден. Пропускаю тест 3. Установить: brew install oha"
fi

# ---------- Сводка ----------
echo
echo "=== Сводка по статусам в БД ==="
psql_exec "
SELECT status, COUNT(*)
FROM payments
GROUP BY status
ORDER BY 2 DESC;"

echo
echo "=== TOP 10 последних платежей ==="
psql_exec "
SELECT payment_id, amount, currency, status, to_timestamp(created_at) AS created
FROM payments
ORDER BY created_at DESC
LIMIT 10;"

echo
echo "[✓] Нагрузочные тесты завершены."
# ---------- /load_test.sh ----------
