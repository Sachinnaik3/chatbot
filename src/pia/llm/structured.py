"""Structured output: parse, validate, and retry once with the error message.

Invalid output never leaves this function. Callers get a validated model or an exception.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable

from pydantic import BaseModel, ValidationError

from pia.llm.client import LLMClient, LLMResponse

_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


class StructuredOutputError(Exception):
    pass


def parse_model(text: str, model_cls: type[BaseModel]) -> BaseModel:
    cleaned = _FENCE.sub("", text).strip()
    return model_cls.model_validate(json.loads(cleaned))


def call_json(
    llm: LLMClient,
    system: str,
    user: str,
    model_cls: type[BaseModel],
    *,
    max_attempts: int = 2,
    max_tokens: int = 1024,
    on_response: Callable[[LLMResponse], None] | None = None,
) -> tuple[BaseModel, LLMResponse]:
    prompt = user
    last_error: Exception | None = None
    for _ in range(max_attempts):
        resp = llm.complete(system, prompt, max_tokens=max_tokens)
        if on_response:
            on_response(resp)
        try:
            return parse_model(resp.text, model_cls), resp
        except (json.JSONDecodeError, ValidationError) as exc:
            last_error = exc
            prompt = (
                f"{user}\n\nYour previous output was invalid ({type(exc).__name__}). "
                "Return only JSON that matches the schema."
            )
    raise StructuredOutputError(f"no valid output after {max_attempts} attempts") from last_error
