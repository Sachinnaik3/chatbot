"""Drafting agent: drafts questionnaire answers from spec facts and retrieved precedent.

Per-question citation scope: a draft may cite only sources retrieved for that question,
and only accessible ones. Anything else is downgraded to needs_input.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from pia.agents.base import Agent
from pia.guardrails.input import redact_pii
from pia.guardrails.output import enforce_supported, resolve_citations
from pia.prompts.registry import wrap_untrusted
from pia.rag.context import build_sources_block, source_ref
from pia.retrieval.index import HybridIndex
from pia.schemas import DraftAnswer, Principal, Question


class DraftItem(BaseModel):
    question_id: str
    answer: str | None = None
    status: Literal["drafted", "needs_input"]
    cited_source_ids: list[str] = Field(default_factory=list)


class DraftBatch(BaseModel):
    answers: list[DraftItem]


class DraftingAgent(Agent):
    prompt_name = "drafting"

    def draft(
        self,
        *,
        review_id: str,
        questions: list[Question],
        spec_facts: str,
        index: HybridIndex,
        principal: Principal,
    ) -> list[DraftAnswer]:
        hits_by_q = {q.id: index.search(q.text, principal.teams, k=4) for q in questions}
        chunks = {h.chunk.chunk_id: h.chunk for hits in hits_by_q.values() for h in hits}
        questions_block = "\n".join(f"- id={q.id}: {q.text}" for q in questions)

        out, resp, pv = self._invoke(
            f"review:{review_id}",
            DraftBatch,
            questions=wrap_untrusted("questions", questions_block),
            sources=wrap_untrusted("sources", build_sources_block(chunks.values())),
            spec_facts=wrap_untrusted("spec_facts", spec_facts),
        )
        by_id = {a.question_id: a for a in out.answers}

        results: list[DraftAnswer] = []
        for q in questions:
            item = by_id.get(q.id)
            if item is None:
                results.append(
                    DraftAnswer(
                        question_id=q.id,
                        answer=None,
                        status="needs_input",
                        model=resp.model,
                        prompt_version=pv,
                    )
                )
                continue
            allowed = {h.chunk.chunk_id for h in hits_by_q[q.id]}
            valid, _ = resolve_citations(item.cited_source_ids, allowed)
            status = enforce_supported(item.status, item.answer, valid)
            if status != "drafted":
                results.append(
                    DraftAnswer(
                        question_id=q.id,
                        answer=None,
                        status="needs_input",
                        model=resp.model,
                        prompt_version=pv,
                    )
                )
                continue
            results.append(
                DraftAnswer(
                    question_id=q.id,
                    answer=redact_pii(item.answer or "")[0],
                    status="drafted",
                    sources=[source_ref(chunks[c]) for c in valid],
                    model=resp.model,
                    prompt_version=pv,
                )
            )
        return results
