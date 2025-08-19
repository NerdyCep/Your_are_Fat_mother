#!/usr/bin/env bash
set -euo pipefail

DB_HOST="${DB_HOST:-postgres}"
DB_PORT="${DB_PORT:-5432}"
DB_NAME="${DB_NAME:-payments}"
DB_USER="${DB_USER:-postgres}"
DB_PASSWORD="${DB_PASSWORD:-postgres}"

echo "[api] waiting for postgres at ${DB_HOST}:${DB_PORT}..."
for i in $(seq 1 60); do
  if PGPASSWORD="$DB_PASSWORD" psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -c "select 1" >/dev/null 2>&1; then
    echo "[api] postgres is up"
    break
  fi
  sleep 1
done

if ! PGPASSWORD="$DB_PASSWORD" psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -c "select 1" >/dev/null 2>&1; then
  echo "[api] ERROR: postgres is not reachable" >&2
  exit 1
fi

MIG_DIR="/app/migration"

if [ -d "$MIG_DIR" ]; then
  echo "[api] migration dir found: $MIG_DIR"
  ls -la "$MIG_DIR" || true
  echo "[api] applying migrations (*.sql) in lexical order"
  find "$MIG_DIR" -maxdepth 1 -type f -name "*.sql" | sort | while read -r f; do
    echo "[api]   -> $f"
    PGPASSWORD="$DB_PASSWORD" psql -v ON_ERROR_STOP=1 \
      -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -f "$f"
  done
else
  echo "[api] WARNING: $MIG_DIR not found. Applying built-in refunds DDL…"
  PGPASSWORD="$DB_PASSWORD" psql -v ON_ERROR_STOP=1 \
    -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" <<'SQL'
CREATE TABLE IF NOT EXISTS refunds (
  refund_id   uuid PRIMARY KEY,
  payment_id  uuid NOT NULL REFERENCES payments(payment_id) ON DELETE CASCADE,
  amount      integer NOT NULL CHECK (amount > 0),
  currency    varchar(8) NOT NULL,
  status      varchar(16) NOT NULL CHECK (status IN ('requested','succeeded','failed')),
  reason      varchar(200),
  created_at  integer NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_refunds_payment ON refunds(payment_id);
CREATE INDEX IF NOT EXISTS idx_refunds_created ON refunds(created_at);
CREATE INDEX IF NOT EXISTS idx_refunds_status  ON refunds(status);
SQL
fi

echo "[api] starting uvicorn..."
exec uvicorn api.main:app --host 0.0.0.0 --port 8000
