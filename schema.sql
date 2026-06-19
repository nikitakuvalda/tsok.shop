CREATE TABLE IF NOT EXISTS products (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    price NUMERIC(12, 2) NOT NULL CHECK (price >= 0),
    size TEXT NOT NULL DEFAULT '',
    brand TEXT NOT NULL DEFAULT '',
    image TEXT NOT NULL DEFAULT '',
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO products (id, name, price, size, brand, image) VALUES
    ('pearl-01', 'Foam Mousse Moisture', 96, '150 мл', 'Pearl by Tais', 'img/Pearl1.jpg'),
    ('pearl-02', 'Face Tonic Toning', 93, '150 мл', 'Pearl by Tais', 'img/Pearl2.jpg'),
    ('pearl-03', 'Tonic Youth Restoring', 93, '150 мл', 'Pearl by Tais', 'img/Pearl3.jpg'),
    ('pearl-04', 'Foam Mousse Cleansing', 96, '150 мл', 'Pearl by Tais', 'img/Pearl4.jpg'),
    ('pearl-05', 'Hair Tonic Radiance', 88, '200 мл', 'Pearl by Tais', 'img/Pearl5.jpg'),
    ('pearl-06', 'Velvet Oil Blend', 69, '60 мл', 'Pearl by Tais', 'img/Pearl6.jpg'),
    ('pearl-07', 'Micellar Water Extract Mix', 99, '200 мл', 'Pearl by Tais', 'img/Pearl7.jpg'),
    ('homme-01', 'Face Wash Black', 78, '200 мл', 'INTELEGENTOFF', 'img/INTELEGENT Пенка.png'),
    ('homme-02', 'Toner Control', 89, '150 мл', 'INTELEGENTOFF', 'img/INTELEGENT тоник.png'),
    ('homme-03', 'Beard Oil', 96, '50 мл', 'INTELEGENTOFF', 'img/INTELEGENT масло.png'),
    ('homme-04', 'Beard Wax', 82, '50 мл', 'INTELEGENTOFF', 'img/INTELEGENT Воск.png'),
    ('homme-05', 'Face Serum Black', 134, '30 мл', 'INTELEGENTOFF', 'img/prod-photo-1.jpg'),
    ('homme-06', 'After Shave Balm', 82, '100 мл', 'INTELEGENTOFF', 'img/prod-photo-2.jpg'),
    ('homme-kit-01', 'INTELEGENTOFF Starter Kit', 254, 'Набор 3 продукта', 'INTELEGENTOFF', 'img/logoIntelegent.png')
ON CONFLICT (id) DO UPDATE SET
    name = EXCLUDED.name,
    price = EXCLUDED.price,
    size = EXCLUDED.size,
    brand = EXCLUDED.brand,
    image = EXCLUDED.image,
    updated_at = NOW();

CREATE TABLE IF NOT EXISTS customers (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email TEXT UNIQUE NOT NULL,
    loyalty_tier TEXT NOT NULL DEFAULT 'Silver' CHECK (loyalty_tier IN ('Silver', 'Gold', 'Platinum')),
    tsok_coins NUMERIC(12, 2) NOT NULL DEFAULT 0 CHECK (tsok_coins >= 0),
    referral_code TEXT UNIQUE,
    last_activity_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS subscription_boxes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    customer_id UUID REFERENCES customers(id),
    plan_code TEXT NOT NULL CHECK (plan_code IN ('monthly', '3m', '6m', '12m')),
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'paused', 'cancelled')),
    next_charge_at TIMESTAMPTZ NOT NULL,
    vip_gift TEXT NOT NULL DEFAULT '',
    payment_token_id TEXT,
    bnpl_provider TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS subscription_box_items (
    subscription_id UUID REFERENCES subscription_boxes(id) ON DELETE CASCADE,
    product_id TEXT REFERENCES products(id),
    qty INTEGER NOT NULL CHECK (qty > 0),
    PRIMARY KEY (subscription_id, product_id)
);

CREATE TABLE IF NOT EXISTS loyalty_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    customer_id UUID REFERENCES customers(id),
    order_id TEXT,
    event_type TEXT NOT NULL,
    coins_delta NUMERIC(12, 2) NOT NULL,
    available_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ,
    anti_fraud_fingerprint TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
