"""Tool schema + registry.

The schema follows the OpenAI function-calling JSON shape (widely adopted as
a de-facto standard across providers), so `OpenAIClient` needs no
translation layer and `FakeLLM` reads the same `tools` list to know what
names are available — one schema, two consumers.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from txnagent.data.store import TransactionStore

TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "list_recurring_series",
            "description": "List detected recurring payments (subscriptions, bills, rent) "
            "with amount, cadence and confidence.",
            "parameters": {
                "type": "object",
                "properties": {
                    "min_confidence": {"type": "number", "description": "0-1, default 0.55"}
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "sum_spending_by_category",
            "description": "Sum outflow transactions, optionally filtered by category.",
            "parameters": {
                "type": "object",
                "properties": {
                    "category": {
                        "type": "string",
                        "enum": [
                            "subscription", "utilities", "groceries", "transport",
                            "rent_mortgage", "insurance", "entertainment", "other",
                        ],
                    }
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_transactions",
            "description": "List the most recent transactions, optionally filtered by category.",
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "default": 10},
                    "category": {"type": "string"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_price_increases",
            "description": "List recurring payments whose amount grew between their first and most "
            "recent occurrence (a subscription or bill got more expensive).",
            "parameters": {
                "type": "object",
                "properties": {
                    "min_confidence": {"type": "number", "description": "0-1, default 0.55"}
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_subscription_overlaps",
            "description": "List categories where the customer has 2 or more distinct active "
            "recurring subscriptions (e.g. two video-streaming services) — a possible redundant spend.",
            "parameters": {
                "type": "object",
                "properties": {
                    "min_confidence": {"type": "number", "description": "0-1, default 0.55"}
                },
            },
        },
    },
]


@dataclass
class ToolRegistry:
    store: TransactionStore

    def dispatch(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Never raise: a tool call comes from the LLM's own (fallible) choice of
        name and arguments, so a malformed call — an unknown tool, a category
        string outside the enum, a missing required argument — must come back as
        a structured error the model can react to, not an exception that aborts
        the whole request. See test_tools.py for the cases this guards against."""
        handler: Callable[..., dict[str, Any]] | None = getattr(self, f"_tool_{name}", None)
        if handler is None:
            return {"_tool": name, "error": f"unknown tool '{name}'"}
        try:
            return handler(**arguments)
        except ValueError as exc:
            return {"_tool": name, "error": f"invalid arguments: {exc}"}
        except TypeError as exc:
            return {"_tool": name, "error": f"malformed tool call: {exc}"}

    def _tool_list_recurring_series(self, min_confidence: float = 0.55) -> dict[str, Any]:
        series = self.store.recurring_series(min_confidence=min_confidence)
        return {
            "_tool": "list_recurring_series",
            "series": [
                {
                    "display_name": s.display_name,
                    "amount_median": s.amount_median,
                    "interval_days_median": s.interval_days_median,
                    "confidence": s.confidence,
                    "category": s.category.value,
                    "monthly_equivalent": s.monthly_equivalent,
                    "next_expected_date": s.next_expected_date.isoformat() if s.next_expected_date else None,
                    "status": s.status.value,
                    "price_increased": s.price_increased,
                }
                for s in series
            ],
        }

    def _tool_list_price_increases(self, min_confidence: float = 0.55) -> dict[str, Any]:
        series = self.store.price_increases(min_confidence=min_confidence)
        return {
            "_tool": "list_price_increases",
            "series": [
                {
                    "display_name": s.display_name,
                    "first_amount": s.first_amount,
                    "last_amount": s.last_amount,
                    "price_change_pct": (
                        round(s.price_change_pct, 4) if s.price_change_pct is not None else None
                    ),
                    "category": s.category.value,
                }
                for s in series
            ],
        }

    def _tool_list_subscription_overlaps(self, min_confidence: float = 0.55) -> dict[str, Any]:
        overlaps = self.store.overlapping_subscriptions(min_confidence=min_confidence)
        return {
            "_tool": "list_subscription_overlaps",
            "overlaps": [
                {
                    "category": o.category.value,
                    "merchants": [s.display_name for s in o.series],
                    "total_monthly_cost": round(o.total_monthly_cost, 2),
                }
                for o in overlaps
            ],
        }

    def _tool_sum_spending_by_category(self, category: str | None = None) -> dict[str, Any]:
        total, count = self.store.spending_by_category(category=category)
        return {"_tool": "sum_spending_by_category", "category": category, "total": total, "count": count}

    def _tool_list_transactions(self, limit: int = 10, category: str | None = None) -> dict[str, Any]:
        txns = self.store.list_transactions(limit=limit, category=category)
        return {
            "_tool": "list_transactions",
            "transactions": [
                {
                    "booking_date": t.booking_date.isoformat(),
                    "counterparty_raw": t.counterparty_raw,
                    "amount": t.amount,
                    "category": t.category.value if t.category else None,
                }
                for t in txns
            ],
        }
