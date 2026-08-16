"""Synthetic transaction generator.

No real banking data is used anywhere in this project (see README §Limiti
noti). This generator produces a plausible 12-month current-account history
for one synthetic customer, with recurring series (subscriptions, rent,
utilities, insurance) injected on top of noisy one-off spending — so the
recurring-detection algorithm has honest ground truth to be scored against.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import date, timedelta

from txnagent.models import Category, Transaction

# (merchant, monthly-ish amount range, category, day-of-month jitter, cadence in months)
RECURRING_TEMPLATES: list[tuple[str, tuple[float, float], Category, int]] = [
    ("NETFLIX.COM", (-12.99, -12.99), Category.SUBSCRIPTION, 1),
    ("SPOTIFY AB", (-9.99, -9.99), Category.SUBSCRIPTION, 1),
    ("AMAZON PRIME", (-49.90, -49.90), Category.SUBSCRIPTION, 12),
    ("ENEL ENERGIA SPA", (-45.0, -110.0), Category.UTILITIES, 1),
    ("ACEA ATO2", (-20.0, -60.0), Category.UTILITIES, 2),
    ("VODAFONE ITALIA", (-29.99, -29.99), Category.UTILITIES, 1),
    ("AFFITTO APPARTAMENTO VIA ROMA 12", (-850.0, -850.0), Category.RENT_MORTGAGE, 1),
    ("GENERALI ITALIA ASSICURAZIONI", (-38.5, -38.5), Category.INSURANCE, 1),
    ("PALESTRA FITNESS CLUB MILANO", (-55.0, -55.0), Category.SUBSCRIPTION, 1),
    ("ICLOUD STORAGE APPLE", (-2.99, -2.99), Category.SUBSCRIPTION, 1),
]

ONEOFF_MERCHANTS: list[tuple[str, tuple[float, float], Category]] = [
    ("ESSELUNGA SPA", (-15.0, -140.0), Category.GROCERIES),
    ("CONAD", (-10.0, -90.0), Category.GROCERIES),
    ("TRENITALIA", (-9.0, -75.0), Category.TRANSPORT),
    ("ATM MILANO", (-1.5, -22.0), Category.TRANSPORT),
    ("RISTORANTE DA MARIO", (-18.0, -95.0), Category.ENTERTAINMENT),
    ("CINEMA THE SPACE", (-8.5, -30.0), Category.ENTERTAINMENT),
    ("BAR CENTRALE", (-1.2, -12.0), Category.ENTERTAINMENT),
    ("ZARA", (-19.9, -180.0), Category.OTHER),
]

SALARY_MERCHANT = "DATORE DI LAVORO SPA - STIPENDIO"

#: A merchant whose price steps up partway through the year — real streaming
#: services do this routinely. Injected so the demo and the price-increase
#: tests (docs/adr/0005) have an honest positive case to detect, not just
#: negative cases where nothing fires.
PRICE_INCREASE_MERCHANT = "DAZN ITALIA"
PRICE_BEFORE_INCREASE = -29.99
PRICE_AFTER_INCREASE = -39.99
PRICE_INCREASE_AT_MONTH = 6


@dataclass
class GeneratedDataset:
    transactions: list[Transaction]
    ground_truth_recurring_merchants: set[str]


def _jitter_amount(rng: random.Random, lo: float, hi: float) -> float:
    return round(rng.uniform(min(lo, hi), max(lo, hi)), 2)


def generate_synthetic_history(
    account_id: str = "IT60X0542811101000000123456",
    months: int = 12,
    start: date | None = None,
    seed: int = 42,
) -> GeneratedDataset:
    """Deterministic (seeded) generator — same seed always produces the same
    dataset, which is what makes the demo and the golden tests reproducible."""

    rng = random.Random(seed)
    start = start or date.today().replace(day=1) - timedelta(days=30 * months)

    txns: list[Transaction] = []
    ground_truth: set[str] = set()
    counter = 0

    for merchant, (lo, hi), category, cadence_months in RECURRING_TEMPLATES:
        ground_truth.add(merchant)
        day_of_month = rng.randint(1, 27)
        month_cursor = 0
        while month_cursor < months:
            billing_month = start.month - 1 + month_cursor
            year = start.year + billing_month // 12
            month = billing_month % 12 + 1
            day = min(day_of_month, 28)
            booking_date = date(year, month, day) + timedelta(days=rng.randint(-2, 2))
            amount = _jitter_amount(rng, lo, hi)
            counter += 1
            txns.append(
                Transaction(
                    id=f"txn-{counter:05d}",
                    account_id=account_id,
                    booking_date=booking_date,
                    amount=amount,
                    currency="EUR",
                    counterparty_raw=merchant,
                    description_raw=f"PAGAMENTO {merchant}",
                    category=category,
                )
            )
            month_cursor += cadence_months

    # monthly salary — an inflow recurring series, useful to test that
    # detection is sign-agnostic and category-aware
    for m in range(months):
        billing_month = start.month - 1 + m
        year = start.year + billing_month // 12
        month = billing_month % 12 + 1
        booking_date = date(year, month, 27)
        counter += 1
        txns.append(
            Transaction(
                id=f"txn-{counter:05d}",
                account_id=account_id,
                booking_date=booking_date,
                amount=round(rng.uniform(1750, 1780), 2),
                currency="EUR",
                counterparty_raw=SALARY_MERCHANT,
                description_raw="ACCREDITO STIPENDIO",
                category=Category.SALARY_INCOME,
            )
        )

    # streaming subscription with a mid-year price increase — a positive
    # ground-truth case for price-increase detection, not just an absence of
    # false positives on the flat-priced templates above
    ground_truth.add(PRICE_INCREASE_MERCHANT)
    day_of_month = rng.randint(1, 27)
    for m in range(months):
        billing_month = start.month - 1 + m
        year = start.year + billing_month // 12
        month = billing_month % 12 + 1
        day = min(day_of_month, 28)
        booking_date = date(year, month, day) + timedelta(days=rng.randint(-2, 2))
        amount = PRICE_BEFORE_INCREASE if m < PRICE_INCREASE_AT_MONTH else PRICE_AFTER_INCREASE
        counter += 1
        txns.append(
            Transaction(
                id=f"txn-{counter:05d}",
                account_id=account_id,
                booking_date=booking_date,
                amount=amount,
                currency="EUR",
                counterparty_raw=PRICE_INCREASE_MERCHANT,
                description_raw=f"PAGAMENTO {PRICE_INCREASE_MERCHANT}",
                category=Category.SUBSCRIPTION,
            )
        )

    # noisy one-off spending, several per week
    days_total = months * 30
    for day_offset in range(days_total):
        current_day = start + timedelta(days=day_offset)
        n_events = rng.choices([0, 1, 2, 3], weights=[35, 40, 18, 7])[0]
        for _ in range(n_events):
            merchant, (lo, hi), category = rng.choice(ONEOFF_MERCHANTS)
            counter += 1
            txns.append(
                Transaction(
                    id=f"txn-{counter:05d}",
                    account_id=account_id,
                    booking_date=current_day,
                    amount=_jitter_amount(rng, lo, hi),
                    currency="EUR",
                    counterparty_raw=merchant,
                    description_raw=f"POS {merchant}",
                    category=category,
                )
            )

    txns.sort(key=lambda t: t.booking_date)
    return GeneratedDataset(transactions=txns, ground_truth_recurring_merchants=ground_truth)
