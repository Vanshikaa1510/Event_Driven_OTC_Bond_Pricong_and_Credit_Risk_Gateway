INSERT INTO client_credit_limits (client_id, credit_limit, current_exposure)
VALUES
    ('DEMO-002', 50000000.00, 12500000.00),
    ('DEMO-003', 150000000.00, 85000000.00),
    ('DEMO-004', 25000000.00, 5000000.00)
ON CONFLICT (client_id) DO NOTHING;

INSERT INTO bond_inventory (
    isin, issuer, maturity_year, available_notional, hedge_capacity, market_mid_yield
)
VALUES
    ('XSDEMO2031M1', 'Microsoft Corp.', 2031, 18000000.00, 35000000.00, 4.180000),
    ('XSDEMO2029A1', 'Acme Robotics Inc.', 2029, 12000000.00, 18000000.00, 5.250000),
    ('XSDEMO2032N1', 'Northstar Energy Holdings', 2032, 8000000.00, 22000000.00, 6.100000),
    ('XSDEMO2028C1', 'Cedar Retail Group', 2028, 15000000.00, 10000000.00, 5.700000)
ON CONFLICT (isin) DO NOTHING;

INSERT INTO client_credit_documents (client_id, source_name, content)
VALUES
    ('DEMO-002', 'demo-002-credit-memo.txt', 'Synthetic demo client DEMO-002. Approved corporate bond exposure limit is USD 50 million. Current drawn exposure is USD 12.5 million. Internal counterparty assessment is investment grade, subject to instrument and concentration limits. No settlement failures are recorded in this synthetic profile. For software demonstration only.'),
    ('DEMO-002', 'demo-002-trading-guidelines.txt', 'Synthetic trading guidelines for DEMO-002: USD corporate bonds are permitted. Escalate concentrated or below-investment-grade exposures for manual review. All settlement figures and policy statements are fictional demonstration data.'),
    ('DEMO-003', 'demo-003-credit-memo.txt', 'Synthetic demo client DEMO-003. Approved corporate bond exposure limit is USD 150 million. Current drawn exposure is USD 85 million, leaving limited headroom relative to the requested trade size. Internal counterparty assessment is moderate risk. Require conservative sizing and recheck aggregate exposure. For software demonstration only.'),
    ('DEMO-003', 'demo-003-trading-guidelines.txt', 'Synthetic trading guidelines for DEMO-003: corporate bond activity is permitted within recorded exposure limits. Large trades, issuer concentration, and high-yield instruments require heightened review. All settlement figures and policy statements are fictional demonstration data.'),
    ('DEMO-004', 'demo-004-credit-memo.txt', 'Synthetic demo client DEMO-004. Approved corporate bond exposure limit is USD 25 million. Current drawn exposure is USD 5 million. Internal counterparty assessment is watch-list / moderate risk; review liquidity and proposed trade size carefully. For software demonstration only.'),
    ('DEMO-004', 'demo-004-trading-guidelines.txt', 'Synthetic trading guidelines for DEMO-004: smaller USD corporate bond trades are permitted subject to available headroom. Any high-yield or concentrated exposure requires manual review. All settlement figures and policy statements are fictional demonstration data.')
ON CONFLICT DO NOTHING;
