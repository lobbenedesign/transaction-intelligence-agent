"""FastAPI service exposing the agent over HTTP.

`GET /` — chat console (static HTML/JS, no build step).
`GET /healthz` — liveness.
`POST /chat` — natural-language query, returns the answer, the tool-call
  trace (the audit-trail payload a real deployment would persist
  append-only, per docs/adr/0003), and a `session_id` — pass it back on the
  next call to continue the conversation with context (docs/adr/0006).
`GET /recurring` — the raw detected recurring series, for a UI or for
  debugging without going through the LLM layer at all.
`GET /price-increases` — recurring series whose amount grew since their
  first occurrence.
`GET /subscription-overlaps` — categories with 2+ distinct active recurring
  subscriptions (redundant-spend signal).
"""

from __future__ import annotations

import logging
import os
import uuid
from dataclasses import asdict
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from txnagent.agent.core import TransactionAgent
from txnagent.agent.tools import ToolRegistry
from txnagent.data.store import TransactionStore
from txnagent.data.synthetic import generate_synthetic_history
from txnagent.llm.base import LLMClient
from txnagent.llm.fake import FakeLLM

#: Messages kept per session, oldest dropped first. Bounds the in-memory
#: session store the same way TransactionStore is deliberately in-memory and
#: not persisted (docs/adr/0003) — a real deployment would move this to a
#: TTL-backed store (Redis, a session table), not grow it unbounded in a
#: process dict.
MAX_SESSION_MESSAGES = 20

logger = logging.getLogger("txnagent")

app = FastAPI(title="Transaction Intelligence Agent", version="0.1.0")

_STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
def console() -> FileResponse:
    return FileResponse(_STATIC_DIR / "index.html")


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Defense in depth: tool-level errors are already caught and turned into a
    structured result the model reacts to (see ToolRegistry.dispatch), so this
    only fires on something genuinely unexpected. On data this sensitive, a raw
    traceback in the response body is not acceptable — log server-side, return
    a generic message client-side."""
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"error": "internal_error"})


_dataset = generate_synthetic_history()
_store = TransactionStore(_dataset.transactions)
_tools = ToolRegistry(store=_store)


def _build_llm() -> LLMClient:
    if os.environ.get("OPENAI_API_KEY"):
        from txnagent.llm.openai_client import OpenAIClient

        return OpenAIClient()
    return FakeLLM()


_agent = TransactionAgent(llm=_build_llm(), tools=_tools)

#: session_id -> AgentRun.messages transcript. In-memory and process-local —
#: same trade-off as TransactionStore (docs/adr/0003): fine for a single-
#: instance demo, not for a horizontally-scaled deployment, where this would
#: move to a shared store keyed the same way.
_sessions: dict[str, list[dict[str, str]]] = {}


class ChatRequest(BaseModel):
    query: str
    session_id: str | None = None


class ChatResponse(BaseModel):
    answer: str
    trace: list[dict]
    session_id: str


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok", "transactions_loaded": len(_store.transactions)}


@app.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest) -> ChatResponse:
    """With no `session_id`, starts a fresh conversation and returns a new
    one. Pass it back on the next call to continue with context — e.g. "e il
    mese scorso?" after "quanto ho speso in ristoranti?" only resolves
    correctly when the model sees the prior turn (docs/adr/0006). `FakeLLM`
    only reads the latest message (docs/adr/0001), so this mainly pays off
    once `OPENAI_API_KEY` is set — but the session plumbing is exercised and
    tested regardless of which LLM client is behind it."""
    session_id = request.session_id or str(uuid.uuid4())
    history = _sessions.get(session_id, [])
    run = _agent.ask(request.query, history=history)
    _sessions[session_id] = run.messages[-MAX_SESSION_MESSAGES:]
    return ChatResponse(answer=run.answer, trace=[asdict(t) for t in run.trace], session_id=session_id)


@app.get("/recurring")
def recurring(min_confidence: float = 0.55) -> dict:
    series = _store.recurring_series(min_confidence=min_confidence)
    return {
        "count": len(series),
        "series": [
            {
                "display_name": s.display_name,
                "amount_median": s.amount_median,
                "interval_days_median": s.interval_days_median,
                "confidence": s.confidence,
                "category": s.category.value,
                "monthly_equivalent": round(s.monthly_equivalent, 2),
                "status": s.status.value,
                "price_increased": s.price_increased,
            }
            for s in series
        ],
    }


@app.get("/price-increases")
def price_increases(min_confidence: float = 0.55) -> dict:
    series = _store.price_increases(min_confidence=min_confidence)
    return {
        "count": len(series),
        "series": [
            {
                "display_name": s.display_name,
                "first_amount": s.first_amount,
                "last_amount": s.last_amount,
                "price_change_pct": round(s.price_change_pct, 4) if s.price_change_pct is not None else None,
                "category": s.category.value,
            }
            for s in series
        ],
    }


@app.get("/subscription-overlaps")
def subscription_overlaps(min_confidence: float = 0.55) -> dict:
    overlaps = _store.overlapping_subscriptions(min_confidence=min_confidence)
    return {
        "count": len(overlaps),
        "overlaps": [
            {
                "category": o.category.value,
                "merchants": [s.display_name for s in o.series],
                "total_monthly_cost": round(o.total_monthly_cost, 2),
            }
            for o in overlaps
        ],
    }
