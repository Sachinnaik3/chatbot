"""Grounded Q&A: retrieve, answer only from retrieved sources, cite, and validate."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from pia.agents.base import Agent
from pia.cost import CostTracker
from pia.guardrails.input import redact_pii
from pia.guardrails.output import enforce_supported, resolve_citations
from pia.llm.client import LLMClient
from pia.observability import MetricsRegistry
from pia.prompts.registry import wrap_untrusted
from pia.rag.context import build_sources_block, source_ref
from pia.retrieval.index import HybridIndex
from pia.schemas import InsightAnswer, Principal


class InsightOut(BaseModel):
    answer: str | None = None
    status: Literal["drafted", "needs_input"]
    cited_source_ids: list[str] = Field(default_factory=list)


class GroundedQA(Agent):
    prompt_name = "insight_answer"

    def __init__(
        self,
        index: HybridIndex,
        llm: LLMClient,
        cost: CostTracker | None = None,
        top_k: int = 4,
        metrics: MetricsRegistry | None = None,
    ):
        super().__init__(llm, cost, metrics)
        self._index = index
        self._top_k = top_k

    def ask(self, question: str, principal: Principal, history: list[dict[str, str]] | None = None) -> InsightAnswer:
        hits = self._index.search(question, principal.teams, k=self._top_k)
        if not hits:
            return InsightAnswer(
                answer=None,
                status="needs_input",
                sources=[],
                model=self.llm.model,
                prompt_version=self.prompt_version,
            )

        chunks = {h.chunk.chunk_id: h.chunk for h in hits}
        history_text = "\n".join(f"{t['role']}: {t['content']}" for t in (history or []))
        out, resp, pv = self._invoke(
            f"insight:{principal.user_id}",
            InsightOut,
            question=wrap_untrusted("question", question),
            history=wrap_untrusted("history", history_text) if history_text else "(none)",
            sources=wrap_untrusted("sources", build_sources_block(chunks.values())),
        )
        valid, _ = resolve_citations(out.cited_source_ids, set(chunks))
        status = enforce_supported(out.status, out.answer, valid)
        if status != "drafted":
            return InsightAnswer(answer=None, status="needs_input", sources=[], model=resp.model, prompt_version=pv)
        return InsightAnswer(
            answer=redact_pii(out.answer or "")[0],
            status="drafted",
            sources=[source_ref(chunks[c]) for c in valid],
            model=resp.model,
            prompt_version=pv,
        )
