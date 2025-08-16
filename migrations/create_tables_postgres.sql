CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

CREATE TABLE IF NOT EXISTS merchants (
  id TEXT PRIMARY KEY,
  name TEXT,
  webhook_url TEXT,
  api_key TEXT UNIQUE,
  api_secret TEXT,
  status TEXT,
  created_at BIGINT
);

CREATE TABLE IF NOT EXISTS payments (
  payment_id TEXT PRIMARY KEY,
  merchant_id TEXT REFERENCES merchants(id),
  order_id TEXT,
  amount BIGINT,
  currency TEXT,
  status TEXT,
  acquirer_id TEXT,
  created_at BIGINT,
  updated_at BIGINT
);

CREATE TABLE IF NOT EXISTS idempotency (
  merchant_id TEXT,
  idem_key TEXT,
  response_json TEXT,
  created_at BIGINT,
  PRIMARY KEY (merchant_id, idem_key)
);

CREATE TABLE IF NOT EXISTS webhook_outbox (
  payment_id TEXT PRIMARY KEY,
  delivered BOOLEAN DEFAULT FALSE,
  attempts INT DEFAULT 0,
  last_attempt BIGINT
);
