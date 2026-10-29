"""Findings agent: structures reviewer notes into findings and proposes remediation from
resolved precedent. Also verifies whether a revised spec addresses a finding.

Remediation is kept only when it cites a retrieved source. Verification can say 'addressed'
only with an exact quote from the revised spec. The agent never closes a finding.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from pia.agents.base import Agent
from pia.agents.domain_review import Severity
from pia.guardrails.output import is_grounded_quote, resolve_citations
from pia.prompts.registry import wrap_untrusted
from pia.rag.context import build_sources_block, source_ref
from pia.retrieval.index import HybridIndex
from pia.schemas import Principal, SourceRef

OwnerRole = Literal["project_team", "architect", "risk", "infosec", "privacy", "business_owner"]


class StructuredOut(BaseModel):
    title: str = Field(max_length=200)
    severity: Severity
    owner_role: OwnerRole
    description: str = Field(default="", max_length=1000)
    remediation: str | None = Field(default=None, max_length=1000)
    remediation_source_ids: list[str] = Field(default_factory=list)


class FindingsOut(BaseModel):
    findings: list[StructuredOut] = Field(default_factory=list, max_length=50)


class StructuredFinding(BaseModel):
    finding_id: str
    title: str
    severity: Severity
    owner_role: OwnerRole
    description: str
    remediation: str | None = None
    remediation_sources: list[SourceRef] = Field(default_factory=list)
    status: Literal["open", "resolved"] = "open"


class VerificationOut(BaseModel):
    addressed: bool
    evidence: str | None = Field(default=None, max_length=1000)
    explanation: str = Field(default="", max_length=1000)


class FixVerification(BaseModel):
    finding_id: str
    verdict: Literal["appears_addressed", "not_verified"]
    evidence: str | None = None
    explanation: str = ""


class FindingsAgent(Agent):
    prompt_name = "findings"
    max_tokens = 2048

    def structure(
        self, *, review_id: str, notes: str, index: HybridIndex, principal: Principal
    ) -> list[StructuredFinding]:
        hits = index.search(f"resolved finding remediation {notes[:500]}", principal.teams, k=5)
        chunks = {h.chunk.chunk_id: h.chunk for h in hits}
        out, _, _ = self._invoke(
            f"review:{review_id}",
            FindingsOut,
            notes=wrap_untrusted("notes", notes),
            sources=wrap_untrusted("sources", build_sources_block(chunks.values())),
        )
        results: list[StructuredFinding] = []
        for i, item in enumerate(out.findings):
            valid, _ = resolve_citations(item.remediation_source_ids, set(chunks))
            supported = bool(valid and item.remediation and item.remediation.strip())
            results.append(
                StructuredFinding(
                    finding_id=f"{review_id}:note:{i}",
                    title=item.title,
                    severity=item.severity,
                    owner_role=item.owner_role,
                    description=item.description,
                    remediation=item.remediation if supported else None,
                    remediation_sources=[source_ref(chunks[c]) for c in valid] if supported else [],
                )
            )
        return results

    def verify_fix(self, *, review_id: str, finding_id: str, finding_text: str, revised_spec: str) -> FixVerification:
        out, _, _ = self._invoke(
            f"review:{review_id}",
            VerificationOut,
            prompt_ref=("fix_verification", 1),
            finding=wrap_untrusted("finding", finding_text),
            spec=wrap_untrusted("spec", revised_spec),
        )
        grounded = out.addressed and is_grounded_quote(out.evidence, revised_spec)
        return FixVerification(
            finding_id=finding_id,
            verdict="appears_addressed" if grounded else "not_verified",
            evidence=out.evidence if grounded else None,
            explanation=out.explanation,
        )
