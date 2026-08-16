"""LLM provider abstraction.

See docs/adr/0001-agnostic-llm-provider.md for why the agent core never
imports a specific vendor SDK directly. In short: this is a bank-adjacent
demo project, model vendor and hosting (on-prem vs cloud, EU-hosted vs not)
are exactly the kind of decision a real bank's AI platform team re-litigates
every 6-12 months, and the agent logic should not need to change when it does.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class ToolCall:
    name: str
    arguments: dict[str, Any]


@dataclass
class LLMResponse:
    """Either a direct textual answer, or a list of tool calls the agent
    loop should execute before asking the model again."""

    content: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)

    @property
    def wants_tool_call(self) -> bool:
        return bool(self.tool_calls)


class LLMClient(Protocol):
    """Minimal surface the agent loop needs. Any provider — OpenAI-compatible
    endpoint, a self-hosted vLLM/TGI server, Bedrock, or the deterministic
    FakeLLM used in tests — implements just this."""

    def complete(
        self,
        system_prompt: str,
        messages: list[dict[str, str]],
        tools: list[dict[str, Any]],
    ) -> LLMResponse: ...
