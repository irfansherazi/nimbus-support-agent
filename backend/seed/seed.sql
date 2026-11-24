-- Idempotent demo seed. Invoice dates are relative to CURRENT_DATE so the demo never ages out of refund windows.
-- Re-applied on every deploy (python -m app.cli release).

INSERT INTO policy_limits (tier, max_refund_cents, window_days) VALUES
    ('free', 0, 0),
    ('pro', 20000, 30),
    ('enterprise', 100000, 60)
ON CONFLICT (tier) DO UPDATE SET max_refund_cents = EXCLUDED.max_refund_cents, window_days = EXCLUDED.window_days;

INSERT INTO customers (id, name, pin, tier, contract_status, email, phone, billing_contact, chaos_flags) VALUES
    ('C-1001', 'Dana Lee',    '4321', 'pro',        'active',   'dana@example.com',  '+14155550101', 'Dana Lee',     '{}'),
    ('C-1002', 'Omar Haddad', '2468', 'enterprise', 'active',   'omar@example.com',  '+14155550102', 'Finance Team', '{}'),
    ('C-1003', 'Priya Shah',  '1357', 'free',       'active',   'priya@example.com', '+14155550103', 'Priya Shah',   '{}'),
    ('C-1004', 'Marco Rossi', '8642', 'pro',        'expired',  'marco@example.com', '+14155550104', 'Marco Rossi',  '{}'),
    ('C-1005', 'Aiko Tanaka', '9753', 'enterprise', 'past_due', 'aiko@example.com',  '+14155550105', 'Accounts',     '{}'),
    ('C-1006', 'Sam Carter',  '1122', 'pro',        'active',   'sam@example.com',   '+14155550106', 'Sam Carter',
        '{"list_invoices": "always_fail"}'),
    ('C-1007', 'Lena Novak',  '3344', 'free',       'expired',  'lena@example.com',  '+14155550107', 'Lena Novak',   '{}'),
    ('C-1008', 'Ben Okafor',  '5566', 'enterprise', 'active',   'ben@example.com',   '+14155550108', 'Ops Team',     '{}')
ON CONFLICT (id) DO UPDATE SET
    name = EXCLUDED.name, pin = EXCLUDED.pin, tier = EXCLUDED.tier, contract_status = EXCLUDED.contract_status,
    email = EXCLUDED.email, phone = EXCLUDED.phone, billing_contact = EXCLUDED.billing_contact,
    chaos_flags = EXCLUDED.chaos_flags;

INSERT INTO invoices (id, customer_id, amount_cents, issued_at, description) VALUES
    ('INV-2207', 'C-1001',   4900, CURRENT_DATE - 10, 'Pro plan, monthly'),
    ('INV-2150', 'C-1001',   4900, CURRENT_DATE - 40, 'Pro plan, monthly'),
    ('INV-2099', 'C-1001',  49000, CURRENT_DATE - 20, 'Pro plan, annual'),
    ('INV-3101', 'C-1002', 120000, CURRENT_DATE - 15, 'Enterprise plan, monthly'),
    ('INV-3050', 'C-1002',  80000, CURRENT_DATE - 45, 'Enterprise seats add-on'),
    ('INV-1201', 'C-1003',      0, CURRENT_DATE - 5,  'Free plan'),
    ('INV-1202', 'C-1003',   1000, CURRENT_DATE - 5,  'Extra storage add-on'),
    ('INV-2301', 'C-1004',   4900, CURRENT_DATE - 12, 'Pro plan, monthly'),
    ('INV-3201', 'C-1005',  95000, CURRENT_DATE - 8,  'Enterprise plan, monthly'),
    ('INV-2401', 'C-1006',   4900, CURRENT_DATE - 6,  'Pro plan, monthly'),
    ('INV-3301', 'C-1008',  30000, CURRENT_DATE - 3,  'Enterprise support add-on')
ON CONFLICT (id) DO UPDATE SET
    customer_id = EXCLUDED.customer_id, amount_cents = EXCLUDED.amount_cents,
    issued_at = EXCLUDED.issued_at, description = EXCLUDED.description;
