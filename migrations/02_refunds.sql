-- 02_refunds.sql
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
