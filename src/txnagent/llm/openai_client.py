"""OpenAI-compatible client (optional).

Requires `pip install openai` and an `OPENAI_API_KEY` — neither is a hard
dependency of this package, so `import txnagent` never fails in an offline
environment. Also works against any OpenAI-compatible endpoint (self-hosted
vLLM, Azure OpenAI, ...) via `base_url`, which is the point made in
docs/adr/0001: vendor/hosting is a runtime choice, not a code dependency.
"""

from __future__ import annotations

import json
import os
from typing import Any

from txnagent.llm.base import LLMResponse, ToolCall


class OpenAIClient:
    def __init__(self, model: str = "gpt-4o-mini", base_url: str | None = None) -> None:
        try:
            from openai import OpenAI
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError(
                "OpenAIClient requires the 'openai' package: pip install openai"
            ) from exc

        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY is not set")

        self._client = OpenAI(api_key=api_key, base_url=base_url)
        self._model = model

    def complete(
        self,
        system_prompt: str,
        messages: list[dict[str, str]],
        tools: list[dict[str, Any]],
    ) -> LLMResponse:
        full_messages = [{"role": "system", "content": system_prompt}, *messages]
        response = self._client.chat.completions.create(
            model=self._model,
            messages=full_messages,
            tools=tools or None,
            tool_choice="auto" if tools else None,
        )
        choice = response.choices[0].message

        if choice.tool_calls:
            calls = [
                ToolCall(name=tc.function.name, arguments=json.loads(tc.function.arguments or "{}"))
                for tc in choice.tool_calls
            ]
            return LLMResponse(tool_calls=calls)

        return LLMResponse(content=choice.content or "")
