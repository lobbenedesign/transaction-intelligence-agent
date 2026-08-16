"""ToolRegistry.dispatch must never raise: a tool call's name and arguments come
from the LLM's own (fallible) choice, not from trusted application code. These
cases are exactly what a real model occasionally gets wrong — an invalid enum
value, an unexpected keyword, a typo'd tool name — and they must degrade to a
structured error the model (or FakeLLM's synthesizer) can react to."""

from txnagent.agent.tools import ToolRegistry
from txnagent.data.store import TransactionStore
from txnagent.data.synthetic import generate_synthetic_history
from txnagent.llm.fake import FakeLLM


def _registry() -> ToolRegistry:
    dataset = generate_synthetic_history(seed=42, months=6)
    return ToolRegistry(store=TransactionStore(dataset.transactions))


class TestToolDispatchRobustness:
    def test_unknown_tool_name_returns_structured_error(self):
        result = _registry().dispatch("delete_all_transactions", {})
        assert result["error"]

    def test_invalid_category_enum_value_does_not_raise(self):
        result = _registry().dispatch("sum_spending_by_category", {"category": "not_a_real_category"})
        assert "error" in result
        assert "not_a_real_category" in result["error"] or "invalid" in result["error"].lower()

    def test_unexpected_keyword_argument_does_not_raise(self):
        result = _registry().dispatch("list_recurring_series", {"unexpected_arg": 1})
        assert "error" in result

    def test_valid_call_still_returns_normal_payload(self):
        result = _registry().dispatch("list_recurring_series", {})
        assert "error" not in result
        assert "series" in result


class TestNewSignalTools:
    def test_list_price_increases_returns_structured_payload(self):
        result = _registry().dispatch("list_price_increases", {})
        assert "error" not in result
        assert "series" in result
        for s in result["series"]:
            assert set(s) == {"display_name", "first_amount", "last_amount", "price_change_pct", "category"}

    def test_list_subscription_overlaps_returns_structured_payload(self):
        result = _registry().dispatch("list_subscription_overlaps", {})
        assert "error" not in result
        assert "overlaps" in result
        for o in result["overlaps"]:
            assert set(o) == {"category", "merchants", "total_monthly_cost"}
            assert len(o["merchants"]) >= 2

    def test_list_recurring_series_payload_includes_status_and_price_increased(self):
        result = _registry().dispatch("list_recurring_series", {})
        assert all("status" in s and "price_increased" in s for s in result["series"])


class TestFakeLLMSynthesizesToolErrorsHonestly:
    def test_tool_error_produces_an_honest_answer_not_a_crash(self):
        error_result = {"_tool": "sum_spending_by_category", "error": "invalid arguments: bad category"}
        answer = FakeLLM._synthesize("quanto ho speso in xyz?", [error_result])
        assert "non sono riuscito" in answer.lower()
