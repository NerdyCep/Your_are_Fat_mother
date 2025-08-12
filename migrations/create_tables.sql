-- migrations/create_tables.sql
-- (этот файл демонстрационный; в текущем MVP используем sqlite, но сюда можно поместить SQL для Postgres)
CREATE TABLE payments (
  payment_id TEXT PRIMARY KEY,
  merchant_id TEXT,
  amount INTEGER,
  currency TEXT,
  status TEXT,
  created_at INTEGER,
  updated_at INTEGER
);
