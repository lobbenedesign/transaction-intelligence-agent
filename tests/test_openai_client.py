"""OpenAIClient tests, with the `openai` SDK faked via sys.modules rather than
requiring the real package to be installed — this is the optional dependency
declared under `[project.optional-dependencies].openai` in pyproject.toml, and
CI installs only `.[dev]`. Faking the module boundary lets the parsing logic
(tool_calls -> ToolCall, content -> LLMResponse) be verified without pulling in
the real SDK or making a network call."""

from __future__ import annotations

import json
import sys
import types
from types import SimpleNamespace

import pytest


def _install_fake_openai_module(monkeypatch: pytest.MonkeyPatch, create_response):
    """Injects a minimal fake `openai` module exposing an `OpenAI` class whose
    `.chat.completions.create(...)` returns whatever `create_response` builds."""

    class _FakeCompletions:
        def create(self, **kwargs):
            return create_response(kwargs)

    class _FakeChat:
        def __init__(self) -> None:
            self.completions = _FakeCompletions()

    class _FakeOpenAI:
        def __init__(self, api_key: str | None = None, base_url: str | None = None) -> None:
            self.api_key = api_key
            self.base_url = base_url
            self.chat = _FakeChat()

    fake_module = types.ModuleType("openai")
    fake_module.OpenAI = _FakeOpenAI
    monkeypatch.setitem(sys.modules, "openai", fake_module)


class TestOpenAIClientErrorHandling:
    def test_raises_clear_error_when_package_is_not_installed(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setitem(sys.modules, "openai", None)  # forces ImportError on `import openai`
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        # re-import must happen inside the client, not at module load time
        from txnagent.llm.openai_client import OpenAIClient

        with pytest.raises(RuntimeError, match="pip install openai"):
            OpenAIClient()

    def test_raises_clear_error_when_api_key_is_missing(self, monkeypatch: pytest.MonkeyPatch):
        _install_fake_openai_module(monkeypatch, create_response=lambda kwargs: None)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        from txnagent.llm.openai_client import OpenAIClient

        with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
            OpenAIClient()


class TestOpenAIClientResponseParsing:
    def test_parses_tool_calls_from_response(self, monkeypatch: pytest.MonkeyPatch):
        def fake_response(kwargs):
            tool_call = SimpleNamespace(
                function=SimpleNamespace(
                    name="list_recurring_series",
                    arguments=json.dumps({"min_confidence": 0.6}),
                )
            )
            message = SimpleNamespace(tool_calls=[tool_call], content=None)
            return SimpleNamespace(choices=[SimpleNamespace(message=message)])

        _install_fake_openai_module(monkeypatch, fake_response)
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        from txnagent.llm.openai_client import OpenAIClient

        client = OpenAIClient()
        response = client.complete("system", [{"role": "user", "content": "hi"}], tools=[])

        assert response.wants_tool_call
        assert response.tool_calls[0].name == "list_recurring_series"
        assert response.tool_calls[0].arguments == {"min_confidence": 0.6}

    def test_parses_plain_text_content_when_no_tool_call(self, monkeypatch: pytest.MonkeyPatch):
        def fake_response(kwargs):
            message = SimpleNamespace(tool_calls=None, content="Ecco la risposta.")
            return SimpleNamespace(choices=[SimpleNamespace(message=message)])

        _install_fake_openai_module(monkeypatch, fake_response)
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        from txnagent.llm.openai_client import OpenAIClient

        client = OpenAIClient()
        response = client.complete("system", [{"role": "user", "content": "hi"}], tools=[])

        assert not response.wants_tool_call
        assert response.content == "Ecco la risposta."

    def test_forwards_tool_choice_auto_only_when_tools_are_present(self, monkeypatch: pytest.MonkeyPatch):
        captured: dict = {}

        def fake_response(kwargs):
            captured.update(kwargs)
            message = SimpleNamespace(tool_calls=None, content="ok")
            return SimpleNamespace(choices=[SimpleNamespace(message=message)])

        _install_fake_openai_module(monkeypatch, fake_response)
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        from txnagent.llm.openai_client import OpenAIClient

        client = OpenAIClient()
        client.complete("system", [], tools=[])
        assert captured["tool_choice"] is None

        client.complete("system", [], tools=[{"type": "function", "function": {"name": "x"}}])
        assert captured["tool_choice"] == "auto"
