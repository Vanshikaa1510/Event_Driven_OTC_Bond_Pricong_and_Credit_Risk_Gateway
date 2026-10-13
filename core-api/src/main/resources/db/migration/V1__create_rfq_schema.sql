CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE rfqs (
    id UUID PRIMARY KEY,
    client_id VARCHAR(64) NOT NULL,
    idempotency_key VARCHAR(128) NOT NULL,
    raw_text TEXT NOT NULL,
    status VARCHAR(32) NOT NULL,
    result_json TEXT,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT uk_rfq_client_idempotency UNIQUE (client_id, idempotency_key)
);

CREATE INDEX idx_rfqs_status_created_at ON rfqs (status, created_at DESC);
CREATE INDEX idx_rfqs_client_created_at ON rfqs (client_id, created_at DESC);

CREATE TABLE rfq_outbox (
    id UUID PRIMARY KEY,
    aggregate_id UUID NOT NULL REFERENCES rfqs (id),
    event_type VARCHAR(64) NOT NULL,
    payload TEXT NOT NULL,
    status VARCHAR(16) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    published_at TIMESTAMPTZ
);

CREATE INDEX idx_rfq_outbox_pending ON rfq_outbox (created_at) WHERE status = 'PENDING';

CREATE TABLE client_credit_limits (
    client_id VARCHAR(64) PRIMARY KEY,
    credit_limit NUMERIC(20, 2) NOT NULL CHECK (credit_limit >= 0),
    current_exposure NUMERIC(20, 2) NOT NULL CHECK (current_exposure >= 0),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE credit_reservations (
    rfq_id UUID PRIMARY KEY REFERENCES rfqs (id),
    client_id VARCHAR(64) NOT NULL REFERENCES client_credit_limits (client_id),
    amount NUMERIC(20, 2) NOT NULL CHECK (amount > 0),
    expires_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_credit_reservations_active ON credit_reservations (client_id, expires_at);

CREATE TABLE bond_inventory (
    isin VARCHAR(12) PRIMARY KEY,
    issuer VARCHAR(160) NOT NULL,
    maturity_year SMALLINT NOT NULL,
    available_notional NUMERIC(20, 2) NOT NULL CHECK (available_notional >= 0),
    hedge_capacity NUMERIC(20, 2) NOT NULL CHECK (hedge_capacity >= 0),
    market_mid_yield NUMERIC(9, 6) NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE client_credit_documents (
    id BIGSERIAL PRIMARY KEY,
    client_id VARCHAR(64) NOT NULL REFERENCES client_credit_limits (client_id),
    source_name VARCHAR(256) NOT NULL,
    content TEXT NOT NULL,
    embedding VECTOR(384),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_credit_docs_client ON client_credit_documents (client_id);
CREATE INDEX idx_credit_docs_embedding ON client_credit_documents USING hnsw (embedding vector_cosine_ops);

INSERT INTO client_credit_limits (client_id, credit_limit, current_exposure)
VALUES ('DEMO-001', 100000000.00, 25000000.00);

INSERT INTO bond_inventory (isin, issuer, maturity_year, available_notional, hedge_capacity, market_mid_yield)
VALUES ('US037833EF47', 'Apple Inc.', 2030, 20000000.00, 40000000.00, 4.350000);

INSERT INTO client_credit_documents (client_id, source_name, content)
VALUES
    ('DEMO-001', 'demo-credit-memo.txt', 'Synthetic demo client. Approved corporate bond exposure limit is USD 100 million. Current drawn exposure is USD 25 million. This synthetic memo is for local testing only.'),
    ('DEMO-001', 'demo-trading-guidelines.txt', 'Synthetic demo client may trade investment-grade USD corporate bonds subject to available credit and instrument-level suitability checks. This synthetic text is not real client documentation.');