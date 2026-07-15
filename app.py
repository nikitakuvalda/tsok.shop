import atexit
import json
import logging
import os
import threading
import time
import uuid
from urllib.parse import urlencode, urlsplit, urlunsplit, parse_qsl
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

import dotenv
from functools import wraps
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

from flask import Flask, Response, jsonify, make_response, redirect, render_template, request, session, url_for
from yookassa import Configuration, Payment

from cache import PAGE_CACHE_TTL, cache_get_text, cache_set_text, is_rate_limited
from d2c import (
    COINS_REDEEM_LIMIT,
    LOYALTY_TIERS,
    REFERRAL_FIRST_ORDER_DISCOUNT,
    build_loyalty_event,
    build_subscription_notification,
    calculate_checkout_benefits,
    determine_loyalty_tier,
    money,
    referral_is_suspicious,
)
from db import PRODUCT_SEED, get_connection, get_products_by_ids, init_database, init_products_table, list_products


class StaticSiteFlask(Flask):
    jinja_options = Flask.jinja_options.copy()
    jinja_options.update(
        comment_start_string="{##",
        comment_end_string="##}",
    )


application = StaticSiteFlask(__name__)
logger = logging.getLogger(__name__)

dotenv.load_dotenv(override=True)
application.secret_key = os.getenv("FLASK_SECRET_KEY", "tsok-dev-secret-change-me")
init_database()

def _env_flag(name, default=True):
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}

SHOW_PRICES = _env_flag("TSOK_SHOW_PRICES", True)


@application.context_processor
def inject_public_settings():
    return {"show_prices": SHOW_PRICES}


YOOKASSA_SHOP_ID   = os.getenv("YOOKASSA_SHOP_ID", "")
YOOKASSA_SECRET_KEY = os.getenv("YOOKASSA_SECRET_KEY", "")
YOOKASSA_CURRENCY   = os.getenv("YOOKASSA_CURRENCY", "RUB")
YOOKASSA_RETURN_URL = os.getenv("YOOKASSA_RETURN_URL", "")
YANDEX_MAPS_API_KEY = os.getenv("YANDEX_MAPS_API_KEY", "14326938-97d2-483c-81c8-ada364bef9ed")

SUBSCRIPTION_PLANS = {
    "once": {"label": "Разовая покупка", "discount": Decimal("0"), "months": 0, "bnpl_required": False},
    "monthly": {"label": "Рекуррент ежемесячно", "discount": Decimal("0.10"), "months": 1, "bnpl_required": False},
    "3m": {"label": "Подписка 3 месяца", "discount": Decimal("0.15"), "months": 3, "bnpl_required": True},
    "6m": {"label": "Подписка 6 месяцев", "discount": Decimal("0.20"), "months": 6, "bnpl_required": True},
    "12m": {"label": "VIP 12 месяцев", "discount": Decimal("0.30"), "months": 12, "bnpl_required": True},
}
VIP_GIFTS = {"body-scrub", "mask-set", "quartz-roller"}
GIFT_LABELS = {
    "body-scrub": "Премиальный скраб для тела",
    "mask-set": "Набор тканевых масок",
    "quartz-roller": "Массажный роллер из кварца",
}
DELIVERY_FEE = Decimal("700")
MIN_BOX_ITEMS = 3

def _selected_count(items):
    return sum(item["qty"] for item in items)

def _calculate_box_quote(items, plan_code="once", vip_gift=""):
    plan = SUBSCRIPTION_PLANS.get(plan_code) or SUBSCRIPTION_PLANS["once"]
    count = _selected_count(items)
    if count < MIN_BOX_ITEMS:
        raise ValueError("Минимальный состав TSOK BOX — 3 товара.")
    base_total = sum(item["line_total"] for item in items)
    discount_amount = (base_total * plan["discount"]).quantize(Decimal("0.01"))
    discounted_total = base_total - discount_amount
    free_delivery = count >= 4 or plan_code in {"6m", "12m"}
    delivery_fee = Decimal("0") if free_delivery else DELIVERY_FEE
    gift_enabled = count >= 5
    gift = vip_gift if gift_enabled and vip_gift in VIP_GIFTS else ""
    payable_total = discounted_total + delivery_fee
    months = max(1, plan["months"] or 1)
    monthly_payment = (payable_total / months).quantize(Decimal("0.01"))
    bnpl = None
    if plan["bnpl_required"]:
        bnpl = {
            "provider": os.getenv("BNPL_PROVIDER", "split/dolyami"),
            "installments": 4,
            "today_payment": _format_amount((payable_total / Decimal("4")).quantize(Decimal("0.01"))),
            "settlement": "Магазин получает всю сумму на следующий день после авторизации BNPL.",
        }
    return {
        "plan_code": plan_code,
        "plan_label": plan["label"],
        "item_count": count,
        "base_total": base_total,
        "box_total": base_total,
        "discount_percent": int(plan["discount"] * 100),
        "discount_amount": discount_amount,
        "delivery_fee": delivery_fee,
        "free_delivery": free_delivery,
        "gift_enabled": gift_enabled,
        "vip_gift": gift,
        "payable_total": payable_total,
        "monthly_payment": monthly_payment,
        "bnpl": bnpl,
    }

def _quote_to_json(quote):
    return {k: (_format_amount(v) if isinstance(v, Decimal) else v) for k, v in quote.items()}

CACHEABLE_TEMPLATE_ROUTES = {
    "index": "index.html",
    "catalog": "catalog.html",
    "catalog_homme": "catalog-homme.html",
    "product_tonic": "product-tonic.html",
    "subscription": "subscription.html",
}

DEMO_CUSTOMER = {
    "email": "client@tsok.shop",
    "name": "Клиент TSOK",
    "loyalty_tier": "Gold",
    "tsok_coins": 1850,
    "referral_code": "TSOK-CLUB-500",
    "annual_spend": 18400,
    "subscription_months": 3,
}

DEMO_SUBSCRIPTION = {
    "id": "demo-subscription",
    "plan_code": "3m",
    "status": "active",
    "next_charge_at": (datetime.now(timezone.utc) + timedelta(days=12)).isoformat(),
    "vip_gift": "body-scrub",
    "items": [
        {"id": "pearl-01", "qty": 1},
        {"id": "pearl-03", "qty": 1},
        {"id": "pearl-05", "qty": 1},
        {"id": "pearl-07", "qty": 1},
    ],
    "payment_token_id": "tok_demo_yookassa",
}

DEMO_NOTIFICATIONS = []
DEMO_LOYALTY_EVENTS = []
DEMO_REFERRAL_CLAIMS = []

DEMO_ADMIN = {
    "email": os.getenv("TSOK_ADMIN_EMAIL", "admin@tsok.shop"),
    "password": os.getenv("TSOK_ADMIN_PASSWORD", "admin123"),
    "name": "TSOK Admin",
    "role": "owner",
}

DEMO_SALES = [
    {
        "id": "ORD-1001",
        "customer_email": DEMO_CUSTOMER["email"],
        "customer_name": DEMO_CUSTOMER["name"],
        "type": "subscription",
        "status": "paid",
        "total": Decimal("386.00"),
        "created_at": "2026-06-01T12:20:00+00:00",
        "items_count": 4,
        "payment_provider": "YooKassa",
    },
    {
        "id": "ORD-1002",
        "customer_email": "new.client@tsok.shop",
        "customer_name": "Новый клиент",
        "type": "one_time",
        "status": "delivered",
        "total": Decimal("254.00"),
        "created_at": "2026-06-10T16:45:00+00:00",
        "items_count": 1,
        "payment_provider": "YooKassa",
    },
]

DEMO_USERS = [
    {
        "id": "usr-demo-1",
        "name": DEMO_CUSTOMER["name"],
        "email": DEMO_CUSTOMER["email"],
        "phone": "+375 29 000-00-00",
        "loyalty_tier": DEMO_CUSTOMER["loyalty_tier"],
        "tsok_coins": DEMO_CUSTOMER["tsok_coins"],
        "annual_spend": DEMO_CUSTOMER["annual_spend"],
        "subscription_status": DEMO_SUBSCRIPTION["status"],
        "created_at": "2026-01-12",
    },
    {
        "id": "usr-demo-2",
        "name": "Новый клиент",
        "email": "new.client@tsok.shop",
        "phone": "+375 44 111-22-33",
        "loyalty_tier": "Silver",
        "tsok_coins": 120,
        "annual_spend": 254,
        "subscription_status": "none",
        "created_at": "2026-06-10",
    },
]


# ═══════════════════════════════════════════════════════════════════════
#  YooKassa helpers (без изменений)
# ═══════════════════════════════════════════════════════════════════════

def _format_amount(amount):
    return f"{amount.quantize(Decimal('0.01'))}"


def _normalize_checkout_payload(payload):
    items = payload.get("items") if isinstance(payload, dict) else None
    if not isinstance(items, list) or not items:
        raise ValueError("Корзина пуста.")

    raw_items  = [item for item in items if isinstance(item, dict)]
    product_ids = [str(item.get("id") or "").strip() for item in raw_items]
    products   = get_products_by_ids([pid for pid in product_ids if pid])

    normalized_items = []
    total = Decimal("0")
    for raw_item, product_id in zip(raw_items, product_ids):
        product = products.get(product_id)
        if not product:
            raise ValueError(f"Товар {product_id or 'без ID'} не найден.")
        try:
            qty = int(raw_item.get("qty", 1))
        except (TypeError, ValueError):
            qty = 1
        qty = max(1, min(qty, 99))
        price      = Decimal(str(product["price"]))
        line_total = price * qty
        total     += line_total
        normalized_items.append({"id": product_id, "qty": qty, **product, "price": price, "line_total": line_total})

    if total <= 0:
        raise ValueError("Некорректная сумма заказа.")

    customer = payload.get("customer") if isinstance(payload.get("customer"), dict) else {}
    delivery = payload.get("delivery") if isinstance(payload.get("delivery"), dict) else {}
    required_fields = {
        "fio":     customer.get("fio"),
        "phone":   customer.get("phone"),
        "email":   customer.get("email"),
        "city":    delivery.get("city"),
        "address": delivery.get("address"),
    }
    missing = [name for name, value in required_fields.items() if not str(value or "").strip()]
    if missing:
        raise ValueError("Заполните ФИО, телефон, email, город и адрес доставки.")

    return normalized_items, total, customer, delivery


def _absolute_return_url():
    if YOOKASSA_RETURN_URL:
        return YOOKASSA_RETURN_URL
    return url_for("payment_success", _external=True)


def _return_url_for_order(order_number):
    url = _absolute_return_url()
    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query["order_number"] = order_number
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def _payment_field(payment, field_name):
    if isinstance(payment, dict):
        return payment.get(field_name)
    return getattr(payment, field_name, None)


def _client_rate_limit_key():
    forwarded_for = request.headers.get("X-Forwarded-For", "")
    client_ip = forwarded_for.split(",", 1)[0].strip() or request.remote_addr or "unknown"
    return f"rate-limit:create-payment:{client_ip}"


def _render_cached_template(template_name):
    cache_key = f"page:v1:{template_name}"
    cached_html = cache_get_text(cache_key)
    if cached_html is not None:
        return Response(cached_html, mimetype="text/html")

    html = render_template(template_name)
    cache_set_text(cache_key, html, PAGE_CACHE_TTL)
    return html


@application.after_request
def add_performance_headers(response):
    if request.path.startswith("/static/"):
        response.cache_control.public = True
        response.cache_control.max_age = 60 * 60 * 24 * 30
        response.expires = datetime.now(timezone.utc) + timedelta(seconds=response.cache_control.max_age)
    elif request.endpoint in CACHEABLE_TEMPLATE_ROUTES:
        response.cache_control.public = True
        response.cache_control.max_age = PAGE_CACHE_TTL
    return response



def _checkout_benefits_from_payload(payload, subtotal, is_subscription_box=False):
    loyalty = payload.get("loyalty") if isinstance(payload.get("loyalty"), dict) else {}
    return calculate_checkout_benefits(
        subtotal=subtotal,
        current_coins=DEMO_CUSTOMER["tsok_coins"],
        loyalty_tier=DEMO_CUSTOMER["loyalty_tier"],
        referral_code=loyalty.get("referral_code"),
        valid_referral_code=DEMO_CUSTOMER["referral_code"],
        use_coins=bool(loyalty.get("use_coins")),
        is_subscription_box=is_subscription_box,
    )


def _benefits_to_json(benefits):
    return {k: (_format_amount(v) if isinstance(v, Decimal) else v) for k, v in benefits.items()}


def _compact_metadata_value(value, max_length=512):
    return str(value or "")[:max_length]


def _build_yookassa_metadata(order_number, customer, delivery, quote=None, benefits=None):
    # YooKassa rejects large metadata maps. Keep only compact, useful fields and
    # group optional checkout details into short strings so payment creation does
    # not fail with `parameter: metadata`.
    metadata = {
        "order_number": order_number,
        "customer_fio": _compact_metadata_value(customer.get("fio"), 120),
        "customer_phone": _compact_metadata_value(customer.get("phone"), 32),
        "customer_email": _compact_metadata_value(customer.get("email"), 120),
        "delivery_city": _compact_metadata_value(delivery.get("city"), 120),
        "delivery_address": _compact_metadata_value(delivery.get("address"), 255),
    }

    delivery_comment = _compact_metadata_value(delivery.get("comment"), 180)
    if delivery_comment:
        metadata["delivery_comment"] = delivery_comment

    pvz_parts = [
        _compact_metadata_value(delivery.get("pvz_provider"), 24),
        _compact_metadata_value(delivery.get("pvz_name"), 80),
        _compact_metadata_value(delivery.get("pvz_address"), 160),
        _compact_metadata_value(delivery.get("pvz_coordinates"), 48),
    ]
    pvz_info = " | ".join(part for part in pvz_parts if part)
    if pvz_info:
        metadata["delivery_pvz"] = _compact_metadata_value(pvz_info, 512)

    if quote:
        box_info = " | ".join(filter(None, [
            _compact_metadata_value(quote.get("plan_code"), 24),
            _compact_metadata_value(quote.get("plan_label"), 80),
            f"items:{quote.get('item_count')}",
            f"discount:{quote.get('discount_percent')}",
            "free_delivery" if quote.get("free_delivery") else "",
            _compact_metadata_value(GIFT_LABELS.get(quote.get("vip_gift", ""), ""), 80),
        ]))
        metadata["box_info"] = _compact_metadata_value(box_info, 512)

    if benefits:
        loyalty_info = " | ".join([
            f"tier:{benefits['loyalty_tier']}",
            f"cashback:{benefits['cashback_percent']}",
            f"ref:{benefits.get('referral_code', '') or '-'}",
            f"ref_status:{benefits['referral_status']}",
            f"ref_discount:{_format_amount(benefits['referral_discount'])}",
            f"coins_used:{_format_amount(benefits['coins_redeemed'])}",
            f"coins_pending:{_format_amount(benefits['coins_pending'])}",
        ])
        metadata["loyalty_info"] = _compact_metadata_value(loyalty_info, 512)

    return metadata


def _serialize_checkout_items(items):
    return json.dumps([{"id": item["id"], "qty": item["qty"], "name": item["name"]} for item in items], ensure_ascii=False)


def _store_payment_session(payment, order_number, items, customer, quote, benefits):
    payment_id = _payment_field(payment, "id")
    checkout_type = "subscription" if quote else "one_time"
    total = benefits["payable_total"] if benefits else (quote["payable_total"] if quote else sum(item["line_total"] for item in items))
    with get_connection() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO payment_sessions(
                order_number, payment_id, type, status, total, customer_name, customer_email, customer_phone,
                items_count, items, quote, updated_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP)
            """,
            (
                order_number,
                payment_id,
                checkout_type,
                "pending",
                _format_amount(total),
                str(customer.get("fio", ""))[:255],
                str(customer.get("email", ""))[:255],
                str(customer.get("phone", ""))[:64],
                _selected_count(items),
                _serialize_checkout_items(items),
                json.dumps(_quote_to_json(quote) if quote else {}, ensure_ascii=False),
            ),
        )


def _payment_is_successful(payment):
    status = _payment_field(payment, "status")
    paid = _payment_field(payment, "paid")
    return status == "succeeded" or paid is True


def _persist_successful_payment(session_row, payment):
    order_number = session_row["order_number"]
    payment_id = session_row["payment_id"] or _payment_field(payment, "id") or ""
    checkout_type = session_row["type"] or "one_time"
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO orders(id,user_id,customer_name,customer_email,type,status,total,items_count,payment_provider,comment)
            VALUES(?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(id) DO UPDATE SET
                status=excluded.status, total=excluded.total, items_count=excluded.items_count,
                payment_provider=excluded.payment_provider, comment=excluded.comment, updated_at=CURRENT_TIMESTAMP
            """,
            (
                order_number,
                None,
                session_row["customer_name"],
                session_row["customer_email"],
                checkout_type,
                "paid",
                session_row["total"],
                session_row["items_count"],
                "YooKassa",
                f"payment_id={payment_id}",
            ),
        )
        if checkout_type == "subscription":
            quote = json.loads(session_row["quote"] or "{}")
            next_charge_at = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
            subscription_id = f"SUB-{order_number}"
            payment_method = _payment_field(payment, "payment_method") or {}
            payment_token_id = _payment_field(payment_method, "id") or payment_id
            try:
                user_row = conn.execute("SELECT id FROM users WHERE lower(email)=lower(?) AND role='customer'", (session_row["customer_email"],)).fetchone()
            except Exception:
                user_row = None
            subscription_user_id = user_row["id"] if user_row else None
            conn.execute(
                """
                INSERT INTO subscriptions(id,user_id,status,plan_code,next_charge_at,vip_gift,items,payment_token_id)
                VALUES(?,?,?,?,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET
                    status=excluded.status, plan_code=excluded.plan_code, next_charge_at=excluded.next_charge_at,
                    vip_gift=excluded.vip_gift, items=excluded.items, payment_token_id=excluded.payment_token_id,
                    updated_at=CURRENT_TIMESTAMP
                """,
                (
                    subscription_id,
                    subscription_user_id,
                    "active",
                    quote.get("plan_code", "once"),
                    next_charge_at,
                    quote.get("vip_gift", ""),
                    session_row["items"],
                    payment_token_id,
                ),
            )
            if subscription_user_id:
                conn.execute("UPDATE users SET subscription_status='active', updated_at=CURRENT_TIMESTAMP WHERE id=?", (subscription_user_id,))
        conn.execute("UPDATE payment_sessions SET status='succeeded', updated_at=CURRENT_TIMESTAMP WHERE order_number=?", (order_number,))


def _webhook_payment_identity(payload):
    if not isinstance(payload, dict):
        return "", ""
    payment_object = payload.get("object") if isinstance(payload.get("object"), dict) else {}
    payment_id = str(payment_object.get("id") or payload.get("payment_id") or "").strip()
    metadata = payment_object.get("metadata") if isinstance(payment_object.get("metadata"), dict) else {}
    order_number = str(metadata.get("order_number") or payload.get("order_number") or "").strip()
    return order_number, payment_id


def _sync_yookassa_payment(order_number=None, payment_id=None):
    if not (order_number or payment_id):
        return {"status": "missing", "message": "Не передан номер заказа или платежа."}
    with get_connection() as conn:
        if order_number:
            row = conn.execute("SELECT * FROM payment_sessions WHERE order_number=?", (order_number,)).fetchone()
        else:
            row = conn.execute("SELECT * FROM payment_sessions WHERE payment_id=?", (payment_id,)).fetchone()
    if not row:
        return {"status": "missing", "message": "Платёжная сессия не найдена."}

    Configuration.account_id = YOOKASSA_SHOP_ID
    Configuration.secret_key = YOOKASSA_SECRET_KEY
    payment = Payment.find_one(row["payment_id"])
    payment_status = _payment_field(payment, "status") or "unknown"
    if _payment_is_successful(payment):
        _persist_successful_payment(row, payment)
        return {"status": "succeeded", "order_number": row["order_number"], "payment_id": row["payment_id"]}

    with get_connection() as conn:
        conn.execute("UPDATE payment_sessions SET status=?, updated_at=CURRENT_TIMESTAMP WHERE order_number=?", (payment_status, row["order_number"]))
    return {"status": payment_status, "order_number": row["order_number"], "payment_id": row["payment_id"]}


def _create_yookassa_payment(items, total, customer, delivery, quote=None, benefits=None):
    if not YOOKASSA_SHOP_ID or not YOOKASSA_SECRET_KEY:
        raise RuntimeError("Не настроены YOOKASSA_SHOP_ID и YOOKASSA_SECRET_KEY.")

    order_number   = f"TSOK-{int(time.time())}-{uuid.uuid4().hex[:6]}".upper()
    description_lines = ", ".join(f"{item['name']} x{item['qty']}" for item in items)
    description    = f"Заказ {order_number}: {description_lines}"[:128]
    metadata = _build_yookassa_metadata(order_number, customer, delivery, quote, benefits)
    payment_total = benefits["payable_total"] if benefits else (quote["payable_total"] if quote else total)
    payload = {
        "amount": {"value": _format_amount(payment_total), "currency": YOOKASSA_CURRENCY},
        "capture": True,
        "confirmation": {"type": "redirect", "return_url": _return_url_for_order(order_number)},
        "description":  description,
        "metadata":     metadata,
    }
    if quote:
        payload["save_payment_method"] = True
    if os.getenv("YOOKASSA_SEND_RECEIPT", "false").lower() in {"1", "true", "yes", "on"}:
        payload["receipt"] = {
            "customer": {
                "email": str(customer.get("email", "")).strip(),
                "phone": str(customer.get("phone", "")).strip(),
            },
            "items": [
                {
                    "description":    item["name"][:128],
                    "quantity":       str(item["qty"]),
                    "amount":         {"value": _format_amount(item["price"]), "currency": YOOKASSA_CURRENCY},
                    "vat_code":       int(os.getenv("YOOKASSA_VAT_CODE", "1")),
                    "payment_subject": "commodity",
                    "payment_mode":   "full_payment",
                }
                for item in items
            ],
        }
    Configuration.account_id = YOOKASSA_SHOP_ID
    Configuration.secret_key  = YOOKASSA_SECRET_KEY

    try:
        payment = Payment.create(payload, str(uuid.uuid4()))
    except Exception as error:
        message = getattr(error, "message", None) or getattr(error, "description", None) or str(error)
        raise RuntimeError(f"Ошибка ЮKassa: {message}") from error

    return payment, order_number



def _create_recurring_yookassa_payment(subscription, amount):
    if not subscription.get("payment_token_id"):
        raise RuntimeError("У подписки нет сохранённого способа оплаты.")
    Configuration.account_id = YOOKASSA_SHOP_ID
    Configuration.secret_key = YOOKASSA_SECRET_KEY
    payload = {
        "amount": {"value": _format_amount(amount), "currency": YOOKASSA_CURRENCY},
        "capture": True,
        "payment_method_id": subscription["payment_token_id"],
        "description": f"Автосписание TSOK BOX {subscription['id']}"[:128],
        "metadata": {"subscription_id": subscription["id"], "type": "subscription_autopay"},
    }
    return Payment.create(payload, str(uuid.uuid4()))


def charge_due_subscriptions(now=None):
    now = now or datetime.now(timezone.utc)
    charged = []
    with get_connection() as conn:
        rows = conn.execute("SELECT * FROM subscriptions WHERE status='active' AND payment_token_id<>'' AND next_charge_at<=?", (now.isoformat(),)).fetchall()
    for row in rows:
        subscription = dict(row)
        try:
            subscription["items"] = json.loads(subscription.get("items") or "[]")
            items = _subscription_items_with_products(subscription)
            quote = _calculate_box_quote(items, subscription.get("plan_code", "monthly"), subscription.get("vip_gift", ""))
            payment = _create_recurring_yookassa_payment(subscription, quote["payable_total"])
            next_charge_at = (now + timedelta(days=30)).isoformat()
            with get_connection() as conn:
                conn.execute("UPDATE subscriptions SET next_charge_at=?, updated_at=CURRENT_TIMESTAMP WHERE id=?", (next_charge_at, subscription["id"]))
            charged.append({"subscription_id": subscription["id"], "payment_id": _payment_field(payment, "id"), "next_charge_at": next_charge_at})
        except Exception as error:
            charged.append({"subscription_id": subscription.get("id"), "error": str(error)})
    return charged

class SubscriptionChargeScheduler:
    """Lightweight in-process scheduler for TSOK BOX recurring charges."""

    def __init__(self, interval_seconds=300):
        self.interval_seconds = max(30, int(interval_seconds))
        self._stop_event = threading.Event()
        self._run_lock = threading.Lock()
        self._thread = None
        self.last_run_at = None
        self.last_result = []
        self.last_error = ""

    @property
    def is_running(self):
        return bool(self._thread and self._thread.is_alive())

    def start(self):
        if self.is_running:
            return False
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, name="tsok-subscription-scheduler", daemon=True)
        self._thread.start()
        return True

    def stop(self):
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)

    def run_once(self):
        if not self._run_lock.acquire(blocking=False):
            return {"status": "skipped", "message": "Планировщик уже выполняет автосписания."}
        try:
            self.last_run_at = datetime.now(timezone.utc).isoformat()
            self.last_error = ""
            self.last_result = charge_due_subscriptions()
            return {"status": "ok", "charged": self.last_result, "last_run_at": self.last_run_at}
        except Exception as error:
            self.last_error = str(error)
            logger.exception("Subscription scheduler failed")
            return {"status": "error", "error": self.last_error, "last_run_at": self.last_run_at}
        finally:
            self._run_lock.release()

    def snapshot(self):
        return {
            "enabled": _subscription_scheduler_enabled(),
            "running": self.is_running,
            "interval_seconds": self.interval_seconds,
            "last_run_at": self.last_run_at,
            "last_result": self.last_result,
            "last_error": self.last_error,
        }

    def _run_loop(self):
        logger.info("TSOK subscription scheduler started with %s second interval", self.interval_seconds)
        while not self._stop_event.wait(self.interval_seconds):
            self.run_once()
        logger.info("TSOK subscription scheduler stopped")


def _subscription_scheduler_enabled():
    return os.getenv("TSOK_SUBSCRIPTION_SCHEDULER_ENABLED", "true").lower() in {"1", "true", "yes", "on"}


def _should_autostart_subscription_scheduler():
    if not _subscription_scheduler_enabled():
        return False
    if os.getenv("FLASK_DEBUG") == "1" and os.getenv("WERKZEUG_RUN_MAIN") != "true":
        return False
    return True


def _scheduler_interval_seconds():
    try:
        return int(os.getenv("TSOK_SUBSCRIPTION_SCHEDULER_INTERVAL_SECONDS", "300"))
    except ValueError:
        return 300


subscription_scheduler = SubscriptionChargeScheduler(_scheduler_interval_seconds())


def start_subscription_scheduler_if_enabled():
    if _should_autostart_subscription_scheduler():
        subscription_scheduler.start()


# ═══════════════════════════════════════════════════════════════════════
#  CLI
# ═══════════════════════════════════════════════════════════════════════

@application.cli.command("init-db")
def init_db_command():
    """Create and seed PostgreSQL tables."""
    init_database()
    print("Database is ready.")


@application.cli.command("charge-due-subscriptions")
def charge_due_subscriptions_command():
    """Charge active TSOK BOX subscriptions whose next_charge_at is due."""
    result = subscription_scheduler.run_once()
    print(json.dumps(result, ensure_ascii=False))


start_subscription_scheduler_if_enabled()
atexit.register(subscription_scheduler.stop)

# ═══════════════════════════════════════════════════════════════════════
#  Страницы — существующие
# ═══════════════════════════════════════════════════════════════════════

@application.route("/")
@application.route("/index")
@application.route("/index.html")
def index():
    return _render_cached_template("index.html")


@application.route("/catalog")
@application.route("/catalog.html")
def catalog():
    return _render_cached_template("catalog.html")


@application.route("/catalog-homme")
@application.route("/catalog-homme.html")
def catalog_homme():
    return _render_cached_template("catalog-homme.html")


@application.route("/product-tonic")
@application.route("/product-tonic.html")
def product_tonic():
    return _render_cached_template("product-tonic.html")


@application.route("/subscription")
@application.route("/subscription.html")
def subscription():
    return _render_cached_template("subscription.html")

@application.route("/gift")
@application.route("/gift.html")
def gift():
    return _render_cached_template("gift.html")

@application.route("/oferta")
@application.route("/oferta.html")
def oferta():
    return _render_cached_template("oferta.html")

@application.route("/privacy")
@application.route("/privacy.html")
def privacy():
    return _render_cached_template("privacy.html")

@application.route("/contacts")
@application.route("/contacts.html")
def contacts():
    return _render_cached_template("contacts.html")




def _admin_logged_in():
    return bool(session.get("admin_user_id")) or session.get("admin_email") == DEMO_ADMIN["email"]

def _current_user_id():
    return session.get("user_id")

def login_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if not _current_user_id():
            return redirect(url_for("account_login", next=request.path))
        return view(*args, **kwargs)
    return wrapper


def admin_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if not _admin_logged_in():
            return redirect(url_for("admin_login", next=request.path))
        return view(*args, **kwargs)
    return wrapper


def _admin_money(value):
    return f"{Decimal(str(value)).quantize(Decimal('0.01'))} ₽"


def _db_user(user_id):
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    return dict(row) if row else None


def _admin_state():
    products = list_products(include_inactive=True)
    with get_connection() as conn:
        users = [dict(row) for row in conn.execute("SELECT id,name,email,phone,loyalty_tier,tsok_coins,annual_spend,subscription_status,role,created_at FROM users ORDER BY created_at DESC").fetchall()]
        orders = [dict(row) for row in conn.execute("SELECT * FROM orders ORDER BY created_at DESC").fetchall()]
        subscriptions = [dict(row) for row in conn.execute("""
            SELECT s.id, s.user_id, s.status, s.plan_code, s.next_charge_at, s.vip_gift, s.items, s.payment_token_id, s.updated_at,
                   u.name AS customer_name, u.email AS customer_email, u.phone AS customer_phone
            FROM subscriptions s
            LEFT JOIN users u ON u.id = s.user_id
            ORDER BY COALESCE(s.next_charge_at, s.updated_at) DESC
        """).fetchall()]
    sales_total = sum((Decimal(str(order.get("total") or 0)) for order in orders), Decimal("0"))
    active_subscriptions = sum(1 for sub in subscriptions if sub.get("status") == "active")
    if not subscriptions:
        active_subscriptions = sum(1 for user in users if user.get("subscription_status") == "active")
    return {
        "admin": {"email": session.get("admin_email", DEMO_ADMIN["email"]), "name": DEMO_ADMIN["name"], "role": DEMO_ADMIN["role"]},
        "stats": {
            "users": len(users), "sales_count": len(orders), "sales_total": _admin_money(sales_total),
            "active_subscriptions": active_subscriptions, "coins_issued": sum(int(user.get("tsok_coins", 0) or 0) for user in users),
        },
        "users": users,
        "sales": [{**sale, "total_label": _admin_money(sale.get("total") or 0)} for sale in orders],
        "active_subscriptions": subscriptions,
        "loyalty_events": DEMO_LOYALTY_EVENTS, "referral_claims": DEMO_REFERRAL_CLAIMS, "notifications": DEMO_NOTIFICATIONS,
        "products": [{**product, "price_label": _admin_money(product["price"])} for product in products],
        "credentials_hint": {"email": DEMO_ADMIN["email"], "password": DEMO_ADMIN["password"]},
    }


@application.route("/admin", methods=["GET"])
@admin_required
def admin_dashboard():
    return render_template("admin.html", state=_admin_state())


@application.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    error = ""
    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""
        with get_connection() as conn:
            admin = conn.execute("SELECT * FROM users WHERE lower(email)=? AND role='admin'", (email,)).fetchone()
        if admin and check_password_hash(admin["password_hash"], password):
            session["admin_user_id"] = admin["id"]
            session["admin_email"] = admin["email"]
            return redirect(request.args.get("next") or url_for("admin_dashboard"))
        error = "Неверный email или пароль администратора."
    return render_template("admin_login.html", admin_email=DEMO_ADMIN["email"], admin_password=DEMO_ADMIN["password"], error=error)


@application.post("/admin/logout")
@admin_required
def admin_logout():
    session.pop("admin_email", None)
    session.pop("admin_user_id", None)
    return redirect(url_for("admin_login"))


@application.get("/api/admin/state")
@admin_required
def admin_state_api():
    return jsonify(_admin_state())


@application.post("/api/admin/users/<user_id>")
@admin_required
def admin_update_user(user_id):
    payload = request.get_json(silent=True) or {}
    allowed = {"name","email","phone","loyalty_tier","subscription_status","tsok_coins","annual_spend"}
    fields = {k: payload[k] for k in allowed if k in payload}
    if not fields: return jsonify({"error":"Нет полей для обновления."}), 400
    if "tsok_coins" in fields: fields["tsok_coins"] = int(fields["tsok_coins"] or 0)
    if "annual_spend" in fields: fields["annual_spend"] = int(fields["annual_spend"] or 0)
    sets = ", ".join(f"{k}=?" for k in fields) + ", updated_at=CURRENT_TIMESTAMP"
    with get_connection() as conn:
        cur = conn.execute(f"UPDATE users SET {sets} WHERE id=?", [*fields.values(), user_id])
        if cur.rowcount == 0: return jsonify({"error":"Пользователь не найден."}), 404
    return jsonify({"message":"Пользователь обновлён в базе.", "state": _admin_state()})



@application.post("/api/admin/products")
@admin_required
def admin_create_product():
    payload = request.form if request.form else (request.get_json(silent=True) or {})
    product_id = (payload.get("id") or f"prod-{uuid.uuid4().hex[:8]}").strip()
    image = (payload.get("image") or "").strip()
    file = request.files.get("image_file") if request.files else None
    if file and file.filename:
        filename = secure_filename(file.filename)
        image = f"img/{uuid.uuid4().hex[:6]}-{filename}"
        file.save(os.path.join(application.static_folder, image))
    with get_connection() as conn:
        conn.execute("""INSERT INTO products(id,name,price,size,brand,category,description,image,is_active)
        VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET name=excluded.name, price=excluded.price, size=excluded.size,
        brand=excluded.brand, category=excluded.category, description=excluded.description, image=excluded.image,
        is_active=excluded.is_active, updated_at=CURRENT_TIMESTAMP""", (
            product_id, payload.get("name","Новый товар"), str(payload.get("price") or 0), payload.get("size",""),
            payload.get("brand",""), payload.get("category","tais"), payload.get("description",""), image, int(payload.get("is_active", 1))
        ))
    return redirect(url_for("admin_dashboard") + "#catalog-admin")

@application.post("/api/admin/products/<product_id>")
@admin_required
def admin_update_product(product_id):
    payload = request.form if request.form else (request.get_json(silent=True) or {})
    fields = {k: payload.get(k) for k in ["name","price","size","brand","category","description","image","is_active"] if k in payload}
    file = request.files.get("image_file") if request.files else None
    if file and file.filename:
        filename = secure_filename(file.filename)
        fields["image"] = f"img/{uuid.uuid4().hex[:6]}-{filename}"
        file.save(os.path.join(application.static_folder, fields["image"]))
    if "is_active" in fields: fields["is_active"] = int(fields["is_active"])
    with get_connection() as conn:
        conn.execute(f"UPDATE products SET {', '.join(f'{k}=?' for k in fields)}, updated_at=CURRENT_TIMESTAMP WHERE id=?", [*fields.values(), product_id])
    return redirect(url_for("admin_dashboard") + "#catalog-admin")

@application.post("/api/admin/orders/<order_id>")
@admin_required
def admin_update_order(order_id):
    payload = request.get_json(silent=True) or {}
    fields = {k: payload[k] for k in ["status","type","total","items_count","payment_provider","comment"] if k in payload}
    if not fields: return jsonify({"error":"Нет полей для обновления."}), 400
    with get_connection() as conn:
        conn.execute(f"UPDATE orders SET {', '.join(f'{k}=?' for k in fields)}, updated_at=CURRENT_TIMESTAMP WHERE id=?", [*fields.values(), order_id])
    return jsonify({"message":"Заказ обновлён в базе.", "state": _admin_state()})

@application.post("/api/admin/subscription")
@admin_required
def admin_update_subscription():
    payload = request.get_json(silent=True) or {}
    if "status" in payload:
        DEMO_SUBSCRIPTION["status"] = str(payload["status"])[:40]
    if "plan_code" in payload and payload["plan_code"] in SUBSCRIPTION_PLANS:
        DEMO_SUBSCRIPTION["plan_code"] = payload["plan_code"]
    if "next_charge_at" in payload:
        try:
            DEMO_SUBSCRIPTION["next_charge_at"] = datetime.fromisoformat(str(payload["next_charge_at"])).isoformat()
        except ValueError:
            return jsonify({"error": "next_charge_at должен быть ISO datetime."}), 400
    return jsonify({"message": "Подписка обновлена.", "state": _admin_state()})

@application.route("/checkout")
@application.route("/checkout.html")
def checkout():
    return render_template("checkout.html", yandex_maps_api_key=YANDEX_MAPS_API_KEY)


@application.route("/account")
@application.route("/account.html")
@login_required
def account():
    return render_template("account.html", user=_db_user(_current_user_id()))

@application.route("/login", methods=["GET", "POST"])
def account_login():
    error = ""
    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""
        with get_connection() as conn:
            user = conn.execute("SELECT * FROM users WHERE lower(email)=? AND role='customer'", (email,)).fetchone()
        if user and check_password_hash(user["password_hash"], password):
            session["user_id"] = user["id"]
            return redirect(request.args.get("next") or url_for("account"))
        error = "Неверный email или пароль."
    return render_template("account_login.html", error=error)

@application.route("/register", methods=["GET", "POST"])
def account_register():
    error = ""
    if request.method == "POST":
        user_id = f"usr-{uuid.uuid4().hex[:10]}"
        name = (request.form.get("name") or "").strip()
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""
        phone = (request.form.get("phone") or "").strip()
        city = (request.form.get("city") or "").strip()
        address = (request.form.get("address") or "").strip()
        if not name or not email or len(password) < 6:
            error = "Укажите имя, email и пароль от 6 символов."
        else:
            try:
                with get_connection() as conn:
                    conn.execute("INSERT INTO users(id,name,email,password_hash,phone,city,address) VALUES(?,?,?,?,?,?,?)", (user_id, name, email, generate_password_hash(password), phone, city, address))
                session["user_id"] = user_id
                return redirect(url_for("account"))
            except Exception:
                error = "Такой email уже зарегистрирован."
    return render_template("account_register.html", error=error)

@application.post("/logout")
def account_logout():
    session.pop("user_id", None)
    return redirect(url_for("account_login"))

@application.post("/api/account/profile")
@login_required
def account_profile_update():
    payload = request.get_json(silent=True) or request.form
    fields = {k: str(payload.get(k) or "").strip()[:255] for k in ["name", "phone", "city", "address"] if k in payload}
    if not fields: return jsonify({"error":"Нет данных для сохранения."}), 400
    sets = ", ".join(f"{k}=?" for k in fields) + ", updated_at=CURRENT_TIMESTAMP"
    with get_connection() as conn:
        conn.execute(f"UPDATE users SET {sets} WHERE id=?", [*fields.values(), _current_user_id()])
    return jsonify({"message":"Личные данные сохранены в базе.", "user": _db_user(_current_user_id())})


@application.route("/payment/success")
def payment_success():
    order_number = request.args.get("order_number", "").strip()
    payment_status = "missing"
    if order_number:
        try:
            payment_status = _sync_yookassa_payment(order_number=order_number).get("status", "unknown")
        except Exception:
            payment_status = "check_failed"
    return render_template(
        "checkout.html",
        yandex_maps_api_key=YANDEX_MAPS_API_KEY,
        payment_success=payment_status == "succeeded",
        payment_status=payment_status,
    )


# ═══════════════════════════════════════════════════════════════════════
#  Страница — IoT Dashboard (новая, курсовая)
# ═══════════════════════════════════════════════════════════════════════

@application.route("/iot")
@application.route("/iot.html")
def iot():
    return render_template("iot.html")


# ═══════════════════════════════════════════════════════════════════════
#  API — YooKassa (без изменений)
# ═══════════════════════════════════════════════════════════════════════


@application.post("/api/yookassa/webhook")
def yookassa_webhook():
    payload = request.get_json(silent=True) or {}
    event = str(payload.get("event") or "")
    order_number, payment_id = _webhook_payment_identity(payload)
    if not (order_number or payment_id):
        return jsonify({"ok": False, "error": "Не найден payment_id или order_number в уведомлении."}), 400

    try:
        result = _sync_yookassa_payment(order_number=order_number, payment_id=payment_id)
    except Exception as error:
        return jsonify({"ok": False, "error": str(error)}), 502

    return jsonify({"ok": True, "event": event, **result})

@application.get("/api/yookassa/check-payment")
def check_yookassa_payment():
    order_number = request.args.get("order_number", "").strip()
    payment_id = request.args.get("payment_id", "").strip()
    try:
        result = _sync_yookassa_payment(order_number=order_number, payment_id=payment_id)
    except Exception as error:
        return jsonify({"error": str(error)}), 502
    return jsonify(result)

@application.post("/api/yookassa/create-payment")
def create_yookassa_payment():
    if not SHOW_PRICES:
        return jsonify({"error": "Оформление заказа временно недоступно."}), 403
    if is_rate_limited(_client_rate_limit_key()):
        return make_response(jsonify({"error": "Слишком много запросов. Попробуйте позже."}), 429)

    payload = request.get_json(silent=True) or {}
    try:
        items, total, customer, delivery = _normalize_checkout_payload(payload)
        quote = None
        if payload.get("box"):
            box_payload = payload.get("box") if isinstance(payload.get("box"), dict) else {}
            quote = _calculate_box_quote(items, box_payload.get("plan", "once"), box_payload.get("vip_gift", ""))
        subtotal_for_benefits = quote["payable_total"] if quote else total
        benefits = _checkout_benefits_from_payload(payload, subtotal_for_benefits, is_subscription_box=bool(quote))
        payment, order_number = _create_yookassa_payment(items, total, customer, delivery, quote, benefits)
        _store_payment_session(payment, order_number, items, customer, quote, benefits)
    except (ValueError, InvalidOperation) as error:
        return jsonify({"error": str(error)}), 400
    except Exception as error:
        return jsonify({"error": str(error)}), 502

    confirmation     = _payment_field(payment, "confirmation")
    confirmation_url = _payment_field(confirmation, "confirmation_url")
    if not confirmation_url:
        return jsonify({"error": "ЮKassa не вернула ссылку на оплату."}), 502
    return jsonify({
        "confirmation_url": confirmation_url,
        "payment_id":       _payment_field(payment, "id"),
        "order_number":     order_number,
    })



def _subscription_items_with_products(subscription):
    products = get_products_by_ids([item["id"] for item in subscription["items"]])
    enriched_items = []
    for item in subscription["items"]:
        product = products.get(item["id"])
        if not product:
            continue
        qty = int(item.get("qty", 1))
        price = Decimal(str(product["price"]))
        enriched_items.append({
            "id": item["id"],
            "qty": qty,
            **product,
            "price": price,
            "line_total": price * qty,
        })
    return enriched_items


def _empty_box_quote():
    return {
        "plan_code": "",
        "plan_label": "—",
        "box_total": Decimal("0"),
        "discount_percent": 0,
        "discount_amount": Decimal("0"),
        "payable_total": Decimal("0"),
        "item_count": 0,
        "free_delivery": False,
        "vip_gift": "",
        "bnpl": None,
    }


def _user_has_active_subscription(db_user):
    return bool(db_user and db_user.get("subscription_status") in {"active", "paused"})


def _load_user_subscription(user_id):
    if not user_id:
        return None
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT * FROM subscriptions
            WHERE user_id=? AND status IN ('active','paused')
            ORDER BY COALESCE(next_charge_at, updated_at) DESC
            LIMIT 1
            """,
            (user_id,),
        ).fetchone()
    if not row:
        return None
    subscription = dict(row)
    try:
        subscription["items"] = json.loads(subscription.get("items") or "[]")
    except (TypeError, json.JSONDecodeError):
        subscription["items"] = []
    return subscription


def _current_subscription_state():
    user_id = _current_user_id()
    db_user = _db_user(user_id) if user_id else None
    customer = {**DEMO_CUSTOMER}
    if db_user:
        customer.update({"name": db_user["name"], "email": db_user["email"], "phone": db_user.get("phone", ""), "city": db_user.get("city", ""), "address": db_user.get("address", ""), "loyalty_tier": db_user["loyalty_tier"], "tsok_coins": db_user["tsok_coins"], "annual_spend": db_user["annual_spend"]})

    stored_subscription = _load_user_subscription(user_id)
    has_subscription = bool(stored_subscription) or _user_has_active_subscription(db_user)
    active_subscription = stored_subscription or DEMO_SUBSCRIPTION
    if has_subscription:
        items = _subscription_items_with_products(active_subscription)
        quote = _calculate_box_quote(items, active_subscription["plan_code"], active_subscription.get("vip_gift", ""))
        next_charge = datetime.fromisoformat(active_subscription["next_charge_at"])
        subscription = {
            **active_subscription,
            "has_subscription": True,
            "next_charge_date": next_charge.strftime("%d.%m.%Y"),
            "items": _quote_items_to_json(items),
            "quote": _quote_to_json(quote),
            "vip_gift_label": GIFT_LABELS.get(active_subscription.get("vip_gift", ""), ""),
        }
    else:
        subscription = {
            "id": "",
            "plan_code": "",
            "status": db_user.get("subscription_status", "none") if db_user else "none",
            "has_subscription": False,
            "next_charge_at": "",
            "next_charge_date": "—",
            "vip_gift": "",
            "items": [],
            "quote": _quote_to_json(_empty_box_quote()),
            "vip_gift_label": "",
        }

    return {
        "customer": customer,
        "subscription": subscription,
        "loyalty_rules": {
            "coins_rate": "1 Coin = 1 ₽",
            "coins_available_after_days": 14,
            "one_time_order_redeem_limit_percent": 30,
            "expires_after_inactive_months": 6,
            "referral_reward": 500,
            "tiers": {
                tier: {**rules, "cashback": int(rules["cashback"] * 100)}
                for tier, rules in LOYALTY_TIERS.items()
            },
        },
        "loyalty_events": DEMO_LOYALTY_EVENTS,
        "referral_claims": DEMO_REFERRAL_CLAIMS,
        "notifications": DEMO_NOTIFICATIONS,
        "catalog": _quote_items_to_json([{**product, "qty": 1, "line_total": Decimal(str(product["price"]))} for product in list_products()]),
    }


def _quote_items_to_json(items):
    return [
        {
            "id": item["id"],
            "name": item["name"],
            "qty": item["qty"],
            "price": _format_amount(item["price"]),
            "line_total": _format_amount(item["line_total"]),
            "brand": item.get("brand", ""),
            "size": item.get("size", ""),
            "image": item.get("image", ""),
        }
        for item in items
    ]

@application.post("/api/subscription-box/quote")
def subscription_box_quote():
    payload = request.get_json(silent=True) or {}
    try:
        items, _total, _customer, _delivery = _normalize_checkout_payload({
            "items": payload.get("items", []),
            "customer": {"fio": "quote", "phone": "+70000000000", "email": "quote@example.com"},
            "delivery": {"city": "quote", "address": "quote"},
        })
        quote = _calculate_box_quote(items, payload.get("plan", "once"), payload.get("vip_gift", ""))
    except (ValueError, InvalidOperation) as error:
        return jsonify({"error": str(error)}), 400
    return jsonify(_quote_to_json(quote))


@application.post("/api/checkout/preview")
def checkout_preview():
    payload = request.get_json(silent=True) or {}
    try:
        items, total, _customer, _delivery = _normalize_checkout_payload({
            "items": payload.get("items", []),
            "customer": {"fio": "preview", "phone": "+70000000000", "email": "preview@example.com"},
            "delivery": {"city": "preview", "address": "preview"},
        })
        quote = None
        if payload.get("box"):
            box_payload = payload.get("box") if isinstance(payload.get("box"), dict) else {}
            quote = _calculate_box_quote(items, box_payload.get("plan", "once"), box_payload.get("vip_gift", ""))
        subtotal = quote["payable_total"] if quote else total
        benefits = _checkout_benefits_from_payload(payload, subtotal, is_subscription_box=bool(quote))
    except (ValueError, InvalidOperation) as error:
        return jsonify({"error": str(error)}), 400
    return jsonify({
        "subtotal": _format_amount(subtotal),
        "quote": _quote_to_json(quote) if quote else None,
        "benefits": _benefits_to_json(benefits),
    })


@application.post("/api/account/referral/apply")
def account_referral_apply():
    payload = request.get_json(silent=True) or {}
    code = str(payload.get("referral_code") or "").strip().upper()
    fingerprint = str(payload.get("fingerprint") or request.headers.get("X-Forwarded-For") or request.remote_addr or "unknown")[:120]
    if code != DEMO_CUSTOMER["referral_code"]:
        return jsonify({"status": "rejected", "error": "Промокод не найден."}), 400
    suspicious = referral_is_suspicious(DEMO_CUSTOMER.get("email"), fingerprint, payload.get("card_fingerprint", ""))
    claim = {
        "referral_code": code,
        "reward_coins": 500,
        "anti_fraud_fingerprint": fingerprint,
        "status": "rejected" if suspicious else "pending_delivery",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    DEMO_REFERRAL_CLAIMS.append(claim)
    return jsonify({"status": "accepted", "claim": claim, "message": "Referral принят: новичку −10%, пригласившему 500 Coins после доставки."})


@application.post("/api/account/loyalty/accrue")
def account_loyalty_accrue():
    payload = request.get_json(silent=True) or {}
    delivered_total = money(payload.get("delivered_total", "0"))
    event = build_loyalty_event(delivered_total, DEMO_CUSTOMER["loyalty_tier"])
    event = {
        **event,
        "coins_delta": _format_amount(event["coins_delta"]),
        "available_at": event["available_at"].isoformat(),
        "expires_at": event["expires_at"].isoformat(),
    }
    DEMO_LOYALTY_EVENTS.append(event)
    return jsonify({"message": "Coins запланированы к начислению через 14 дней после доставки.", "event": event})


@application.post("/api/account/notifications/schedule")
def account_notifications_schedule():
    notification = build_subscription_notification(DEMO_SUBSCRIPTION["id"], DEMO_SUBSCRIPTION["next_charge_at"])
    notification = {**notification, "send_at": notification["send_at"].isoformat()}
    DEMO_NOTIFICATIONS.append(notification)
    return jsonify({"message": "Уведомление за 72 часа поставлено в демо-очередь.", "notification": notification})


@application.get("/api/account/subscription")
@login_required
def account_subscription():
    return jsonify(_current_subscription_state())


@application.post("/api/account/subscription/swap")
@login_required
def account_subscription_swap():
    if not _user_has_active_subscription(_db_user(_current_user_id())):
        return jsonify({"error": "У вас пока нет активной подписки TSOK BOX."}), 400
    payload = request.get_json(silent=True) or {}
    raw_items = payload.get("items")
    if not isinstance(raw_items, list):
        return jsonify({"error": "Передайте items для нового состава подписки."}), 400
    try:
        candidate_items = []
        for raw in raw_items:
            if not isinstance(raw, dict):
                continue
            product_id = str(raw.get("id") or "").strip()
            qty = int(raw.get("qty", 0))
            if product_id and qty > 0:
                candidate_items.append({"id": product_id, "qty": min(qty, 99)})
        products = get_products_by_ids([item["id"] for item in candidate_items])
        items = [{"id": item["id"], "qty": item["qty"], **products[item["id"]]} for item in candidate_items if item["id"] in products]
        for item in items:
            item["price"] = Decimal(str(item["price"]))
            item["line_total"] = item["price"] * item["qty"]
        stored_subscription = _load_user_subscription(_current_user_id())
        plan_code = (stored_subscription or DEMO_SUBSCRIPTION)["plan_code"]
        vip_gift = (stored_subscription or DEMO_SUBSCRIPTION).get("vip_gift", "")
        quote = _calculate_box_quote(items, plan_code, vip_gift)
    except (ValueError, InvalidOperation, TypeError) as error:
        return jsonify({"error": str(error)}), 400
    new_items = [{"id": item["id"], "qty": item["qty"]} for item in items]
    if stored_subscription:
        with get_connection() as conn:
            conn.execute("UPDATE subscriptions SET items=?, updated_at=CURRENT_TIMESTAMP WHERE id=?", (json.dumps(new_items, ensure_ascii=False), stored_subscription["id"]))
    else:
        DEMO_SUBSCRIPTION["items"] = new_items
    return jsonify({"message": "Состав обновлён, сумма следующего автосписания пересчитана.", "quote": _quote_to_json(quote), "state": _current_subscription_state()})


@application.post("/api/account/subscription/pause")
@login_required
def account_subscription_pause():
    if not _user_has_active_subscription(_db_user(_current_user_id())):
        return jsonify({"error": "У вас пока нет активной подписки TSOK BOX."}), 400
    skip_count = int(DEMO_SUBSCRIPTION.get("skip_count", 0))
    if skip_count >= 2:
        return jsonify({"error": "Лимит пропусков исчерпан: месяц можно пропустить не больше двух раз."}), 400
    stored_subscription = _load_user_subscription(_current_user_id())
    active_subscription = stored_subscription or DEMO_SUBSCRIPTION
    next_charge = datetime.fromisoformat(active_subscription["next_charge_at"]) + timedelta(days=30)
    DEMO_SUBSCRIPTION["skip_count"] = skip_count + 1
    if stored_subscription:
        with get_connection() as conn:
            conn.execute("UPDATE subscriptions SET status='paused', next_charge_at=?, updated_at=CURRENT_TIMESTAMP WHERE id=?", (next_charge.isoformat(), stored_subscription["id"]))
            conn.execute("UPDATE users SET subscription_status='paused', updated_at=CURRENT_TIMESTAMP WHERE id=?", (_current_user_id(),))
    else:
        DEMO_SUBSCRIPTION["next_charge_at"] = next_charge.isoformat()
        DEMO_SUBSCRIPTION["status"] = "paused"
        with get_connection() as conn:
            conn.execute("UPDATE users SET subscription_status='paused', updated_at=CURRENT_TIMESTAMP WHERE id=?", (_current_user_id(),))
    return jsonify({"message": f"Месяц пропущен ({DEMO_SUBSCRIPTION['skip_count']}/2), следующее списание сдвинуто на 30 дней.", "state": _current_subscription_state()})


@application.post("/api/account/loyalty/recalculate-tier")
def account_loyalty_recalculate_tier():
    DEMO_CUSTOMER["loyalty_tier"] = determine_loyalty_tier(
        DEMO_CUSTOMER.get("subscription_months", 0),
        DEMO_CUSTOMER.get("annual_spend", 0),
        DEMO_SUBSCRIPTION.get("status", "active"),
    )
    return jsonify({"message": "loyalty_tier пересчитан по стажу подписки и годовой сумме покупок.", "state": _current_subscription_state()})


@application.post("/api/account/subscription/resume")
@login_required
def account_subscription_resume():
    stored_subscription = _load_user_subscription(_current_user_id())
    DEMO_SUBSCRIPTION["status"] = "active"
    with get_connection() as conn:
        if stored_subscription:
            conn.execute("UPDATE subscriptions SET status='active', updated_at=CURRENT_TIMESTAMP WHERE id=?", (stored_subscription["id"],))
        conn.execute("UPDATE users SET subscription_status='active', updated_at=CURRENT_TIMESTAMP WHERE id=?", (_current_user_id(),))
    DEMO_CUSTOMER["loyalty_tier"] = determine_loyalty_tier(
        DEMO_CUSTOMER.get("subscription_months", 0),
        DEMO_CUSTOMER.get("annual_spend", 0),
        DEMO_SUBSCRIPTION.get("status", "active"),
    )
    return jsonify({"message": "Подписка возобновлена, tier пересчитан автоматически.", "state": _current_subscription_state()})


@application.post("/api/account/subscription/cancel")
@login_required
def account_subscription_cancel():
    if not _user_has_active_subscription(_db_user(_current_user_id())):
        return jsonify({"error": "У вас пока нет активной подписки TSOK BOX."}), 400
    stored_subscription = _load_user_subscription(_current_user_id())
    if stored_subscription:
        with get_connection() as conn:
            conn.execute("UPDATE subscriptions SET status='cancelled', payment_token_id='', updated_at=CURRENT_TIMESTAMP WHERE id=?", (stored_subscription["id"],))
            conn.execute("UPDATE users SET subscription_status='cancelled', loyalty_tier='Silver', updated_at=CURRENT_TIMESTAMP WHERE id=?", (_current_user_id(),))
    else:
        DEMO_SUBSCRIPTION["status"] = "cancelled"
        DEMO_SUBSCRIPTION["payment_token_id"] = ""
        with get_connection() as conn:
            conn.execute("UPDATE users SET subscription_status='cancelled', loyalty_tier='Silver', updated_at=CURRENT_TIMESTAMP WHERE id=?", (_current_user_id(),))
    DEMO_CUSTOMER["loyalty_tier"] = "Silver"
    return jsonify({"message": "Карта отвязана в платёжном шлюзе, подписка отменена, loyalty_tier понижен до Silver.", "state": _current_subscription_state()})


if __name__ == "__main__":
    application.run(debug=True)
