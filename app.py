import os
import time
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

import dotenv
from flask import Flask, Response, jsonify, make_response, render_template, request, url_for
from yookassa import Configuration, Payment

from cache import PAGE_CACHE_TTL, cache_get_text, cache_set_text, is_rate_limited
from db import get_products_by_ids, init_products_table


class StaticSiteFlask(Flask):
    jinja_options = Flask.jinja_options.copy()
    jinja_options.update(
        comment_start_string="{##",
        comment_end_string="##}",
    )


application = StaticSiteFlask(__name__)

dotenv.load_dotenv(override=True)

YOOKASSA_SHOP_ID = os.getenv("YOOKASSA_SHOP_ID", "")
YOOKASSA_SECRET_KEY = os.getenv("YOOKASSA_SECRET_KEY", "")
YOOKASSA_CURRENCY = os.getenv("YOOKASSA_CURRENCY", "RUB")
YOOKASSA_RETURN_URL = os.getenv("YOOKASSA_RETURN_URL", "")
YANDEX_MAPS_API_KEY = os.getenv("YANDEX_MAPS_API_KEY", "14326938-97d2-483c-81c8-ada364bef9ed")
CACHEABLE_TEMPLATE_ROUTES = {
    "index": "index.html",
    "catalog": "catalog.html",
    "catalog_homme": "catalog-homme.html",
    "product_tonic": "product-tonic.html",
    "subscription": "subscription.html",
}



def _format_amount(amount):
    return f"{amount.quantize(Decimal('0.01'))}"


def _normalize_checkout_payload(payload):
    items = payload.get("items") if isinstance(payload, dict) else None
    if not isinstance(items, list) or not items:
        raise ValueError("Корзина пуста.")

    raw_items = [item for item in items if isinstance(item, dict)]
    product_ids = [str(item.get("id") or "").strip() for item in raw_items]
    products = get_products_by_ids([product_id for product_id in product_ids if product_id])

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
        price = Decimal(str(product["price"]))
        line_total = price * qty
        total += line_total
        normalized_items.append({"id": product_id, "qty": qty, **product, "price": price, "line_total": line_total})

    if total <= 0:
        raise ValueError("Некорректная сумма заказа.")

    customer = payload.get("customer") if isinstance(payload.get("customer"), dict) else {}
    delivery = payload.get("delivery") if isinstance(payload.get("delivery"), dict) else {}
    required_fields = {
        "fio": customer.get("fio"),
        "phone": customer.get("phone"),
        "email": customer.get("email"),
        "city": delivery.get("city"),
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


def _create_yookassa_payment(items, total, customer, delivery):
    if not YOOKASSA_SHOP_ID or not YOOKASSA_SECRET_KEY:
        raise RuntimeError("Не настроены YOOKASSA_SHOP_ID и YOOKASSA_SECRET_KEY.")

    order_number = f"TSOK-{int(time.time())}-{uuid.uuid4().hex[:6]}".upper()
    description_lines = ", ".join(f"{item['name']} x{item['qty']}" for item in items)
    description = f"Заказ {order_number}: {description_lines}"[:128]
    metadata = {
        "order_number": order_number,
        "customer_fio": str(customer.get("fio", ""))[:120],
        "customer_phone": str(customer.get("phone", ""))[:32],
        "customer_email": str(customer.get("email", ""))[:120],
        "delivery_city": str(delivery.get("city", ""))[:120],
        "delivery_address": str(delivery.get("address", ""))[:255],
        "delivery_comment": str(delivery.get("comment", ""))[:255],
        "delivery_pvz_provider": str(delivery.get("pvz_provider", ""))[:32],
        "delivery_pvz_name": str(delivery.get("pvz_name", ""))[:160],
        "delivery_pvz_address": str(delivery.get("pvz_address", ""))[:255],
        "delivery_pvz_coordinates": str(delivery.get("pvz_coordinates", ""))[:64],
    }
    payload = {
        "amount": {"value": _format_amount(total), "currency": YOOKASSA_CURRENCY},
        "capture": True,
        "confirmation": {"type": "redirect", "return_url": _absolute_return_url()},
        "description": description,
        "metadata": metadata,
    }
    if os.getenv("YOOKASSA_SEND_RECEIPT", "false").lower() in {"1", "true", "yes", "on"}:
        payload["receipt"] = {
            "customer": {
                "email": str(customer.get("email", "")).strip(),
                "phone": str(customer.get("phone", "")).strip(),
            },
            "items": [
                {
                    "description": item["name"][:128],
                    "quantity": str(item["qty"]),
                    "amount": {"value": _format_amount(item["price"]), "currency": YOOKASSA_CURRENCY},
                    "vat_code": int(os.getenv("YOOKASSA_VAT_CODE", "1")),
                    "payment_subject": "commodity",
                    "payment_mode": "full_payment",
                }
                for item in items
            ],
        }
    Configuration.account_id = YOOKASSA_SHOP_ID
    Configuration.secret_key = YOOKASSA_SECRET_KEY

    try:
        payment = Payment.create(payload, str(uuid.uuid4()))
    except Exception as error:
        message = getattr(error, "message", None) or getattr(error, "description", None) or str(error)
        raise RuntimeError(f"Ошибка ЮKassa: {message}") from error

    return payment, order_number


@application.cli.command("init-db")
def init_db_command():
    """Create and seed PostgreSQL tables."""
    init_products_table()
    print("PostgreSQL products table is ready.")


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


@application.route("/payment/success")
def payment_success():
    return render_template("checkout.html", yandex_maps_api_key=YANDEX_MAPS_API_KEY, payment_success=True)


@application.post("/api/yookassa/create-payment")
def create_yookassa_payment():
    if is_rate_limited(_client_rate_limit_key()):
        return make_response(jsonify({"error": "Слишком много запросов. Попробуйте позже."}), 429)

    payload = request.get_json(silent=True) or {}
    try:
        items, total, customer, delivery = _normalize_checkout_payload(payload)
        payment, order_number = _create_yookassa_payment(items, total, customer, delivery)
    except (ValueError, InvalidOperation) as error:
        return jsonify({"error": str(error)}), 400
    except Exception as error:
        return jsonify({"error": str(error)}), 502

    confirmation = _payment_field(payment, "confirmation")
    confirmation_url = _payment_field(confirmation, "confirmation_url")
    if not confirmation_url:
        return jsonify({"error": "ЮKassa не вернула ссылку на оплату."}), 502
    return jsonify({"confirmation_url": confirmation_url, "payment_id": _payment_field(payment, "id"), "order_number": order_number})


if __name__ == "__main__":
    application.run(debug=True)
