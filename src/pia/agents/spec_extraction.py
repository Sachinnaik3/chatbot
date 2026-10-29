"""Spec extraction agent: pulls design facts from a spec. Each fact must quote the spec exactly.

Facts whose evidence is not found in the spec are dropped and counted. The architect confirms
the remaining facts at the extraction gate.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, Field

from pia.agents.base import Agent
from pia.guardrails.output import is_grounded_quote, normalize_text
from pia.prompts.registry import wrap_untrusted

FactCategory = Literal["component", "data_store", "data_flow", "integration", "vendor", "control"]


class Fact(BaseModel):
    category: FactCategory
    name: str = Field(max_length=120)
    detail: str = Field(default="", max_length=500)
    evidence: str = Field(max_length=1000)


class FactsOut(BaseModel):
    facts: list[Fact] = Field(default_factory=list, max_length=200)


@dataclass(frozen=True)
class ExtractionResult:
    facts: list[Fact]
    dropped_ungrounded: int


class SpecExtractionAgent(Agent):
    prompt_name = "spec_extraction"
    max_tokens = 4096

    def run(self, *, review_id: str, spec_text: str) -> ExtractionResult:
        out, _, _ = self._invoke(f"review:{review_id}", FactsOut, spec=wrap_untrusted("spec", spec_text))
        kept: list[Fact] = []
        seen: set[tuple[str, str]] = set()
        dropped = 0
        for fact in out.facts:
            if not is_grounded_quote(fact.evidence, spec_text):
                dropped += 1
                continue
            key = (fact.category, normalize_text(fact.name))
            if key not in seen:
                seen.add(key)
                kept.append(fact)
        return ExtractionResult(facts=kept, dropped_ungrounded=dropped)


def facts_as_text(facts: list[dict] | list[Fact]) -> str:
    rows = [f if isinstance(f, dict) else f.model_dump() for f in facts]
    return "\n".join(f"{r['category']}: {r['name']}. {r['evidence']}" for r in rows)
