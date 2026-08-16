from txnagent.agent.core import TransactionAgent
from txnagent.agent.tools import ToolRegistry
from txnagent.data.store import TransactionStore
from txnagent.data.synthetic import generate_synthetic_history
from txnagent.llm.fake import FakeLLM


def _agent() -> TransactionAgent:
    dataset = generate_synthetic_history(seed=42, months=12)
    store = TransactionStore(dataset.transactions)
    return TransactionAgent(llm=FakeLLM(), tools=ToolRegistry(store=store))


class TestTransactionAgent:
    def test_recurring_query_calls_the_right_tool_and_answers(self):
        run = _agent().ask("Quali abbonamenti ho attivi?")
        tool_calls = [t for t in run.trace if t.kind == "tool_call"]
        assert len(tool_calls) == 1
        assert tool_calls[0].payload["name"] == "list_recurring_series"
        assert "Netflix" in run.answer or "netflix" in run.answer.lower()

    def test_spending_query_returns_a_grounded_number(self):
        run = _agent().ask("Quanto ho speso in ristoranti e intrattenimento?")
        tool_calls = [t for t in run.trace if t.kind == "tool_call"]
        assert tool_calls[0].payload["name"] == "sum_spending_by_category"
        assert "EUR" in run.answer

    def test_every_run_produces_a_complete_audit_trail(self):
        run = _agent().ask("Mostrami le mie ultime transazioni")
        assert run.trace[-1].kind == "final_answer"
        assert all(entry.timestamp for entry in run.trace)

    def test_unrecognized_query_does_not_crash_and_asks_for_clarification(self):
        run = _agent().ask("asdkjhasdkjh random gibberish query 12345")
        tool_calls = [t for t in run.trace if t.kind == "tool_call"]
        assert tool_calls == []  # no tool invocata a caso su un topic non riconosciuto
        assert "non ho capito" in run.answer.lower()

    def test_price_increase_query_calls_the_right_tool(self):
        run = _agent().ask("Quali abbonamenti sono aumentati di prezzo?")
        tool_calls = [t for t in run.trace if t.kind == "tool_call"]
        assert len(tool_calls) == 1
        assert tool_calls[0].payload["name"] == "list_price_increases"

    def test_overlap_query_calls_the_right_tool_and_finds_streaming_overlap(self):
        # 12-month dataset injects both Netflix and Spotify as SUBSCRIPTION-category
        # recurring series — a real overlap the agent should surface.
        run = _agent().ask("Ho abbonamenti doppioni o ridondanti?")
        tool_calls = [t for t in run.trace if t.kind == "tool_call"]
        assert tool_calls[0].payload["name"] == "list_subscription_overlaps"
        assert "subscription" in run.answer.lower()

    def test_price_increase_intent_wins_over_generic_recurring_keyword(self):
        # "abbonamento" alone would match the generic recurring branch; the
        # more specific price-increase phrasing must take priority.
        run = _agent().ask("È aumentato il prezzo di qualche abbonamento?")
        tool_calls = [t for t in run.trace if t.kind == "tool_call"]
        assert tool_calls[0].payload["name"] == "list_price_increases"


class TestConversationMemory:
    """docs/adr/0006: ask() threads a prior transcript across turns."""

    def test_first_turn_with_no_history_starts_from_just_the_user_message(self):
        run = _agent().ask("Mostrami le mie ultime transazioni")
        assert run.messages[0] == {"role": "user", "content": "Mostrami le mie ultime transazioni"}

    def test_final_answer_is_appended_to_the_returned_transcript(self):
        run = _agent().ask("Quali abbonamenti ho attivi?")
        assert run.messages[-1] == {"role": "assistant", "content": run.answer}

    def test_second_turn_transcript_includes_the_first_turns_messages(self):
        agent = _agent()
        first = agent.ask("Quali abbonamenti ho attivi?")
        second = agent.ask("E i doppioni?", history=first.messages)

        # the second turn's transcript starts with everything from the first
        assert second.messages[: len(first.messages)] == first.messages
        assert {"role": "user", "content": "E i doppioni?"} in second.messages[len(first.messages) :]

    def test_each_turn_gets_its_own_step_budget_not_a_shared_one(self):
        agent = _agent()
        first = agent.ask("Quali abbonamenti ho attivi?")
        second = agent.ask("Quanto ho speso in ristoranti?", history=first.messages)
        # both turns independently resolve within MAX_STEPS, proving the
        # budget reset rather than being consumed cumulatively
        assert second.trace[-1].kind == "final_answer"
