from datetime import date

from txnagent.detection.duplicates import find_overlapping_subscriptions
from txnagent.detection.recurring import detect_recurring_series
from txnagent.models import Category, Transaction


def _monthly(merchant: str, amount: float, category: Category, n: int = 4) -> list[Transaction]:
    return [
        Transaction(
            id=f"{merchant}-{i}",
            account_id="acc1",
            booking_date=date(2025, i + 1, 10),
            amount=amount,
            currency="EUR",
            counterparty_raw=merchant,
            category=category,
        )
        for i in range(n)
    ]


class TestFindOverlappingSubscriptions:
    def test_two_streaming_subscriptions_are_flagged_as_overlap(self):
        txns = (
            _monthly("NETFLIX.COM", -12.99, Category.SUBSCRIPTION)
            + _monthly("SPOTIFY AB", -9.99, Category.SUBSCRIPTION)
        )
        series = detect_recurring_series(txns)
        overlaps = find_overlapping_subscriptions(series)

        assert len(overlaps) == 1
        assert overlaps[0].category == Category.SUBSCRIPTION
        assert {s.display_name for s in overlaps[0].series} == {"Netflix.Com", "Spotify Ab"}

    def test_single_subscription_in_a_category_is_not_an_overlap(self):
        txns = _monthly("NETFLIX.COM", -12.99, Category.SUBSCRIPTION)
        series = detect_recurring_series(txns)
        assert find_overlapping_subscriptions(series) == []

    def test_two_recurring_utilities_are_not_flagged_as_overlap(self):
        # two active utility providers is normal (e.g. gas + electricity), not
        # the kind of redundant spend this feature is meant to surface
        txns = (
            _monthly("ENEL ENERGIA SPA", -80.0, Category.UTILITIES)
            + _monthly("VODAFONE ITALIA", -29.99, Category.UTILITIES)
        )
        series = detect_recurring_series(txns)
        assert find_overlapping_subscriptions(series) == []

    def test_overlaps_sorted_by_total_monthly_cost_descending(self):
        txns = (
            _monthly("NETFLIX.COM", -12.99, Category.SUBSCRIPTION)
            + _monthly("SPOTIFY AB", -9.99, Category.SUBSCRIPTION)
            + _monthly("RISTORANTE DA MARIO", -40.0, Category.ENTERTAINMENT)
            + _monthly("CINEMA THE SPACE", -25.0, Category.ENTERTAINMENT)
        )
        series = detect_recurring_series(txns)
        overlaps = find_overlapping_subscriptions(series)

        assert len(overlaps) == 2
        assert overlaps[0].total_monthly_cost >= overlaps[1].total_monthly_cost

    def test_total_monthly_cost_sums_the_group(self):
        txns = (
            _monthly("NETFLIX.COM", -12.99, Category.SUBSCRIPTION)
            + _monthly("SPOTIFY AB", -9.99, Category.SUBSCRIPTION)
        )
        series = detect_recurring_series(txns)
        [overlap] = find_overlapping_subscriptions(series)
        assert overlap.total_monthly_cost == sum(s.monthly_equivalent for s in overlap.series)
