from datetime import datetime, timedelta, timezone
from decimal import Decimal

LOYALTY_TIERS = {
    "Silver": {"cashback": Decimal("0.03"), "early_sale_hours": 0, "free_delivery": False},
    "Gold": {"cashback": Decimal("0.05"), "early_sale_hours": 24, "free_delivery": False},
    "Platinum": {"cashback": Decimal("0.10"), "early_sale_hours": 24, "free_delivery": True},
}
REFERRAL_FIRST_ORDER_DISCOUNT = Decimal("0.10")
COINS_REDEEM_LIMIT = Decimal("0.30")
REFERRAL_REWARD_COINS = Decimal("500")
COINS_AVAILABLE_AFTER_DAYS = 14
COINS_EXPIRE_AFTER_DAYS = 180
NOTIFICATION_BEFORE_HOURS = 72


def money(value):
    return Decimal(str(value or "0")).quantize(Decimal("0.01"))


def determine_loyalty_tier(subscription_months=0, annual_spend=0, subscription_status="active"):
    if subscription_status == "cancelled":
        return "Silver"
    months = int(subscription_months or 0)
    spend = money(annual_spend)
    if months >= 6 or spend > Decimal("30000"):
        return "Platinum"
    if months >= 3 or spend > Decimal("15000"):
        return "Gold"
    return "Silver"


def calculate_checkout_benefits(
    subtotal,
    current_coins=0,
    loyalty_tier="Silver",
    referral_code="",
    valid_referral_code="",
    use_coins=False,
    is_subscription_box=False,
):
    subtotal = money(subtotal)
    referral_code = str(referral_code or "").strip().upper()
    valid_referral_code = str(valid_referral_code or "").strip().upper()
    referral_discount = Decimal("0")
    referral_status = "not_applied"
    if referral_code:
        if referral_code == valid_referral_code:
            referral_discount = (subtotal * REFERRAL_FIRST_ORDER_DISCOUNT).quantize(Decimal("0.01"))
            referral_status = "applied"
        else:
            referral_status = "invalid"

    coins_redeemed = Decimal("0")
    if use_coins and not is_subscription_box:
        max_redeem = (subtotal * COINS_REDEEM_LIMIT).quantize(Decimal("0.01"))
        coins_redeemed = min(money(current_coins), max_redeem, subtotal - referral_discount)

    payable_total = max(Decimal("0"), subtotal - referral_discount - coins_redeemed)
    tier_rules = LOYALTY_TIERS.get(loyalty_tier, LOYALTY_TIERS["Silver"])
    coins_pending = (payable_total * tier_rules["cashback"]).quantize(Decimal("0.01"))
    return {
        "referral_code": referral_code,
        "referral_status": referral_status,
        "referral_discount": referral_discount,
        "coins_redeemed": coins_redeemed,
        "coins_pending": coins_pending,
        "payable_total": payable_total,
        "loyalty_tier": loyalty_tier if loyalty_tier in LOYALTY_TIERS else "Silver",
        "cashback_percent": int(tier_rules["cashback"] * 100),
    }


def build_loyalty_event(delivered_total, loyalty_tier="Silver", now=None):
    now = now or datetime.now(timezone.utc)
    tier_rules = LOYALTY_TIERS.get(loyalty_tier, LOYALTY_TIERS["Silver"])
    coins = (money(delivered_total) * tier_rules["cashback"]).quantize(Decimal("0.01"))
    return {
        "event_type": "cashback_pending",
        "coins_delta": coins,
        "available_at": now + timedelta(days=COINS_AVAILABLE_AFTER_DAYS),
        "expires_at": now + timedelta(days=COINS_EXPIRE_AFTER_DAYS),
    }


def build_subscription_notification(subscription_id, next_charge_at):
    if isinstance(next_charge_at, str):
        next_charge_at = datetime.fromisoformat(next_charge_at)
    return {
        "subscription_id": subscription_id,
        "channel": "email+telegram",
        "send_at": next_charge_at - timedelta(hours=NOTIFICATION_BEFORE_HOURS),
        "payload": "Мы начинаем собирать твой бокс! У тебя есть 48 часов, чтобы поменять состав или пропустить месяц.",
    }


def referral_is_suspicious(referrer_fingerprint, referred_fingerprint, card_fingerprint=""):
    referrer_fingerprint = str(referrer_fingerprint or "").strip()
    referred_fingerprint = str(referred_fingerprint or "").strip()
    card_fingerprint = str(card_fingerprint or "").strip()
    return bool(referrer_fingerprint and referrer_fingerprint == referred_fingerprint) or card_fingerprint == "same-card"
