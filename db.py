import os
import sqlite3
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path
from werkzeug.security import generate_password_hash

DATABASE_URL = os.getenv("DATABASE_URL") or os.getenv("POSTGRES_URL") or os.getenv("POSTGRES_DSN")
SQLITE_PATH = os.getenv("SQLITE_PATH", str(Path(__file__).with_name("tsok.sqlite3")))

PRODUCT_SEED = {
    "pearl-01": {"name": "Foam Mousse Moisture", "price": Decimal("2590"), "size": "150 мл", "brand": "Pearl by Tais", "category": "tais", "description": "Увлажняющая пенка для лица.", "image": "img/Pearl1.jpg"},
    "pearl-02": {"name": "Face Tonic Toning", "price": Decimal("2490"), "size": "150 мл", "brand": "Pearl by Tais", "category": "tais", "description": "Тоник для лица Тонус.", "image": "img/Pearl2.jpg"},
    "pearl-03": {"name": "Tonic Youth Restoring", "price": Decimal("2490"), "size": "150 мл", "brand": "Pearl by Tais", "category": "tais", "description": "Тоник-реставратор молодости.", "image": "img/Pearl3.jpg"},
    "pearl-04": {"name": "Foam Mousse Cleansing", "price": Decimal("2290"), "size": "150 мл", "brand": "Pearl by Tais", "category": "tais", "description": "Очищающая пенка для лица.", "image": "img/Pearl4.jpg"},
    "pearl-05": {"name": "Hair Tonic Radiance", "price": Decimal("2350"), "size": "200 мл", "brand": "Pearl by Tais", "category": "tais", "description": "Тоник для сияния волос.", "image": "img/Pearl5.jpg"},
    "pearl-06": {"name": "Velvet Oil Blend", "price": Decimal("2490"), "size": "60 мл", "brand": "Pearl by Tais", "category": "tais", "description": "Бархатное масло для ухода.", "image": "img/Pearl6.jpg"},
    "pearl-07": {"name": "Micellar Water Extract Mix", "price": Decimal("2650"), "size": "200 мл", "brand": "Pearl by Tais", "category": "tais", "description": "Мицеллярная вода с экстрактами.", "image": "img/Pearl7.jpg"},
    "homme-01": {"name": "Face Wash Black", "price": Decimal("1990"), "size": "200 мл", "brand": "INTELEGENTOFF", "category": "intelegent", "description": "Пенка для мужского ухода.", "image": "img/INTELEGENT Пенка.png"},
    "homme-02": {"name": "Toner Control", "price": Decimal("2190"), "size": "150 мл", "brand": "INTELEGENTOFF", "category": "intelegent", "description": "Контроль-тоник.", "image": "img/INTELEGENT тоник.png"},
    "homme-03": {"name": "Beard Oil", "price": Decimal("2290"), "size": "50 мл", "brand": "INTELEGENTOFF", "category": "intelegent", "description": "Масло для бороды.", "image": "img/INTELEGENT масло.png"},
    "homme-04": {"name": "Beard Wax", "price": Decimal("1890"), "size": "50 мл", "brand": "INTELEGENTOFF", "category": "intelegent", "description": "Воск для бороды.", "image": "img/INTELEGENT Воск.png"},
    "homme-05": {"name": "Face Serum Black", "price": Decimal("2790"), "size": "30 мл", "brand": "INTELEGENTOFF", "category": "intelegent", "description": "Сыворотка для лица.", "image": "img/prod-photo-1.jpg"},
    "homme-06": {"name": "After Shave Balm", "price": Decimal("1990"), "size": "100 мл", "brand": "INTELEGENTOFF", "category": "intelegent", "description": "Бальзам после бритья.", "image": "img/prod-photo-2.jpg"},
    "homme-kit-01": {"name": "INTELEGENTOFF Starter Kit", "price": Decimal("254"), "size": "Набор 3 продукта", "brand": "INTELEGENTOFF", "category": "intelegent", "description": "Стартовый набор.", "image": "img/logoIntelegent.png"},
    "pearl-set-1": {"name": "Pearl Set №1", "price": Decimal("7850"), "size": "Набор средств", "brand": "Pearl by Tais", "category": "tais", "description": "Набор для комплексного ухода.", "image": "img/PearlSet1.jpg"},
    "pearl-set-2": {"name": "Pearl Set №2", "price": Decimal("7850"), "size": "Набор средств", "brand": "Pearl by Tais", "category": "tais", "description": "Набор для тонуса и сияния.", "image": "img/PearlSet2.jpg"},
    "homme-beard-oil": {"name": "Масло для бороды", "price": Decimal("1680"), "size": "50 мл", "brand": "INTELEGENTOFF", "category": "intelegent", "description": "Смягчает бороду и кожу под ней.", "image": "img/INTELEGENT масло.png"},
    "homme-beard-foam": {"name": "Пенка для бороды", "price": Decimal("1720"), "size": "150 мл", "brand": "INTELEGENTOFF", "category": "intelegent", "description": "Мягко очищает бороду.", "image": "img/INTELEGENT Пенка.png"},
    "homme-beard-tonic": {"name": "Тоник-уход для бороды", "price": Decimal("1670"), "size": "150 мл", "brand": "INTELEGENTOFF", "category": "intelegent", "description": "Увлажняет и укрепляет бороду.", "image": "img/INTELEGENT тоник.png"},
    "homme-beard-wax": {"name": "Воск для бороды", "price": Decimal("1650"), "size": "50 мл", "brand": "INTELEGENTOFF", "category": "intelegent", "description": "Фиксирует форму и укладку.", "image": "img/INTELEGENT Воск.png"},
    "homme-shower-gel": {"name": "Гель для душа", "price": Decimal("1380"), "size": "250 мл", "brand": "INTELEGENTOFF", "category": "intelegent", "description": "Бодрящее очищение тела.", "image": "img/intel-gel.jpg"},
    "homme-liquid-soap": {"name": "Жидкое мыло", "price": Decimal("1380"), "size": "250 мл", "brand": "INTELEGENTOFF", "category": "intelegent", "description": "Мягко очищает руки и тело.", "image": "img/intel-liquid-soap.jpg"},
    "homme-shampoo": {"name": "Шампунь мужской", "price": Decimal("1680"), "size": "250 мл", "brand": "INTELEGENTOFF", "category": "intelegent", "description": "Очищает кожу головы и укрепляет волосы.", "image": "img/intel-shampoo.jpg"},
    "homme-bar-soap": {"name": "Мыло кусковое", "price": Decimal("550"), "size": "100 г", "brand": "INTELEGENTOFF", "category": "intelegent", "description": "Плотное брусковое мыло.", "image": "img/intel-bar-soap.jpg"},
    "homme-kit-beard": {"name": "Набор для бороды", "price": Decimal("5900"), "size": "Набор 4 средства", "brand": "INTELEGENTOFF", "category": "intelegent", "description": "Полный уход за бородой.", "image": "img/intel-kit-beard.jpg"},
    "homme-kit-shower": {"name": "Набор для душа", "price": Decimal("4200"), "size": "Набор 3 средства", "brand": "INTELEGENTOFF", "category": "intelegent", "description": "Базовый мужской уход.", "image": "img/intel-kit-shower.jpg"},
    "tsok-test-subscription-box-3m": {"name": "TSOK TEST BOX 3M", "price": Decimal("1"), "size": "3 месяца · тест оплаты", "brand": "TSOK BOX", "category": "hidden-test", "description": "Скрытая тестовая подписка-бокс: 1 ₽ сейчас и по 1 ₽ в следующие 2 месяца.", "image": ""},
}

@contextmanager
def get_connection():
    conn = sqlite3.connect(SQLITE_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()

def _row(row):
    data = dict(row)
    if "price" in data: data["price"] = Decimal(str(data["price"]))
    return data

def init_database():
    Path(SQLITE_PATH).parent.mkdir(parents=True, exist_ok=True)
    with get_connection() as conn:
        c = conn.cursor()
        c.execute("""CREATE TABLE IF NOT EXISTS users (id TEXT PRIMARY KEY, name TEXT NOT NULL, email TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL, phone TEXT DEFAULT '', city TEXT DEFAULT '', address TEXT DEFAULT '', loyalty_tier TEXT DEFAULT 'Silver', tsok_coins INTEGER DEFAULT 0, annual_spend INTEGER DEFAULT 0, subscription_status TEXT DEFAULT 'none', role TEXT DEFAULT 'customer', created_at TEXT DEFAULT CURRENT_TIMESTAMP, updated_at TEXT DEFAULT CURRENT_TIMESTAMP)""")
        c.execute("""CREATE TABLE IF NOT EXISTS products (id TEXT PRIMARY KEY, name TEXT NOT NULL, price NUMERIC NOT NULL, size TEXT DEFAULT '', brand TEXT DEFAULT '', category TEXT DEFAULT 'tais', description TEXT DEFAULT '', image TEXT DEFAULT '', is_active INTEGER DEFAULT 1, updated_at TEXT DEFAULT CURRENT_TIMESTAMP)""")
        c.execute("""CREATE TABLE IF NOT EXISTS orders (id TEXT PRIMARY KEY, user_id TEXT, customer_name TEXT DEFAULT '', customer_email TEXT DEFAULT '', type TEXT DEFAULT 'one_time', status TEXT DEFAULT 'new', total NUMERIC DEFAULT 0, items_count INTEGER DEFAULT 0, payment_provider TEXT DEFAULT '', comment TEXT DEFAULT '', created_at TEXT DEFAULT CURRENT_TIMESTAMP, updated_at TEXT DEFAULT CURRENT_TIMESTAMP)""")
        c.execute("""CREATE TABLE IF NOT EXISTS subscriptions (id TEXT PRIMARY KEY, user_id TEXT, status TEXT DEFAULT 'active', plan_code TEXT DEFAULT '3m', next_charge_at TEXT, vip_gift TEXT DEFAULT '', items TEXT DEFAULT '[]', payment_token_id TEXT DEFAULT '', updated_at TEXT DEFAULT CURRENT_TIMESTAMP)""")
        c.execute("""CREATE TABLE IF NOT EXISTS payment_sessions (order_number TEXT PRIMARY KEY, payment_id TEXT UNIQUE, type TEXT DEFAULT 'one_time', status TEXT DEFAULT 'pending', total NUMERIC DEFAULT 0, customer_name TEXT DEFAULT '', customer_email TEXT DEFAULT '', customer_phone TEXT DEFAULT '', items_count INTEGER DEFAULT 0, items TEXT DEFAULT '[]', quote TEXT DEFAULT '{}', created_at TEXT DEFAULT CURRENT_TIMESTAMP, updated_at TEXT DEFAULT CURRENT_TIMESTAMP)""")
        for pid, p in PRODUCT_SEED.items():
            c.execute("""INSERT OR IGNORE INTO products(id,name,price,size,brand,category,description,image) VALUES(?,?,?,?,?,?,?,?)""", (pid,p['name'],str(p['price']),p['size'],p['brand'],p['category'],p['description'],p['image']))
        admin_email=os.getenv('TSOK_ADMIN_EMAIL','admin@tsok.shop').lower(); admin_pass=os.getenv('TSOK_ADMIN_PASSWORD','admin123')
        c.execute("""INSERT OR IGNORE INTO users(id,name,email,password_hash,role,phone,loyalty_tier,tsok_coins,annual_spend,subscription_status) VALUES('admin','TSOK Admin',?,?, 'admin','', 'Gold',0,0,'none')""", (admin_email, generate_password_hash(admin_pass)))

def init_products_table(): init_database()

def list_products(category=None, include_inactive=False, include_hidden=False):
    init_database(); sql="SELECT * FROM products WHERE 1=1"; args=[]
    if category: sql += " AND category=?"; args.append(category)
    if not include_inactive: sql += " AND is_active=1"
    if not include_hidden: sql += " AND category != 'hidden-test'"
    sql += " ORDER BY category, name"
    with get_connection() as conn: return [_row(r) for r in conn.execute(sql,args).fetchall()]

def get_products_by_ids(product_ids):
    init_database(); ids=list(dict.fromkeys(product_ids));
    if not ids: return {}
    q=','.join('?'*len(ids))
    with get_connection() as conn:
        rows=conn.execute(f"SELECT * FROM products WHERE id IN ({q}) AND is_active=1", ids).fetchall()
    return {r['id']:_row(r) for r in rows}
