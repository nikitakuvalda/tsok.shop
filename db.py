import os
from contextlib import contextmanager
from decimal import Decimal

try:
    import psycopg
    from psycopg.rows import dict_row
except ImportError:  # pragma: no cover - local environments install requirements.txt
    psycopg = None
    dict_row = None

from cache import PRODUCT_CACHE_TTL, cache_get_json, cache_set_json

DATABASE_URL = os.getenv("DATABASE_URL") or os.getenv("POSTGRES_URL") or os.getenv("POSTGRES_DSN")

PRODUCT_SEED = {
    "pearl-01": {"name": "Foam Mousse Moisture", "price": Decimal("96"), "size": "150 мл", "brand": "Pearl by Tais", "image": "img/Pearl1.jpg"},
    "pearl-02": {"name": "Face Tonic Toning", "price": Decimal("93"), "size": "150 мл", "brand": "Pearl by Tais", "image": "img/Pearl2.jpg"},
    "pearl-03": {"name": "Tonic Youth Restoring", "price": Decimal("93"), "size": "150 мл", "brand": "Pearl by Tais", "image": "img/Pearl3.jpg"},
    "pearl-04": {"name": "Foam Mousse Cleansing", "price": Decimal("96"), "size": "150 мл", "brand": "Pearl by Tais", "image": "img/Pearl4.jpg"},
    "pearl-05": {"name": "Hair Tonic Radiance", "price": Decimal("88"), "size": "200 мл", "brand": "Pearl by Tais", "image": "img/Pearl5.jpg"},
    "pearl-06": {"name": "Velvet Oil Blend", "price": Decimal("69"), "size": "60 мл", "brand": "Pearl by Tais", "image": "img/Pearl6.jpg"},
    "pearl-07": {"name": "Micellar Water Extract Mix", "price": Decimal("99"), "size": "200 мл", "brand": "Pearl by Tais", "image": "img/Pearl7.jpg"},
    "homme-01": {"name": "Face Wash Black", "price": Decimal("78"), "size": "200 мл", "brand": "INTELEGENTOFF", "image": "img/INTELEGENT Пенка.png"},
    "homme-02": {"name": "Toner Control", "price": Decimal("89"), "size": "150 мл", "brand": "INTELEGENTOFF", "image": "img/INTELEGENT тоник.png"},
    "homme-03": {"name": "Beard Oil", "price": Decimal("96"), "size": "50 мл", "brand": "INTELEGENTOFF", "image": "img/INTELEGENT масло.png"},
    "homme-04": {"name": "Beard Wax", "price": Decimal("82"), "size": "50 мл", "brand": "INTELEGENTOFF", "image": "img/INTELEGENT Воск.png"},
    "homme-05": {"name": "Face Serum Black", "price": Decimal("134"), "size": "30 мл", "brand": "INTELEGENTOFF", "image": "img/prod-photo-1.jpg"},
    "homme-06": {"name": "After Shave Balm", "price": Decimal("82"), "size": "100 мл", "brand": "INTELEGENTOFF", "image": "img/prod-photo-2.jpg"},
    "homme-kit-01": {"name": "INTELEGENTOFF Starter Kit", "price": Decimal("254"), "size": "Набор 3 продукта", "brand": "INTELEGENTOFF", "image": "img/logoIntelegent.png"},
}


@contextmanager
def get_connection():
    if not DATABASE_URL:
        raise RuntimeError("Не настроен DATABASE_URL для PostgreSQL.")
    if psycopg is None:
        raise RuntimeError("Не установлен пакет psycopg. Установите зависимости из requirements.txt.")
    with psycopg.connect(DATABASE_URL, row_factory=dict_row) as conn:
        yield conn


def init_products_table():
    """Create and seed the PostgreSQL products table."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS products (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    price NUMERIC(12, 2) NOT NULL CHECK (price >= 0),
                    size TEXT NOT NULL DEFAULT '',
                    brand TEXT NOT NULL DEFAULT '',
                    image TEXT NOT NULL DEFAULT '',
                    is_active BOOLEAN NOT NULL DEFAULT TRUE,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
            cur.executemany(
                """
                INSERT INTO products (id, name, price, size, brand, image)
                VALUES (%(id)s, %(name)s, %(price)s, %(size)s, %(brand)s, %(image)s)
                ON CONFLICT (id) DO UPDATE SET
                    name = EXCLUDED.name,
                    price = EXCLUDED.price,
                    size = EXCLUDED.size,
                    brand = EXCLUDED.brand,
                    image = EXCLUDED.image,
                    updated_at = NOW()
                """,
                [{"id": product_id, **data} for product_id, data in PRODUCT_SEED.items()],
            )
        conn.commit()


def get_products_by_ids(product_ids):
    """Return active products keyed by id from PostgreSQL.

    If DATABASE_URL is absent, fall back to the seed catalog so local development
    and tests can run without a PostgreSQL service. Production must set
    DATABASE_URL to make checkout prices authoritative from the database.
    """
    unique_ids = list(dict.fromkeys(product_ids))
    if not unique_ids:
        return {}

    cache_key = "products:v1:" + ",".join(sorted(unique_ids))
    cached_products = cache_get_json(cache_key)
    if cached_products is not None:
        return {product_id: {**product, "price": Decimal(str(product["price"]))} for product_id, product in cached_products.items()}

    if not DATABASE_URL:
        products = {product_id: PRODUCT_SEED[product_id] for product_id in unique_ids if product_id in PRODUCT_SEED}
        cache_set_json(cache_key, products, PRODUCT_CACHE_TTL)
        return products

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, name, price, size, brand, image
                FROM products
                WHERE id = ANY(%s) AND is_active = TRUE
                """,
                (unique_ids,),
            )
            rows = cur.fetchall()
    products = {row["id"]: row for row in rows}
    cache_set_json(cache_key, products, PRODUCT_CACHE_TTL)
    return products
