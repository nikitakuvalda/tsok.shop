import base64
import json
import os
import dotenv
import time
import uuid
import urllib.error
import urllib.request
from decimal import Decimal, InvalidOperation

from flask import Flask, jsonify, render_template, request, url_for

from db import get_products_by_ids, init_products_table


class StaticSiteFlask(Flask):
    jinja_options = Flask.jinja_options.copy()
    jinja_options.update(
        comment_start_string="{##",
        comment_end_string="##}",
    )


application = StaticSiteFlask(__name__)

dotenv.load_dotenv(override = True)

YOOKASSA_SHOP_ID = os.getenv("YOOKASSA_SHOP_ID", "")
YOOKASSA_SECRET_KEY = os.getenv("YOOKASSA_SECRET_KEY", "")
YOOKASSA_CURRENCY = os.getenv("YOOKASSA_CURRENCY", "RUB")
YOOKASSA_API_URL = os.getenv("YOOKASSA_API_URL", "https://api.yookassa.ru/v3/payments")
YOOKASSA_RETURN_URL = os.getenv("YOOKASSA_RETURN_URL", "")
YANDEX_MAPS_API_KEY = os.getenv("YANDEX_MAPS_API_KEY", "14326938-97d2-483c-81c8-ada364bef9ed")



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
    auth = base64.b64encode(f"{YOOKASSA_SHOP_ID}:{YOOKASSA_SECRET_KEY}".encode("utf-8")).decode("ascii")
    req = urllib.request.Request(
        YOOKASSA_API_URL,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Basic {auth}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Idempotence-Key": str(uuid.uuid4()),
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            body = response.read().decode("utf-8")
            return json.loads(body), order_number
    except urllib.error.HTTPError as error:
        error_body = error.read().decode("utf-8", errors="replace") if error.fp else ""
        try:
            parsed = json.loads(error_body)
            message = parsed.get("description") or parsed.get("error") or error_body
        except json.JSONDecodeError:
            message = error_body or str(error)
        raise RuntimeError(f"Ошибка ЮKassa: {message}") from error


@application.cli.command("init-db")
def init_db_command():
    """Create and seed PostgreSQL tables."""
    init_products_table()
    print("PostgreSQL products table is ready.")


@application.route("/")
@application.route("/index.html")
def index():
    return render_template("index.html")


@application.route("/catalog.html")
def catalog():
    return render_template("catalog.html")


@application.route("/catalog-homme.html")
def catalog_homme():
    return render_template("catalog-homme.html")


@application.route("/product-tonic.html")
def product_tonic():
    return render_template("product-tonic.html")


@application.route("/subscription.html")
def subscription():
    return render_template("subscription.html")


@application.route("/checkout")
@application.route("/checkout.html")
def checkout():
    return render_template("checkout.html", yandex_maps_api_key=YANDEX_MAPS_API_KEY)


@application.route("/payment/success")
def payment_success():
    return render_template("checkout.html", yandex_maps_api_key=YANDEX_MAPS_API_KEY, payment_success=True)


@application.post("/api/yookassa/create-payment")
def create_yookassa_payment():
    payload = request.get_json(silent=True) or {}
    try:
        items, total, customer, delivery = _normalize_checkout_payload(payload)
        payment, order_number = _create_yookassa_payment(items, total, customer, delivery)
    except (ValueError, InvalidOperation) as error:
        return jsonify({"error": str(error)}), 400
    except Exception as error:
        return jsonify({"error": str(error)}), 502

    confirmation = payment.get("confirmation") or {}
    confirmation_url = confirmation.get("confirmation_url")
    if not confirmation_url:
        return jsonify({"error": "ЮKassa не вернула ссылку на оплату."}), 502
    return jsonify({"confirmation_url": confirmation_url, "payment_id": payment.get("id"), "order_number": order_number})


if __name__ == "__main__":
    application.run(debug=True)
