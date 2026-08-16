"""Overlapping/duplicate subscription detection.

Rocket Money's stated feature set goes beyond just listing recurring
payments: it explicitly surfaces "potential duplicate charges" and redundant
services (see README's competitor comparison for sources). This module ships
the same signal at the granularity our data actually supports: we don't have
a finer merchant taxonomy than `Category` (see models.py), so "overlap" here
means two or more distinct, currently active recurring merchants in the same
subscription-like category — same coarse signal a first version of this
feature would ship anywhere, refined later with a real merchant-type
taxonomy instead of the bank's own spend category.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from txnagent.models import Category, RecurringSeries

#: Categories where paying for more than one active merchant is plausibly
#: redundant. Deliberately narrow: RENT_MORTGAGE or UTILITIES having two
#: active series is normal (two utility providers, a second home), not a
#: signal worth surfacing as "you might be double-paying".
OVERLAP_CATEGORIES: tuple[Category, ...] = (Category.SUBSCRIPTION, Category.ENTERTAINMENT)


@dataclass(slots=True)
class SubscriptionOverlap:
    """Two or more distinct recurring merchants active in the same category."""

    category: Category
    series: list[RecurringSeries]

    @property
    def total_monthly_cost(self) -> float:
        return sum(s.monthly_equivalent for s in self.series)


def find_overlapping_subscriptions(
    series: list[RecurringSeries],
    categories: tuple[Category, ...] = OVERLAP_CATEGORIES,
) -> list[SubscriptionOverlap]:
    """Group recurring series by category and return the categories with 2+
    distinct merchants — a plausible signal of redundant spend, not proof
    (two streaming subscriptions used by different household members are not
    actually wasteful). Sorted by total monthly cost descending, so the most
    expensive overlap surfaces first."""
    grouped: dict[Category, list[RecurringSeries]] = defaultdict(list)
    for s in series:
        if s.category in categories:
            grouped[s.category].append(s)

    overlaps = [
        SubscriptionOverlap(category=category, series=sorted(items, key=lambda s: s.display_name))
        for category, items in grouped.items()
        if len(items) >= 2
    ]
    return sorted(overlaps, key=lambda o: o.total_monthly_cost, reverse=True)
