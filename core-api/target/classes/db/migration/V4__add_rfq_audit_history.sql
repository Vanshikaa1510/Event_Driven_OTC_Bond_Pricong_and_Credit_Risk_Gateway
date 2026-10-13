CREATE TABLE rfq_audit_events (
    id BIGSERIAL PRIMARY KEY,
    rfq_id UUID NOT NULL REFERENCES rfqs (id),
    event_type VARCHAR(64) NOT NULL,
    previous_status VARCHAR(32),
    new_status VARCHAR(32) NOT NULL,
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_rfq_audit_history ON rfq_audit_events (rfq_id, occurred_at, id);

CREATE FUNCTION reject_rfq_audit_mutation() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'RFQ audit history is append-only';
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_rfq_audit_append_only
    BEFORE UPDATE OR DELETE ON rfq_audit_events
    FOR EACH ROW EXECUTE FUNCTION reject_rfq_audit_mutation();

INSERT INTO rfq_audit_events (rfq_id, event_type, previous_status, new_status, occurred_at)
SELECT id, 'LEGACY_STATE_SNAPSHOT', NULL, status, updated_at
FROM rfqs;
