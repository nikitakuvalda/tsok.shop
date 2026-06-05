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
