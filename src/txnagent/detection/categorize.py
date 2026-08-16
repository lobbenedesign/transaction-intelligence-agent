"""Merchant categorization.

A small deterministic keyword classifier. It is intentionally *not* an LLM
call: categorization runs on every transaction (thousands per customer per
year), so it needs to be cheap, fast and auditable. The LLM agent layer
consumes these categories as a tool result rather than re-deriving them —
see docs/adr/0002 for why.
"""

from __future__ import annotations

from txnagent.detection.normalize import normalize_merchant
from txnagent.models import Category, Transaction

_KEYWORD_RULES: list[tuple[tuple[str, ...], Category]] = [
    (("NETFLIX", "SPOTIFY", "PRIME", "ICLOUD", "PALESTRA", "FITNESS"), Category.SUBSCRIPTION),
    (("ENEL", "ACEA", "VODAFONE", "TIM ", "WINDTRE", "GAS", "LUCE"), Category.UTILITIES),
    (("ESSELUNGA", "CONAD", "COOP", "CARREFOUR", "LIDL"), Category.GROCERIES),
    (("TRENITALIA", "ATM ", "ITALO", "TAXI", "UBER"), Category.TRANSPORT),
    (("AFFITTO", "MUTUO",), Category.RENT_MORTGAGE),
    (("ASSICURA", "GENERALI", "ALLIANZ", "UNIPOL"), Category.INSURANCE),
    (("RISTORANTE", "CINEMA", "BAR ", "TEATRO"), Category.ENTERTAINMENT),
    (("STIPENDIO", "ACCREDITO SALARIO"), Category.SALARY_INCOME),
    (("BONIFICO", "GIROCONTO"), Category.TRANSFER),
]


def categorize(transaction: Transaction) -> tuple[Category, float]:
    """Return (category, confidence). Confidence is 0.9 for a keyword hit,
    0.3 for the OTHER fallback — callers can use this to decide whether to
    ask an LLM (or the user) to disambiguate."""
    haystack = normalize_merchant(transaction.counterparty_raw) + " " + transaction.description_raw.upper()
    for keywords, category in _KEYWORD_RULES:
        if any(k in haystack for k in keywords):
            return category, 0.9
    return Category.OTHER, 0.3


def categorize_all(transactions: list[Transaction]) -> list[Transaction]:
    """Return a new list with `.category` filled in where missing."""
    out = []
    for t in transactions:
        if t.category is not None:
            out.append(t)
            continue
        category, _ = categorize(t)
        out.append(
            Transaction(
                id=t.id,
                account_id=t.account_id,
                booking_date=t.booking_date,
                amount=t.amount,
                currency=t.currency,
                counterparty_raw=t.counterparty_raw,
                description_raw=t.description_raw,
                category=category,
            )
        )
    return out
