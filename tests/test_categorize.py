from datetime import date

from txnagent.detection.categorize import categorize, categorize_all
from txnagent.models import Category, Transaction


def _txn(counterparty: str, description: str = "") -> Transaction:
    return Transaction(
        id="t1", account_id="a1", booking_date=date(2025, 1, 1), amount=-10.0,
        currency="EUR", counterparty_raw=counterparty, description_raw=description,
    )


class TestCategorize:
    def test_known_subscription_merchant(self):
        category, confidence = categorize(_txn("NETFLIX.COM"))
        assert category == Category.SUBSCRIPTION
        assert confidence > 0.5

    def test_unknown_merchant_falls_back_to_other_with_low_confidence(self):
        category, confidence = categorize(_txn("MERCHANT SCONOSCIUTO XYZ 999"))
        assert category == Category.OTHER
        assert confidence < 0.5

    def test_categorize_all_preserves_existing_category(self):
        pre_categorized = Transaction(
            id="t2", account_id="a1", booking_date=date(2025, 1, 1), amount=-5.0,
            currency="EUR", counterparty_raw="ANYTHING", category=Category.ENTERTAINMENT,
        )
        [result] = categorize_all([pre_categorized])
        assert result.category == Category.ENTERTAINMENT

    def test_categorize_all_fills_missing_category(self):
        [result] = categorize_all([_txn("ENEL ENERGIA SPA")])
        assert result.category == Category.UTILITIES
