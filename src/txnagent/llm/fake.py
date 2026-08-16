"""Deterministic, offline LLM client.

This is what `make demo`, the FastAPI service (by default) and the whole
test suite run against — no API key required, fully reproducible output.
It plays the same *role* in the agent loop a real model would: decide which
tool to call from the user's message, then turn tool results into a
natural-language answer. The decision logic is keyword-based rather than
learned, which is the honest trade-off stated in docs/adr/0001 — swapping in
`OpenAIClient` (src/txnagent/llm/openai_client.py) upgrades this to a real
model without touching the agent loop or the tool schema.
"""

from __future__ import annotations

import json

from txnagent.llm.base import LLMClient, LLMResponse, ToolCall

_PRICE_INCREASE_KEYWORDS = ("aumentat", "rincar", "cresciuto di prezzo", "più caro", "price increase")
_OVERLAP_KEYWORDS = ("doppion", "duplicat", "due abbonamenti", "pagando due volte", "sovrappost", "ridondant")
_RECURRING_KEYWORDS = ("abbonament", "ricorrent", "subscription", "prossimo pagamento", "quando pago")
_SPEND_KEYWORDS = ("quanto ho speso", "spesa", "spese", "quanto spendo", "costo")
_LIST_KEYWORDS = ("elenca", "mostrami", "lista", "transazioni")


class FakeLLM(LLMClient):
    def complete(
        self,
        system_prompt: str,
        messages: list[dict[str, str]],
        tools: list[dict[str, object]],
    ) -> LLMResponse:
        tool_names = {t["function"]["name"] for t in tools} if tools and "function" in tools[0] else {
            t["name"] for t in tools
        }

        last_user = self._last_user_message(messages)
        tool_results = self._pending_tool_results(messages)

        if tool_results:
            return LLMResponse(content=self._synthesize(last_user, tool_results))

        query = (last_user or "").lower()

        # Checked before the generic recurring-payment branch: a query like
        # "è aumentato il prezzo di un abbonamento?" contains "abbonament" too,
        # and the more specific intent should win.
        if any(k in query for k in _PRICE_INCREASE_KEYWORDS) and "list_price_increases" in tool_names:
            return LLMResponse(tool_calls=[ToolCall(name="list_price_increases", arguments={})])

        if any(k in query for k in _OVERLAP_KEYWORDS) and "list_subscription_overlaps" in tool_names:
            return LLMResponse(tool_calls=[ToolCall(name="list_subscription_overlaps", arguments={})])

        if any(k in query for k in _RECURRING_KEYWORDS) and "list_recurring_series" in tool_names:
            return LLMResponse(tool_calls=[ToolCall(name="list_recurring_series", arguments={})])

        if any(k in query for k in _SPEND_KEYWORDS) and "sum_spending_by_category" in tool_names:
            category = self._guess_category(query)
            return LLMResponse(
                tool_calls=[ToolCall(name="sum_spending_by_category", arguments={"category": category})]
            )

        if any(k in query for k in _LIST_KEYWORDS) and "list_transactions" in tool_names:
            return LLMResponse(tool_calls=[ToolCall(name="list_transactions", arguments={"limit": 10})])

        # Nessuna keyword riconosciuta: meglio chiedere chiarimento che rispondere con
        # sicurezza a un argomento sbagliato. Un router che risponde sempre qualcosa,
        # anche fuori dal proprio dominio di competenza, è più pericoloso di uno che
        # a volte dice "non ho capito" — specialmente su dati finanziari di un cliente.
        return LLMResponse(
            content="Non ho capito bene la domanda. Prova a chiedermi ad esempio: "
            "'quali abbonamenti ho attivi?' oppure 'quanto ho speso in ristoranti questo mese?'."
        )

    @staticmethod
    def _last_user_message(messages: list[dict[str, str]]) -> str | None:
        for m in reversed(messages):
            if m.get("role") == "user":
                return m.get("content")
        return None

    @staticmethod
    def _pending_tool_results(messages: list[dict[str, str]]) -> list[dict]:
        results: list[dict] = []
        for m in reversed(messages):
            if m.get("role") == "user":
                break
            if m.get("role") == "tool":
                try:
                    results.append(json.loads(m["content"]))
                except (json.JSONDecodeError, KeyError):
                    continue
        return list(reversed(results))

    @staticmethod
    def _guess_category(query: str) -> str | None:
        mapping = {
            "ristorant": "entertainment",
            "cinema": "entertainment",
            "spesa": "groceries",
            "supermerc": "groceries",
            "affitto": "rent_mortgage",
            "abbonament": "subscription",
            "bolletta": "utilities",
            "utenz": "utilities",
        }
        for key, category in mapping.items():
            if key in query:
                return category
        return None

    @staticmethod
    def _synthesize(user_query: str | None, tool_results: list[dict]) -> str:
        result = tool_results[-1]
        name = result.get("_tool")

        if "error" in result:
            return (
                "Non sono riuscito a recuperare questo dato: "
                f"{result['error']}. Puoi riformulare la domanda?"
            )

        if name == "list_recurring_series":
            series = result.get("series", [])
            if not series:
                return "Non ho trovato pagamenti ricorrenti nello storico disponibile."
            lines = [
                f"- {s['display_name']}: {abs(s['amount_median']):.2f} EUR "
                f"ogni ~{s['interval_days_median']:.0f} giorni "
                f"(confidenza {s['confidence']:.0%}, categoria {s['category']})"
                for s in series
            ]
            total_monthly = sum(s["monthly_equivalent"] for s in series if s["amount_median"] < 0)
            return (
                f"Ho individuato {len(series)} pagamenti ricorrenti:\n"
                + "\n".join(lines)
                + f"\n\nSpesa ricorrente equivalente mensile: {total_monthly:.2f} EUR."
            )

        if name == "sum_spending_by_category":
            total = result.get("total", 0.0)
            category = result.get("category") or "tutte le categorie"
            count = result.get("count", 0)
            return (
                f"Nel periodo richiesto hai speso {abs(total):.2f} EUR in {category} "
                f"({count} transazioni)."
            )

        if name == "list_transactions":
            items = result.get("transactions", [])
            lines = [f"- {t['booking_date']}: {t['counterparty_raw']} ({t['amount']:.2f} EUR)" for t in items]
            return "Ultime transazioni:\n" + "\n".join(lines)

        if name == "list_price_increases":
            series = result.get("series", [])
            if not series:
                return (
                    "Nessun pagamento ricorrente ha subito un aumento di prezzo "
                    "rispetto al primo addebito."
                )
            lines = [
                f"- {s['display_name']}: da {abs(s['first_amount']):.2f} EUR a "
                f"{abs(s['last_amount']):.2f} EUR ({s['price_change_pct']:+.1%})"
                for s in series
            ]
            header = f"Ho trovato {len(series)} pagamenti ricorrenti con il prezzo aumentato:"
            return header + "\n" + "\n".join(lines)

        if name == "list_subscription_overlaps":
            overlaps = result.get("overlaps", [])
            if not overlaps:
                return "Non ho trovato categorie con più abbonamenti attivi sovrapposti."
            lines = [
                f"- {o['category']}: {', '.join(o['merchants'])} "
                f"(insieme {o['total_monthly_cost']:.2f} EUR/mese)"
                for o in overlaps
            ]
            return (
                f"Hai {len(overlaps)} categorie con più abbonamenti attivi, "
                "possibile spesa ridondante:\n" + "\n".join(lines)
            )

        return "Ho eseguito lo strumento richiesto ma non ho un formato di risposta per questo caso."
