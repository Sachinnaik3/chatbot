"""Base agent contract.

Every agent has a versioned prompt, a typed output, a token budget check, cost recording,
and latency and outcome metrics. Agents never write to the workflow, the audit log, or
review status. They return proposals; services and humans decide what happens next.
"""

from __future__ import annotations

import time
from typing import Any

from pydantic import BaseModel

from pia.cost import CostTracker
from pia.llm.client import LLMClient, LLMResponse
from pia.llm.structured import call_json
from pia.observability import MetricsRegistry
from pia.prompts.registry import load_prompt


class Agent:
    prompt_name: str = ""
    prompt_version: int = 1
    max_tokens: int = 1024

    def __init__(self, llm: LLMClient, cost: CostTracker | None = None, metrics: MetricsRegistry | None = None) -> None:
        self.llm = llm
        self.cost = cost
        self.metrics = metrics

    def _invoke(
        self,
        scope: str,
        model_cls: type[BaseModel],
        *,
        prompt_ref: tuple[str, int] | None = None,
        **variables: Any,
    ) -> tuple[Any, LLMResponse, int]:
        name, version = prompt_ref or (self.prompt_name, self.prompt_version)
        prompt = load_prompt(name, version)
        user = prompt.render(**variables)
        if self.cost:
            self.cost.ensure_budget(scope)
        labels = {"agent": name}

        def record(resp: LLMResponse) -> None:
            if self.cost:
                self.cost.record(scope, resp.model, resp.tokens_in, resp.tokens_out)
            if self.metrics:
                self.metrics.inc("agent_tokens_total", {**labels, "direction": "in"}, resp.tokens_in)
                self.metrics.inc("agent_tokens_total", {**labels, "direction": "out"}, resp.tokens_out)

        start = time.perf_counter()
        outcome = "ok"
        try:
            out, resp = call_json(
                self.llm, prompt.system, user, model_cls, max_tokens=self.max_tokens, on_response=record
            )
            return out, resp, prompt.version
        except Exception:
            outcome = "error"
            raise
        finally:
            if self.metrics:
                self.metrics.observe("agent_latency_seconds", time.perf_counter() - start, labels)
                self.metrics.inc("agent_calls_total", {**labels, "outcome": outcome})
