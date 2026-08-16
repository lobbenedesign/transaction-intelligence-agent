"""The agent loop.

A minimal ReAct-style loop: send the conversation + tool schema to the LLM,
execute whatever tool it asks for, feed the result back, repeat until the
model returns plain text instead of a tool call (or `max_steps` is hit).

Every turn is appended to `AgentRun.trace` — this is not incidental logging,
it is the audit trail an AI Act Article 12 "automatic event logging"
requirement asks for: which tool ran, with what arguments, against what
result, in what order, before the user-facing answer was produced. See
docs/adr/0003.

`ask()` accepts an optional `history` of prior OpenAI-style messages and
returns the updated transcript in `AgentRun.messages`, so a caller (see
`api/main.py`'s session store) can thread multi-turn conversations — a
follow-up like "e il mese scorso?" only resolves correctly if the model
sees what was asked and answered before it. `FakeLLM` itself only reads the
*latest* user message (see docs/adr/0001: it is a keyword router, not a
model, and does not attempt cross-turn disambiguation) — this plumbing is
what makes multi-turn actually work once `OpenAIClient` is in the loop,
which does use the full history, per docs/adr/0006.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime

from txnagent.agent.tools import TOOL_SCHEMAS, ToolRegistry
from txnagent.llm.base import LLMClient

SYSTEM_PROMPT = (
    "Sei un assistente finanziario che risponde a domande sulle transazioni "
    "di un conto corrente. Usa sempre gli strumenti disponibili per recuperare "
    "i dati reali prima di rispondere: non inventare mai importi o date. "
    "Rispondi in italiano, in modo conciso e con i numeri arrotondati a due decimali."
)

MAX_STEPS = 4


@dataclass
class TraceEntry:
    step: int
    kind: str  # "tool_call" | "final_answer"
    payload: dict
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


@dataclass
class AgentRun:
    query: str
    answer: str
    trace: list[TraceEntry]
    messages: list[dict[str, str]] = field(default_factory=list)


class TransactionAgent:
    def __init__(self, llm: LLMClient, tools: ToolRegistry) -> None:
        self._llm = llm
        self._tools = tools

    def ask(self, query: str, history: list[dict[str, str]] | None = None) -> AgentRun:
        """`history` is a prior AgentRun.messages transcript to continue, or
        None to start a fresh conversation. Each call still gets its own
        MAX_STEPS tool-call budget — the limit is per-turn, not cumulative
        across a whole conversation."""
        messages: list[dict[str, str]] = list(history or []) + [{"role": "user", "content": query}]
        trace: list[TraceEntry] = []

        for step in range(1, MAX_STEPS + 1):
            response = self._llm.complete(SYSTEM_PROMPT, messages, TOOL_SCHEMAS)

            if not response.wants_tool_call:
                answer = response.content or ""
                trace.append(TraceEntry(step=step, kind="final_answer", payload={"answer": answer}))
                messages.append({"role": "assistant", "content": answer})
                return AgentRun(query=query, answer=answer, trace=trace, messages=messages)

            for call in response.tool_calls:
                result = self._tools.dispatch(call.name, call.arguments)
                trace.append(
                    TraceEntry(
                        step=step,
                        kind="tool_call",
                        payload={"name": call.name, "arguments": call.arguments, "result": result},
                    )
                )
                messages.append(
                    {"role": "assistant", "content": f"[tool_call:{call.name}]"}
                )
                messages.append({"role": "tool", "content": json.dumps(result)})

        fallback = "Non sono riuscito a completare la richiesta entro il numero massimo di passi consentiti."
        trace.append(TraceEntry(step=MAX_STEPS + 1, kind="final_answer", payload={"answer": fallback}))
        messages.append({"role": "assistant", "content": fallback})
        return AgentRun(query=query, answer=fallback, trace=trace, messages=messages)
