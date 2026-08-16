"""FastAPI service tests. Uses the module-level app instance (default FakeLLM,
no OPENAI_API_KEY set in CI/test environments) so these run offline like the
rest of the suite."""

from fastapi.testclient import TestClient

from txnagent.api.main import app

client = TestClient(app)


class TestHealthz:
    def test_reports_ok_with_transaction_count(self):
        response = client.get("/healthz")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        assert body["transactions_loaded"] > 0


class TestChatEndpoint:
    def test_recurring_query_returns_answer_and_trace(self):
        response = client.post("/chat", json={"query": "Quali abbonamenti ho attivi?"})
        assert response.status_code == 200
        body = response.json()
        assert "Netflix" in body["answer"] or "netflix" in body["answer"].lower()
        assert any(step["kind"] == "tool_call" for step in body["trace"])

    def test_every_trace_step_has_a_timestamp(self):
        response = client.post("/chat", json={"query": "Mostrami le mie ultime transazioni"})
        body = response.json()
        assert all(step["timestamp"] for step in body["trace"])

    def test_missing_query_field_is_a_validation_error_not_a_crash(self):
        response = client.post("/chat", json={})
        assert response.status_code == 422

    def test_response_includes_a_session_id(self):
        response = client.post("/chat", json={"query": "Mostrami le mie ultime transazioni"})
        assert response.json()["session_id"]

    def test_omitting_session_id_starts_a_new_session_each_time(self):
        first = client.post("/chat", json={"query": "Quali abbonamenti ho attivi?"}).json()
        second = client.post("/chat", json={"query": "Quali abbonamenti ho attivi?"}).json()
        assert first["session_id"] != second["session_id"]

    def test_reusing_session_id_continues_the_same_conversation(self):
        first = client.post("/chat", json={"query": "Quali abbonamenti ho attivi?"}).json()
        sid = first["session_id"]
        second = client.post("/chat", json={"query": "E i doppioni?", "session_id": sid}).json()
        assert second["session_id"] == sid
        assert second["answer"]


class TestRecurringEndpoint:
    def test_returns_detected_series(self):
        response = client.get("/recurring")
        assert response.status_code == 200
        body = response.json()
        assert body["count"] == len(body["series"])
        assert body["count"] > 0

    def test_min_confidence_filter_narrows_results(self):
        loose = client.get("/recurring", params={"min_confidence": 0.0}).json()
        strict = client.get("/recurring", params={"min_confidence": 0.95}).json()
        assert strict["count"] <= loose["count"]

    def test_series_include_status_and_price_increased_fields(self):
        body = client.get("/recurring").json()
        assert all("status" in s and "price_increased" in s for s in body["series"])


class TestPriceIncreasesEndpoint:
    def test_returns_structured_series(self):
        response = client.get("/price-increases")
        assert response.status_code == 200
        body = response.json()
        assert body["count"] == len(body["series"])
        for s in body["series"]:
            assert s["price_change_pct"] is None or s["price_change_pct"] > 0


class TestSubscriptionOverlapsEndpoint:
    def test_returns_streaming_overlap(self):
        response = client.get("/subscription-overlaps")
        assert response.status_code == 200
        body = response.json()
        assert body["count"] == len(body["overlaps"])
        assert body["count"] > 0
        assert all(len(o["merchants"]) >= 2 for o in body["overlaps"])


class TestConsole:
    def test_serves_the_chat_console_html(self):
        response = client.get("/")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]
        assert "Transaction Intelligence Agent" in response.text

    def test_serves_static_assets(self):
        response = client.get("/static/app.js")
        assert response.status_code == 200
