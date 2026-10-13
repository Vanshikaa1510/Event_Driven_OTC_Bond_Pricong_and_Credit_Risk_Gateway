CREATE TABLE bond_inventory_reservations (
    rfq_id UUID PRIMARY KEY REFERENCES rfqs (id),
    isin VARCHAR(12) NOT NULL REFERENCES bond_inventory (isin),
    amount NUMERIC(20, 2) NOT NULL CHECK (amount > 0),
    expires_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_bond_inventory_reservations_active
    ON bond_inventory_reservations (isin, expires_at);
