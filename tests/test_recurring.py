from datetime import date

import pytest

from txnagent.data.synthetic import generate_synthetic_history
from txnagent.detection.normalize import normalize_merchant
from txnagent.detection.recurring import ESTABLISHED_MIN_OCCURRENCES, detect_recurring_series
from txnagent.models import SeriesStatus, Transaction


def _make_monthly_series(merchant: str, amount: float, n: int = 6, day: int = 5) -> list[Transaction]:
    return [
        Transaction(
            id=f"t{i}",
            account_id="acc1",
            booking_date=date(2025, i + 1, day),
            amount=amount,
            currency="EUR",
            counterparty_raw=merchant,
        )
        for i in range(n)
    ]


class TestNormalize:
    def test_strips_legal_form_and_noise(self):
        assert normalize_merchant("NETFLIX.COM SPA RIF.12345") == "NETFLIX COM"

    def test_case_insensitive_and_stable(self):
        assert normalize_merchant("enel energia spa") == normalize_merchant("ENEL ENERGIA SPA")


class TestRecurringDetection:
    def test_detects_regular_monthly_series(self):
        txns = _make_monthly_series("NETFLIX.COM", -12.99)
        series = detect_recurring_series(txns)
        assert len(series) == 1
        assert series[0].confidence > 0.7
        assert abs(series[0].amount_median - (-12.99)) < 1e-6

    def test_ignores_single_occurrence(self):
        txns = _make_monthly_series("ONE OFF SHOP", -40.0, n=1)
        series = detect_recurring_series(txns)
        assert series == []

    def test_low_regularity_scores_low_confidence(self):
        # same merchant, wildly irregular intervals and amounts
        txns = [
            Transaction(id="a", account_id="x", booking_date=date(2025, 1, 3), amount=-10.0,
                        currency="EUR", counterparty_raw="RANDOM SHOP"),
            Transaction(id="b", account_id="x", booking_date=date(2025, 1, 20), amount=-85.0,
                        currency="EUR", counterparty_raw="RANDOM SHOP"),
            Transaction(id="c", account_id="x", booking_date=date(2025, 4, 2), amount=-3.0,
                        currency="EUR", counterparty_raw="RANDOM SHOP"),
        ]
        series = detect_recurring_series(txns, min_confidence=0.0)
        assert series[0].confidence < 0.55

    def test_monthly_equivalent_amortizes_annual_billing(self):
        txns = [
            Transaction(id=f"p{i}", account_id="x", booking_date=date(2023 + i, 6, 10), amount=-49.90,
                        currency="EUR", counterparty_raw="AMAZON PRIME")
            for i in range(3)
        ]
        series = detect_recurring_series(txns, min_confidence=0.0)
        assert series[0].monthly_equivalent == pytest.approx(49.90 / 12, abs=0.5)


class TestSyntheticGeneratorGroundTruth:
    def test_generator_is_deterministic(self):
        a = generate_synthetic_history(seed=7, months=6)
        b = generate_synthetic_history(seed=7, months=6)
        assert [t.id for t in a.transactions] == [t.id for t in b.transactions]
        assert [t.amount for t in a.transactions] == [t.amount for t in b.transactions]

    def test_recall_against_injected_ground_truth(self):
        dataset = generate_synthetic_history(seed=42, months=12)
        series = detect_recurring_series(dataset.transactions)
        detected = {s.merchant_key for s in series}
        ground_truth = {normalize_merchant(m) for m in dataset.ground_truth_recurring_merchants}
        recall = len(detected & ground_truth) / len(ground_truth)
        # documented in README's benchmark table; regression guard, not a tautology
        assert recall >= 0.8

    def test_no_oneoff_merchant_is_falsely_flagged_as_recurring(self):
        dataset = generate_synthetic_history(seed=42, months=12)
        series = detect_recurring_series(dataset.transactions, min_confidence=0.55)
        oneoff_names = {"ESSELUNGA SPA", "CONAD", "RISTORANTE DA MARIO", "BAR CENTRALE"}
        detected_display_names = {s.display_name.upper() for s in series}
        assert not (oneoff_names & detected_display_names)


class TestSeriesStatus:
    """Plaid-style early_detection vs established status — see docs/adr/0005."""

    def test_exactly_two_occurrences_is_early_detection(self):
        txns = _make_monthly_series("NEW GYM MEMBERSHIP", -40.0, n=2)
        [series] = detect_recurring_series(txns, min_confidence=0.0)
        assert len(series.transactions) < ESTABLISHED_MIN_OCCURRENCES
        assert series.status == SeriesStatus.EARLY_DETECTION

    def test_three_or_more_occurrences_is_established(self):
        txns = _make_monthly_series("NETFLIX.COM", -12.99, n=ESTABLISHED_MIN_OCCURRENCES)
        [series] = detect_recurring_series(txns, min_confidence=0.0)
        assert series.status == SeriesStatus.ESTABLISHED

    def test_early_detection_series_are_still_returned_not_hidden(self):
        # Competitors that only surface 3+ occurrence streams miss a brand-new
        # subscription for two billing cycles; we surface it immediately with
        # an honest status instead of pretending it isn't there yet.
        txns = _make_monthly_series("BRAND NEW STREAMING SERVICE", -9.99, n=2)
        series = detect_recurring_series(txns, min_confidence=0.0)
        assert len(series) == 1


class TestPriceIncreaseDetection:
    """Rocket Money's headline "subscription price increase" alert."""

    def test_stable_price_is_not_flagged(self):
        txns = _make_monthly_series("NETFLIX.COM", -12.99, n=4)
        [series] = detect_recurring_series(txns, min_confidence=0.0)
        assert series.price_increased is False
        assert series.price_change_pct == pytest.approx(0.0, abs=1e-9)

    def test_amount_growing_beyond_threshold_is_flagged(self):
        txns = [
            Transaction(id=f"p{i}", account_id="x", booking_date=date(2025, i + 1, 5), amount=amount,
                        currency="EUR", counterparty_raw="STREAMING PLUS")
            for i, amount in enumerate([-9.99, -9.99, -9.99, -13.99])  # +40% on the last charge
        ]
        [series] = detect_recurring_series(txns, min_confidence=0.0)
        assert series.price_increased is True
        assert series.price_change_pct == pytest.approx(0.4004, abs=0.01)

    def test_small_fluctuation_within_threshold_is_not_flagged(self):
        # consumption-based utility bill: amount varies, but not a "price increase"
        txns = [
            Transaction(id=f"p{i}", account_id="x", booking_date=date(2025, i + 1, 5), amount=amount,
                        currency="EUR", counterparty_raw="ENEL ENERGIA")
            for i, amount in enumerate([-50.0, -48.0, -51.0, -52.0])  # +4%, under the 5% threshold
        ]
        [series] = detect_recurring_series(txns, min_confidence=0.0)
        assert series.price_increased is False

    def test_growing_salary_is_never_flagged_as_a_price_increase(self):
        # an inflow growing is good news, not a "price increase" alert
        txns = [
            Transaction(id=f"s{i}", account_id="x", booking_date=date(2025, i + 1, 27), amount=amount,
                        currency="EUR", counterparty_raw="DATORE DI LAVORO SPA")
            for i, amount in enumerate([1750.0, 1750.0, 1750.0, 2200.0])
        ]
        [series] = detect_recurring_series(txns, min_confidence=0.0)
        assert series.price_increased is False
