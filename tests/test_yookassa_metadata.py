from decimal import Decimal

from app import _build_yookassa_metadata


def test_yookassa_metadata_is_compact_for_full_checkout_payload():
    customer = {
        "fio": "Иван Иванов",
        "phone": "+79990000000",
        "email": "ivan@example.com",
    }
    delivery = {
        "city": "Москва",
        "address": "Красная площадь, 1" * 30,
        "comment": "Позвонить за час" * 30,
        "pvz_provider": "cdek",
        "pvz_name": "ПВЗ у метро" * 20,
        "pvz_address": "Тверская, 10" * 30,
        "pvz_coordinates": "55.753930,37.620795",
    }
    quote = {
        "plan_code": "12m",
        "plan_label": "VIP 12 месяцев",
        "item_count": 5,
        "discount_percent": 30,
        "free_delivery": True,
        "vip_gift": "quartz-roller",
    }
    benefits = {
        "loyalty_tier": "Platinum",
        "cashback_percent": 10,
        "referral_code": "TSOK-CLUB-500",
        "referral_status": "applied",
        "referral_discount": Decimal("500.00"),
        "coins_redeemed": Decimal("300.00"),
        "coins_pending": Decimal("100.00"),
    }

    metadata = _build_yookassa_metadata("TSOK-1", customer, delivery, quote, benefits)

    assert len(metadata) <= 16
    assert all(isinstance(key, str) and len(key) <= 32 for key in metadata)
    assert all(isinstance(value, str) and len(value) <= 512 for value in metadata.values())
    assert metadata["delivery_pvz"].startswith("cdek | ПВЗ у метро")
    assert "tier:Platinum" in metadata["loyalty_info"]
