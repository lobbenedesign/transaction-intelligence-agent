#!/usr/bin/env python3
"""End-to-end CLI demo — no server, no API key needed.

Generates a year of synthetic transactions, runs recurring-payment
detection, then fires six representative natural-language queries at the
agent (using FakeLLM) and prints the answers plus a short benchmark. The
last two queries exercise the competitor-parity signals added in
docs/adr/0005 (price increases, subscription overlaps) — see the README's
competitor comparison for why those two were picked.

Run with: `python scripts/demo.py` or `make demo`.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from txnagent.agent.core import TransactionAgent
from txnagent.agent.tools import ToolRegistry
from txnagent.data.store import TransactionStore
from txnagent.data.synthetic import generate_synthetic_history
from txnagent.detection.normalize import normalize_merchant
from txnagent.detection.recurring import detect_recurring_series
from txnagent.llm.fake import FakeLLM

DEMO_QUERIES = [
    "Quali abbonamenti ho attivi?",
    "Quanto ho speso in ristoranti e intrattenimento?",
    "Mostrami le mie ultime transazioni",
    "Quando pago di nuovo l'affitto?",
    "È aumentato di prezzo qualche abbonamento?",
    "Ho abbonamenti doppioni o ridondanti?",
]


def main() -> None:
    print("=" * 72)
    print("Transaction Intelligence Agent — demo end-to-end")
    print("=" * 72)

    dataset = generate_synthetic_history(months=12, seed=42)
    print(f"\nGenerate {len(dataset.transactions)} transazioni sintetiche su 12 mesi.")

    t0 = time.perf_counter()
    series = detect_recurring_series(dataset.transactions)
    elapsed_ms = (time.perf_counter() - t0) * 1000

    detected_merchants = {s.merchant_key for s in series}
    ground_truth = {normalize_merchant(m) for m in dataset.ground_truth_recurring_merchants}
    true_positives = detected_merchants & ground_truth
    precision = len(true_positives) / len(detected_merchants) if detected_merchants else 0.0
    recall = len(true_positives) / len(ground_truth) if ground_truth else 0.0

    print(f"\nRilevamento pagamenti ricorrenti: {elapsed_ms:.1f} ms per {len(dataset.transactions)} transazioni")
    print(f"  precision={precision:.2%}  recall={recall:.2%}  (ground truth: {len(ground_truth)} serie note)")
    print(f"  serie rilevate ({len(series)}):")
    for s in series:
        flag = "  ↑ prezzo aumentato" if s.price_increased else ""
        print(
            f"    - {s.display_name:<35} {abs(s.amount_median):>8.2f} EUR "
            f"ogni ~{s.interval_days_median:>5.1f}g  conf={s.confidence:.0%}  "
            f"cat={s.category.value}  status={s.status.value}{flag}"
        )

    store = TransactionStore(dataset.transactions)
    agent = TransactionAgent(llm=FakeLLM(), tools=ToolRegistry(store=store))

    print("\n" + "-" * 72)
    print("Query all'agente (FakeLLM, nessuna chiave API richiesta)")
    print("-" * 72)
    for query in DEMO_QUERIES:
        run = agent.ask(query)
        print(f"\n> {query}")
        print(run.answer)
        tool_names = [t.payload["name"] for t in run.trace if t.kind == "tool_call"]
        print(f"  [audit trail: {len(run.trace)} passi, tool usati: {tool_names}]")

    print("\n" + "=" * 72)
    print("Demo completata. Avvia il servizio con: uvicorn txnagent.api.main:app --reload")
    print("=" * 72)


if __name__ == "__main__":
    main()
