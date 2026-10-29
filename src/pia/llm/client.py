"""Provider-agnostic LLM client. Agents depend on the LLMClient protocol, not on a vendor SDK."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from pia.llm.fake import grounded_responder
from pia.settings import Settings


@dataclass(frozen=True)
class LLMResponse:
    text: str
    model: str
    tokens_in: int
    tokens_out: int


class LLMClient(Protocol):
    model: str

    def complete(self, system: str, user: str, *, max_tokens: int = 1024, temperature: float = 0.0) -> LLMResponse: ...


def _approx_tokens(text: str) -> int:
    return max(1, len(text) // 4)


class FakeLLM:
    """For dev, tests, and offline evals only. Refused outside dev by build_llm."""

    model = "fake-1"

    def __init__(self, responder: Callable[[str, str], str] | None = None) -> None:
        self._responder = responder or grounded_responder

    def complete(self, system, user, *, max_tokens=1024, temperature=0.0):
        text = self._responder(system, user)
        return LLMResponse(text, self.model, _approx_tokens(system + user), _approx_tokens(text))


class AnthropicLLM:
    def __init__(self, model: str, api_key: str, timeout_s: float, max_retries: int) -> None:
        import anthropic

        self.model = model
        self._client = anthropic.Anthropic(api_key=api_key, timeout=timeout_s, max_retries=max_retries)

    def complete(self, system, user, *, max_tokens=1024, temperature=0.0):
        msg = self._client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            temperature=temperature,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        text = "".join(block.text for block in msg.content if block.type == "text")
        return LLMResponse(text, self.model, msg.usage.input_tokens, msg.usage.output_tokens)


def build_llm(settings: Settings) -> LLMClient:
    if settings.llm_provider == "fake":
        if settings.env != "dev":
            raise RuntimeError("the fake LLM is only allowed in dev")
        return FakeLLM()
    if settings.llm_provider == "anthropic":
        if not settings.anthropic_api_key:
            raise RuntimeError("PIA_ANTHROPIC_API_KEY is required for the anthropic provider")
        return AnthropicLLM(
            settings.llm_model,
            settings.anthropic_api_key,
            settings.llm_timeout_s,
            settings.llm_max_retries,
        )
    raise ValueError(f"unknown llm_provider: {settings.llm_provider}")
