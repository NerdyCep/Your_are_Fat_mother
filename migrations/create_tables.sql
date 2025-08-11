CREATE TABLE IF NOT EXISTS payments (
    id SERIAL PRIMARY KEY,
    idempotency_key VARCHAR(36) UNIQUE NOT NULL,
    amount NUMERIC(12, 2) NOT NULL,
    currency VARCHAR(3) NOT NULL,
    user_id VARCHAR(64) NOT NULL,
    card_number VARCHAR(19) NOT NULL,
    card_expiry VARCHAR(5) NOT NULL,
    cvv VARCHAR(4) NOT NULL,
    status VARCHAR(20) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE
);

CREATE INDEX idx_payments_user_id ON payments(user_id);
CREATE INDEX idx_payments_status ON payments(status);
