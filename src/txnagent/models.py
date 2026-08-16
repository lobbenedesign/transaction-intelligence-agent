"""Core domain types.

Kept deliberately small and dependency-free (stdlib dataclasses only) so the
detection and categorization logic can be unit tested without pulling in any
LLM or web framework.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum


class Category(StrEnum):
    SUBSCRIPTION = "subscription"
    UTILITIES = "utilities"
    GROCERIES = "groceries"
    TRANSPORT = "transport"
    RENT_MORTGAGE = "rent_mortgage"
    INSURANCE = "insurance"
    ENTERTAINMENT = "entertainment"
    SALARY_INCOME = "salary_income"
    TRANSFER = "transfer"
    OTHER = "other"


class SeriesStatus(StrEnum):
    """Mirrors Plaid's Recurring Transactions status field: a stream seen
    fewer times than ESTABLISHED_MIN_OCCURRENCES (see detection/recurring.py)
    is real but not yet mature enough to fully trust its interval/amount
    statistics — surfaced as such instead of either hiding it (competitors
    that only show 3+ occurrence series miss new subscriptions for months)
    or presenting it with the same confidence as a well-established one."""

    EARLY_DETECTION = "early_detection"
    ESTABLISHED = "established"


@dataclass(frozen=True, slots=True)
class Transaction:
    """A single posted transaction on a current account.

    `amount` is signed: negative for outflows, positive for inflows — this
    mirrors how core banking ledgers represent movements and avoids a whole
    class of sign-handling bugs downstream.
    """

    id: str
    account_id: str
    booking_date: date
    amount: float
    currency: str
    counterparty_raw: str
    description_raw: str = ""
    category: Category | None = None

    def is_outflow(self) -> bool:
        return self.amount < 0


#: A recurring charge whose magnitude grew by more than this fraction between
#: its first and most recent occurrence is flagged as a price increase — the
#: same signal Rocket Money surfaces as "subscription price increase" alerts.
PRICE_INCREASE_THRESHOLD = 0.05


@dataclass(slots=True)
class RecurringSeries:
    """A detected group of transactions that behave like a recurring payment
    (subscription, utility bill, rent, ...)."""

    merchant_key: str
    display_name: str
    transactions: list[Transaction]
    interval_days_median: float
    interval_days_stdev: float
    amount_median: float
    amount_stdev: float
    confidence: float
    category: Category
    status: SeriesStatus = SeriesStatus.ESTABLISHED
    next_expected_date: date | None = None
    metadata: dict = field(default_factory=dict)

    @property
    def monthly_equivalent(self) -> float:
        """Amortize the median amount to a monthly cadence, using the
        detected interval — lets the agent answer 'how much do I spend
        monthly on subscriptions' even when billing is quarterly/annual."""
        if self.interval_days_median <= 0:
            return abs(self.amount_median)
        months = self.interval_days_median / 30.44
        return abs(self.amount_median) / max(months, 1e-6)

    @property
    def first_amount(self) -> float:
        """`transactions` is kept sorted chronologically by the detector."""
        return self.transactions[0].amount

    @property
    def last_amount(self) -> float:
        return self.transactions[-1].amount

    @property
    def price_change_pct(self) -> float | None:
        """Signed percentage change in magnitude between the first and most
        recent occurrence. None when the first occurrence's amount is (near)
        zero, where a percentage change is not meaningful."""
        first, last = abs(self.first_amount), abs(self.last_amount)
        if first < 1e-9:
            return None
        return (last - first) / first

    @property
    def price_increased(self) -> bool:
        """True only for outflows whose cost grew beyond PRICE_INCREASE_THRESHOLD
        — an inflow (e.g. a salary raise) growing is good news, not an alert."""
        pct = self.price_change_pct
        return self.first_amount < 0 and pct is not None and pct > PRICE_INCREASE_THRESHOLD
