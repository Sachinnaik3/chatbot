"""Domain review agents (risk, infosec, privacy).

Each pre-screens the package from its own angle and proposes candidate findings.
A finding survives only if it cites a retrieved, accessible source or quotes the spec exactly.
Every finding starts as 'candidate'; a human reviewer confirms or dismisses it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, Field

from pia.agents.base import Agent
from pia.cost import CostTracker
from pia.guardrails.output import is_grounded_quote, resolve_citations
from pia.llm.client import LLMClient
from pia.observability import MetricsRegistry
from pia.prompts.registry import wrap_untrusted
from pia.rag.context import build_sources_block, source_ref
from pia.retrieval.index import HybridIndex
from pia.schemas import Principal, SourceRef

Severity = Literal["low", "medium", "high", "critical"]
Domain = Literal["risk", "infosec", "privacy"]

DOMAIN_QUERY = {
    "risk": "operational risk reconciliation fraud outage rollback vendor dependency",
    "infosec": "encryption access control authentication key management logging secrets",
    "privacy": "personal data retention consent purpose minimization cross-border transfer",
}
TRACK_TO_DOMAIN: dict[str, Domain] = {
    "risk_review": "risk",
    "infosec_review": "infosec",
    "privacy_review": "privacy",
}


class CandidateOut(BaseModel):
    title: str = Field(max_length=200)
    severity: Severity
    description: str = Field(default="", max_length=1000)
    cited_source_ids: list[str] = Field(default_factory=list)
    spec_evidence: str | None = Field(default=None, max_length=1000)


class ReviewOut(BaseModel):
    findings: list[CandidateOut] = Field(default_factory=list, max_length=50)


class Finding(BaseModel):
    finding_id: str
    domain: str
    title: str
    severity: Severity
    description: str
    status: Literal["candidate", "confirmed", "dismissed"] = "candidate"
    sources: list[SourceRef] = Field(default_factory=list)
    spec_evidence: str | None = None


@dataclass(frozen=True)
class DomainReviewResult:
    findings: list[Finding]
    dropped_unsupported: int


class DomainReviewAgent(Agent):
    max_tokens = 2048

    def __init__(
        self,
        domain: Domain,
        llm: LLMClient,
        cost: CostTracker | None = None,
        metrics: MetricsRegistry | None = None,
    ) -> None:
        super().__init__(llm, cost, metrics)
        self.domain = domain
        self.prompt_name = f"{domain}_review"

    def review(
        self, *, review_id: str, spec_text: str, index: HybridIndex, principal: Principal, k: int = 5
    ) -> DomainReviewResult:
        query = f"{DOMAIN_QUERY[self.domain]} {spec_text[:400]}"
        hits = index.search(query, principal.teams, k=k)
        chunks = {h.chunk.chunk_id: h.chunk for h in hits}
        out, _, _ = self._invoke(
            f"review:{review_id}",
            ReviewOut,
            spec=wrap_untrusted("spec_facts", spec_text),
            sources=wrap_untrusted("sources", build_sources_block(chunks.values())),
        )
        findings: list[Finding] = []
        dropped = 0
        for i, cand in enumerate(out.findings):
            valid, _ = resolve_citations(cand.cited_source_ids, set(chunks))
            evidence_ok = is_grounded_quote(cand.spec_evidence, spec_text)
            if not valid and not evidence_ok:
                dropped += 1
                continue
            findings.append(
                Finding(
                    finding_id=f"{review_id}:{self.domain}:{i}",
                    domain=self.domain,
                    title=cand.title,
                    severity=cand.severity,
                    description=cand.description,
                    sources=[source_ref(chunks[c]) for c in valid],
                    spec_evidence=cand.spec_evidence if evidence_ok else None,
                )
            )
        return DomainReviewResult(findings=findings, dropped_unsupported=dropped)
