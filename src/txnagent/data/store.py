"""In-memory transaction store.

Deliberately not a database: this project's point is the agent/detection
logic, not persistence. Swapping this for a Postgres-backed repository is a
single-file change (same public methods) — noted in docs/adr/0003.
"""

from __future__ import annotations

from datetime import date

from txnagent.detection.categorize import categorize_all
from txnagent.detection.duplicates import SubscriptionOverlap, find_overlapping_subscriptions
from txnagent.detection.recurring import detect_recurring_series
from txnagent.models import Category, RecurringSeries, Transaction


class TransactionStore:
    def __init__(self, transactions: list[Transaction]) -> None:
        self._transactions = categorize_all(transactions)
        self._recurring_cache: list[RecurringSeries] | None = None

    @property
    def transactions(self) -> list[Transaction]:
        return list(self._transactions)

    def recurring_series(self, min_confidence: float = 0.55) -> list[RecurringSeries]:
        if self._recurring_cache is None:
            self._recurring_cache = detect_recurring_series(self._transactions, min_confidence=0.0)
        return [s for s in self._recurring_cache if s.confidence >= min_confidence]

    def price_increases(self, min_confidence: float = 0.55) -> list[RecurringSeries]:
        """Recurring series whose most recent charge grew beyond
        PRICE_INCREASE_THRESHOLD relative to its first — Rocket Money's
        "subscription price increase" alert."""
        return [s for s in self.recurring_series(min_confidence) if s.price_increased]

    def overlapping_subscriptions(self, min_confidence: float = 0.55) -> list[SubscriptionOverlap]:
        """Categories with 2+ distinct active recurring merchants — Rocket
        Money's "potential duplicate" / redundant-service signal."""
        return find_overlapping_subscriptions(self.recurring_series(min_confidence))

    def spending_by_category(
        self,
        category: Category | str | None = None,
        since: date | None = None,
        until: date | None = None,
    ) -> tuple[float, int]:
        cat = Category(category) if isinstance(category, str) else category
        total = 0.0
        count = 0
        for t in self._transactions:
            if not t.is_outflow():
                continue
            if cat is not None and t.category != cat:
                continue
            if since and t.booking_date < since:
                continue
            if until and t.booking_date > until:
                continue
            total += t.amount
            count += 1
        return round(total, 2), count

    def list_transactions(
        self,
        limit: int = 20,
        category: Category | str | None = None,
    ) -> list[Transaction]:
        cat = Category(category) if isinstance(category, str) else category
        items = self._transactions
        if cat is not None:
            items = [t for t in items if t.category == cat]
        return sorted(items, key=lambda t: t.booking_date, reverse=True)[:limit]
