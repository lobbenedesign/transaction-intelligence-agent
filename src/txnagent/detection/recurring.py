"""Recurring-payment detection.

Approach: group transactions by normalized merchant key, then score each
group on how *regular* its inter-transaction intervals and amounts are.
This is the same family of heuristic used in production subscription-
detection systems (interval regularity + amount stability), kept
deliberately explainable — no black-box model — because the agent needs to
justify *why* it flagged something as a subscription when a user asks.

Confidence is a weighted combination of:
  - interval regularity (low relative stdev of days-between-charges)
  - amount stability (low relative stdev of charged amount)
  - sample size (at least 2 occurrences; 3+ raises confidence)
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from datetime import timedelta

from txnagent.detection.normalize import normalize_merchant
from txnagent.models import Category, RecurringSeries, SeriesStatus, Transaction

MIN_OCCURRENCES = 2
#: Below this occurrence count a series is real but not yet mature enough to
#: fully trust — surfaced with SeriesStatus.EARLY_DETECTION instead of being
#: presented with the same confidence as a well-established stream. Mirrors
#: Plaid's Recurring Transactions "early_detection" status (streams with
#: fewer than 3 occurrences), see docs/adr/0005.
ESTABLISHED_MIN_OCCURRENCES = 3
MAX_INTERVAL_CV = 0.35  # coefficient of variation ceiling for "regular enough"
MAX_AMOUNT_CV = 0.25


def _coefficient_of_variation(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = statistics.mean(values)
    if abs(mean) < 1e-9:
        return 0.0
    return statistics.pstdev(values) / abs(mean)


def _confidence(interval_cv: float, amount_cv: float, n: int) -> float:
    interval_score = max(0.0, 1 - interval_cv / MAX_INTERVAL_CV)
    amount_score = max(0.0, 1 - amount_cv / MAX_AMOUNT_CV)
    size_score = min(1.0, (n - 1) / 4)  # saturates at 5 occurrences
    score = 0.45 * interval_score + 0.35 * amount_score + 0.20 * size_score
    return round(max(0.0, min(1.0, score)), 3)


def detect_recurring_series(
    transactions: list[Transaction],
    min_confidence: float = 0.55,
) -> list[RecurringSeries]:
    """Detect recurring series among a transaction list.

    Returns series sorted by confidence descending. Anything scoring below
    `min_confidence` is dropped — callers that want the raw candidates for
    debugging can pass `min_confidence=0.0`.
    """
    groups: dict[str, list[Transaction]] = defaultdict(list)
    for t in transactions:
        groups[normalize_merchant(t.counterparty_raw)].append(t)

    results: list[RecurringSeries] = []
    for key, group in groups.items():
        if len(group) < MIN_OCCURRENCES:
            continue
        group = sorted(group, key=lambda t: t.booking_date)

        intervals = [
            (group[i + 1].booking_date - group[i].booking_date).days
            for i in range(len(group) - 1)
        ]
        amounts = [t.amount for t in group]

        interval_median = statistics.median(intervals)
        interval_stdev = statistics.pstdev(intervals) if len(intervals) > 1 else 0.0
        amount_median = statistics.median(amounts)
        amount_stdev = statistics.pstdev(amounts) if len(amounts) > 1 else 0.0

        interval_cv = _coefficient_of_variation([float(i) for i in intervals])
        amount_cv = _coefficient_of_variation(amounts)
        confidence = _confidence(interval_cv, amount_cv, len(group))

        if confidence < min_confidence:
            continue

        category = group[-1].category or Category.OTHER
        next_expected = group[-1].booking_date + timedelta(days=round(interval_median))
        status = (
            SeriesStatus.ESTABLISHED
            if len(group) >= ESTABLISHED_MIN_OCCURRENCES
            else SeriesStatus.EARLY_DETECTION
        )

        results.append(
            RecurringSeries(
                merchant_key=key,
                display_name=group[-1].counterparty_raw.title(),
                transactions=group,
                interval_days_median=interval_median,
                interval_days_stdev=interval_stdev,
                amount_median=amount_median,
                amount_stdev=amount_stdev,
                confidence=confidence,
                category=category,
                status=status,
                next_expected_date=next_expected,
                metadata={"interval_cv": round(interval_cv, 3), "amount_cv": round(amount_cv, 3)},
            )
        )

    return sorted(results, key=lambda s: s.confidence, reverse=True)
