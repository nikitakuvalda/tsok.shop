import unittest
from datetime import datetime, timezone
from decimal import Decimal

from d2c import (
    build_loyalty_event,
    build_subscription_notification,
    calculate_checkout_benefits,
    determine_loyalty_tier,
    referral_is_suspicious,
)


class D2CRulesTest(unittest.TestCase):
    def test_tier_recalculation_by_months_and_spend(self):
        self.assertEqual(determine_loyalty_tier(0, 0), "Silver")
        self.assertEqual(determine_loyalty_tier(3, 0), "Gold")
        self.assertEqual(determine_loyalty_tier(0, 15001), "Gold")
        self.assertEqual(determine_loyalty_tier(6, 0), "Platinum")
        self.assertEqual(determine_loyalty_tier(0, 30001), "Platinum")
        self.assertEqual(determine_loyalty_tier(12, 99999, "cancelled"), "Silver")

    def test_checkout_benefits_referral_and_coins_for_one_time_order(self):
        benefits = calculate_checkout_benefits(
            subtotal=1000,
            current_coins=500,
            loyalty_tier="Gold",
            referral_code="TSOK-CLUB-500",
            valid_referral_code="TSOK-CLUB-500",
            use_coins=True,
            is_subscription_box=False,
        )
        self.assertEqual(benefits["referral_discount"], Decimal("100.00"))
        self.assertEqual(benefits["coins_redeemed"], Decimal("300.00"))
        self.assertEqual(benefits["payable_total"], Decimal("600.00"))
        self.assertEqual(benefits["coins_pending"], Decimal("30.00"))

    def test_coins_are_not_redeemed_for_subscription_box(self):
        benefits = calculate_checkout_benefits(
            subtotal=1000,
            current_coins=500,
            loyalty_tier="Platinum",
            use_coins=True,
            is_subscription_box=True,
        )
        self.assertEqual(benefits["coins_redeemed"], Decimal("0"))
        self.assertEqual(benefits["coins_pending"], Decimal("100.00"))

    def test_loyalty_event_dates(self):
        now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        event = build_loyalty_event(1000, "Silver", now)
        self.assertEqual(event["coins_delta"], Decimal("30.00"))
        self.assertEqual((event["available_at"] - now).days, 14)
        self.assertEqual((event["expires_at"] - now).days, 180)

    def test_notification_is_72_hours_before_charge(self):
        charge_at = datetime(2026, 1, 10, 12, tzinfo=timezone.utc)
        notification = build_subscription_notification("sub-1", charge_at)
        self.assertEqual((charge_at - notification["send_at"]).total_seconds(), 72 * 3600)

    def test_referral_anti_fraud(self):
        self.assertTrue(referral_is_suspicious("ip-a", "ip-a"))
        self.assertTrue(referral_is_suspicious("ip-a", "ip-b", "same-card"))
        self.assertFalse(referral_is_suspicious("ip-a", "ip-b", "card-b"))


if __name__ == "__main__":
    unittest.main()
