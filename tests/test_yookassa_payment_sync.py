import sqlite3
from contextlib import contextmanager
import app


@contextmanager
def sqlite_connection(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def create_payment_tables(path):
    with sqlite_connection(path) as conn:
        conn.execute("""CREATE TABLE payment_sessions (order_number TEXT PRIMARY KEY, payment_id TEXT UNIQUE, type TEXT DEFAULT 'one_time', status TEXT DEFAULT 'pending', total NUMERIC DEFAULT 0, customer_name TEXT DEFAULT '', customer_email TEXT DEFAULT '', customer_phone TEXT DEFAULT '', items_count INTEGER DEFAULT 0, items TEXT DEFAULT '[]', quote TEXT DEFAULT '{}', created_at TEXT DEFAULT CURRENT_TIMESTAMP, updated_at TEXT DEFAULT CURRENT_TIMESTAMP)""")
        conn.execute("""CREATE TABLE orders (id TEXT PRIMARY KEY, user_id TEXT, customer_name TEXT DEFAULT '', customer_email TEXT DEFAULT '', type TEXT DEFAULT 'one_time', status TEXT DEFAULT 'new', total NUMERIC DEFAULT 0, items_count INTEGER DEFAULT 0, payment_provider TEXT DEFAULT '', comment TEXT DEFAULT '', created_at TEXT DEFAULT CURRENT_TIMESTAMP, updated_at TEXT DEFAULT CURRENT_TIMESTAMP)""")
        conn.execute("""CREATE TABLE subscriptions (id TEXT PRIMARY KEY, user_id TEXT, status TEXT DEFAULT 'active', plan_code TEXT DEFAULT '3m', next_charge_at TEXT, vip_gift TEXT DEFAULT '', items TEXT DEFAULT '[]', payment_token_id TEXT DEFAULT '', updated_at TEXT DEFAULT CURRENT_TIMESTAMP)""")


def test_successful_one_time_payment_is_added_to_orders(monkeypatch, tmp_path):
    db_path = tmp_path / "payments.sqlite3"
    create_payment_tables(db_path)
    monkeypatch.setattr(app, "get_connection", lambda: sqlite_connection(db_path))

    with sqlite_connection(db_path) as conn:
        conn.execute("""INSERT INTO payment_sessions(order_number,payment_id,type,total,customer_name,customer_email,items_count,items,quote) VALUES('TSOK-1','pay-1','one_time','600.00','Иван','ivan@example.com',2,'[]','{}')""")

    monkeypatch.setattr(app.Payment, "find_one", lambda payment_id: {"id": payment_id, "status": "succeeded", "paid": True})

    result = app._sync_yookassa_payment(order_number="TSOK-1")

    assert result["status"] == "succeeded"
    with sqlite_connection(db_path) as conn:
        order = conn.execute("SELECT * FROM orders WHERE id='TSOK-1'").fetchone()
        assert order["status"] == "paid"
        assert order["type"] == "one_time"
        assert order["payment_provider"] == "YooKassa"
        assert order["comment"] == "payment_id=pay-1"


def test_successful_subscription_payment_creates_subscription(monkeypatch, tmp_path):
    db_path = tmp_path / "subscriptions.sqlite3"
    create_payment_tables(db_path)
    monkeypatch.setattr(app, "get_connection", lambda: sqlite_connection(db_path))

    quote = '{"plan_code":"12m","vip_gift":"quartz-roller"}'
    with sqlite_connection(db_path) as conn:
        conn.execute("""INSERT INTO payment_sessions(order_number,payment_id,type,total,customer_name,customer_email,items_count,items,quote) VALUES('TSOK-BOX','pay-box','subscription','1200.00','Анна','anna@example.com',5,'[{""id"":""pearl-01"",""qty"":1}]',?)""", (quote,))

    monkeypatch.setattr(app.Payment, "find_one", lambda payment_id: {"id": payment_id, "status": "succeeded", "paid": True})

    result = app._sync_yookassa_payment(payment_id="pay-box")

    assert result["status"] == "succeeded"
    with sqlite_connection(db_path) as conn:
        order = conn.execute("SELECT * FROM orders WHERE id='TSOK-BOX'").fetchone()
        subscription = conn.execute("SELECT * FROM subscriptions WHERE id='SUB-TSOK-BOX'").fetchone()
        assert order["type"] == "subscription"
        assert subscription["status"] == "active"
        assert subscription["plan_code"] == "12m"
        assert subscription["vip_gift"] == "quartz-roller"
        assert subscription["payment_token_id"] == "pay-box"


def test_yookassa_webhook_syncs_successful_payment(monkeypatch, tmp_path):
    db_path = tmp_path / "webhook.sqlite3"
    create_payment_tables(db_path)
    monkeypatch.setattr(app, "get_connection", lambda: sqlite_connection(db_path))

    with sqlite_connection(db_path) as conn:
        conn.execute("""INSERT INTO payment_sessions(order_number,payment_id,type,total,customer_name,customer_email,items_count,items,quote) VALUES('TSOK-WEBHOOK','pay-webhook','one_time','700.00','Олег','oleg@example.com',1,'[]','{}')""")

    monkeypatch.setattr(app.Payment, "find_one", lambda payment_id: {"id": payment_id, "status": "succeeded", "paid": True})

    response = app.application.test_client().post("/api/yookassa/webhook", json={
        "type": "notification",
        "event": "payment.succeeded",
        "object": {
            "id": "pay-webhook",
            "status": "succeeded",
            "paid": True,
            "metadata": {"order_number": "TSOK-WEBHOOK"},
        },
    })

    assert response.status_code == 200
    assert response.get_json()["status"] == "succeeded"
    with sqlite_connection(db_path) as conn:
        order = conn.execute("SELECT * FROM orders WHERE id='TSOK-WEBHOOK'").fetchone()
        assert order["status"] == "paid"
        assert order["comment"] == "payment_id=pay-webhook"
