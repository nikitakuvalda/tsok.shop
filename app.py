import os
import time
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

import dotenv
from flask import Flask, Response, jsonify, make_response, render_template, request, url_for
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
from db import get_products_by_ids, init_products_table
from iot_devices import (
    apply_command,
    get_all_devices,
    get_device,
    get_mqtt_status,
    toggle_device_online,
)


class StaticSiteFlask(Flask):
    jinja_options = Flask.jinja_options.copy()
    jinja_options.update(
        comment_start_string="{##",
        comment_end_string="##}",
    )


application = StaticSiteFlask(__name__)

dotenv.load_dotenv(override=True)

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

def _create_yookassa_payment(items, total, customer, delivery, quote=None, benefits=None):
    if not YOOKASSA_SHOP_ID or not YOOKASSA_SECRET_KEY:
        raise RuntimeError("Не настроены YOOKASSA_SHOP_ID и YOOKASSA_SECRET_KEY.")

    order_number   = f"TSOK-{int(time.time())}-{uuid.uuid4().hex[:6]}".upper()
    description_lines = ", ".join(f"{item['name']} x{item['qty']}" for item in items)
    description    = f"Заказ {order_number}: {description_lines}"[:128]
    metadata = {
        "order_number":              order_number,
        "customer_fio":              str(customer.get("fio", ""))[:120],
        "customer_phone":            str(customer.get("phone", ""))[:32],
        "customer_email":            str(customer.get("email", ""))[:120],
        "delivery_city":             str(delivery.get("city", ""))[:120],
        "delivery_address":          str(delivery.get("address", ""))[:255],
        "delivery_comment":          str(delivery.get("comment", ""))[:255],
        "delivery_pvz_provider":     str(delivery.get("pvz_provider", ""))[:32],
        "delivery_pvz_name":         str(delivery.get("pvz_name", ""))[:160],
        "delivery_pvz_address":      str(delivery.get("pvz_address", ""))[:255],
        "delivery_pvz_coordinates":  str(delivery.get("pvz_coordinates", ""))[:64],
    }

    if quote:
        metadata.update({
            "box_plan": quote["plan_code"],
            "box_plan_label": quote["plan_label"],
            "box_item_count": str(quote["item_count"]),
            "box_discount_percent": str(quote["discount_percent"]),
            "box_free_delivery": str(quote["free_delivery"]).lower(),
            "box_vip_gift": quote.get("vip_gift", ""),
            "box_vip_gift_label": GIFT_LABELS.get(quote.get("vip_gift", ""), ""),
        })
    if benefits:
        metadata.update({
            "loyalty_tier": benefits["loyalty_tier"],
            "loyalty_cashback_percent": str(benefits["cashback_percent"]),
            "loyalty_referral_code": benefits.get("referral_code", ""),
            "loyalty_referral_status": benefits["referral_status"],
            "loyalty_referral_discount": _format_amount(benefits["referral_discount"]),
            "loyalty_coins_redeemed": _format_amount(benefits["coins_redeemed"]),
            "loyalty_coins_pending": _format_amount(benefits["coins_pending"]),
        })
    payment_total = benefits["payable_total"] if benefits else (quote["payable_total"] if quote else total)
    payload = {
        "amount": {"value": _format_amount(payment_total), "currency": YOOKASSA_CURRENCY},
        "capture": True,
        "confirmation": {"type": "redirect", "return_url": _absolute_return_url()},
        "description":  description,
        "metadata":     metadata,
    }
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


# ═══════════════════════════════════════════════════════════════════════
#  CLI
# ═══════════════════════════════════════════════════════════════════════

@application.cli.command("init-db")
def init_db_command():
    """Create and seed PostgreSQL tables."""
    init_products_table()
    print("PostgreSQL products table is ready.")


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


@application.route("/checkout")
@application.route("/checkout.html")
def checkout():
    return render_template("checkout.html", yandex_maps_api_key=YANDEX_MAPS_API_KEY)


@application.route("/account")
@application.route("/account.html")
def account():
    return render_template("account.html")


@application.route("/payment/success")
def payment_success():
    return render_template("checkout.html", yandex_maps_api_key=YANDEX_MAPS_API_KEY, payment_success=True)


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

@application.post("/api/yookassa/create-payment")
def create_yookassa_payment():
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
    return [{"id": item["id"], "qty": item["qty"], **products[item["id"]]} for item in subscription["items"] if item["id"] in products]


def _current_subscription_state():
    items = _subscription_items_with_products(DEMO_SUBSCRIPTION)
    quote = _calculate_box_quote(items, DEMO_SUBSCRIPTION["plan_code"], DEMO_SUBSCRIPTION.get("vip_gift", ""))
    next_charge = datetime.fromisoformat(DEMO_SUBSCRIPTION["next_charge_at"])
    return {
        "customer": DEMO_CUSTOMER,
        "subscription": {
            **DEMO_SUBSCRIPTION,
            "next_charge_date": next_charge.strftime("%d.%m.%Y"),
            "items": _quote_items_to_json(items),
            "quote": _quote_to_json(quote),
            "vip_gift_label": GIFT_LABELS.get(DEMO_SUBSCRIPTION.get("vip_gift", ""), ""),
        },
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
        "anti_churn_steps": ["loss", "offer", "final"],
        "notification": "CRON-уведомление будет отправлено за 72 часа до списания; у клиента есть 48 часов на swap/pause.",
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


@application.post("/api/subscription-box/anti-churn")
def subscription_anti_churn():
    payload = request.get_json(silent=True) or {}
    tier = str(payload.get("loyalty_tier") or "Silver")
    step = str(payload.get("step") or "loss")
    offers = {
        "loss": f"При отмене подписки статус {tier} будет понижен до Silver, а повышенный кэшбек TSOK Coins отключится.",
        "offer": "Останьтесь — добавим премиум-скраб за 0 ₽ в следующий бокс или поставим подписку на паузу на 30 дней.",
        "final": "Карта будет отвязана в платёжном шлюзе, подписка отменена, loyalty_tier станет Silver.",
    }
    return jsonify({"step": step, "message": offers.get(step, offers["loss"])})


@application.get("/api/account/subscription")
def account_subscription():
    return jsonify(_current_subscription_state())


@application.post("/api/account/subscription/swap")
def account_subscription_swap():
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
        quote = _calculate_box_quote(items, DEMO_SUBSCRIPTION["plan_code"], DEMO_SUBSCRIPTION.get("vip_gift", ""))
    except (ValueError, InvalidOperation, TypeError) as error:
        return jsonify({"error": str(error)}), 400
    DEMO_SUBSCRIPTION["items"] = [{"id": item["id"], "qty": item["qty"]} for item in items]
    return jsonify({"message": "Состав обновлён, сумма следующего автосписания пересчитана.", "quote": _quote_to_json(quote), "state": _current_subscription_state()})


@application.post("/api/account/subscription/pause")
def account_subscription_pause():
    next_charge = datetime.fromisoformat(DEMO_SUBSCRIPTION["next_charge_at"]) + timedelta(days=30)
    DEMO_SUBSCRIPTION["next_charge_at"] = next_charge.isoformat()
    DEMO_SUBSCRIPTION["status"] = "paused"
    return jsonify({"message": "Подписка поставлена на паузу, следующее списание сдвинуто на 30 дней.", "state": _current_subscription_state()})


@application.post("/api/account/loyalty/recalculate-tier")
def account_loyalty_recalculate_tier():
    DEMO_CUSTOMER["loyalty_tier"] = determine_loyalty_tier(
        DEMO_CUSTOMER.get("subscription_months", 0),
        DEMO_CUSTOMER.get("annual_spend", 0),
        DEMO_SUBSCRIPTION.get("status", "active"),
    )
    return jsonify({"message": "loyalty_tier пересчитан по стажу подписки и годовой сумме покупок.", "state": _current_subscription_state()})


@application.post("/api/account/subscription/resume")
def account_subscription_resume():
    DEMO_SUBSCRIPTION["status"] = "active"
    DEMO_CUSTOMER["loyalty_tier"] = determine_loyalty_tier(
        DEMO_CUSTOMER.get("subscription_months", 0),
        DEMO_CUSTOMER.get("annual_spend", 0),
        DEMO_SUBSCRIPTION.get("status", "active"),
    )
    return jsonify({"message": "Подписка возобновлена, tier пересчитан автоматически.", "state": _current_subscription_state()})


@application.post("/api/account/subscription/cancel")
def account_subscription_cancel():
    DEMO_SUBSCRIPTION["status"] = "cancelled"
    DEMO_SUBSCRIPTION["payment_token_id"] = ""
    DEMO_CUSTOMER["loyalty_tier"] = "Silver"
    return jsonify({"message": "Карта отвязана в демо-шлюзе, подписка отменена, loyalty_tier понижен до Silver.", "state": _current_subscription_state()})


if __name__ == "__main__":
    application.run(debug=True)
