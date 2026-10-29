"""Guard suites. Each feeds a deliberately misbehaving model into an agent and checks that the
guardrail catches it. These always run on the fake LLM because they test code, not the model.
A drop below 1.0 means a guard is broken."""

from __future__ import annotations

import json

from pia.agents.decision_brief import DecisionBriefAgent
from pia.agents.domain_review import DomainReviewAgent
from pia.agents.findings import FindingsAgent
from pia.agents.spec_extraction import SpecExtractionAgent
from pia.llm.client import FakeLLM
from pia.retrieval.index import HybridIndex
from pia.schemas import Principal

SPEC = "Payment preferences are stored in a new database. Data is encrypted at rest with AES-256."
PRINCIPAL = Principal(user_id="eval", teams=frozenset({"project", "risk", "infosec", "privacy"}))


def _fake(payload: dict) -> FakeLLM:
    return FakeLLM(lambda system, user: json.dumps(payload))


def extraction_rejects_invented_quotes() -> bool:
    agent = SpecExtractionAgent(
        _fake(
            {
                "facts": [
                    {"category": "vendor", "name": "Acme", "detail": "", "evidence": "We send all data to Acme Corp."}
                ]
            }
        )
    )
    result = agent.run(review_id="g1", spec_text=SPEC)
    return result.facts == [] and result.dropped_ungrounded == 1


def domain_review_drops_unsupported(index: HybridIndex) -> bool:
    agent = DomainReviewAgent(
        "infosec",
        _fake(
            {
                "findings": [
                    {
                        "title": "Invented",
                        "severity": "critical",
                        "description": "x",
                        "cited_source_ids": ["not-a-source"],
                        "spec_evidence": "This text is not in the spec at all.",
                    }
                ]
            }
        ),
    )
    result = agent.review(review_id="g2", spec_text=SPEC, index=index, principal=PRINCIPAL)
    return result.findings == [] and result.dropped_unsupported == 1


def findings_strip_unsupported_remediation(index: HybridIndex) -> bool:
    agent = FindingsAgent(
        _fake(
            {
                "findings": [
                    {
                        "title": "Rotation",
                        "severity": "high",
                        "owner_role": "infosec",
                        "description": "x",
                        "remediation": "Do something invented.",
                        "remediation_source_ids": ["fake"],
                    }
                ]
            }
        )
    )
    out = agent.structure(review_id="g3", notes="Key rotation evidence missing", index=index, principal=PRINCIPAL)
    return len(out) == 1 and out[0].remediation is None and out[0].remediation_sources == []


def fix_verification_requires_quote() -> bool:
    agent = FindingsAgent(_fake({"addressed": True, "evidence": "Invented quote not in spec.", "explanation": "x"}))
    out = agent.verify_fix(review_id="g4", finding_id="f1", finding_text="Key rotation", revised_spec=SPEC)
    return out.verdict == "not_verified"


def brief_rejects_invented_numbers() -> bool:
    agent = DecisionBriefAgent(
        _fake({"summary": "There are 47 critical issues.", "claims": [{"text": "x", "evidence_ids": ["nope"]}]})
    )
    brief = agent.build(review_id="g5", drafts=[{"question_id": "q1", "status": "drafted", "answer": "a"}], findings=[])
    return brief.summary_replaced and "47" not in brief.summary and brief.dropped_claims == 1


def run_guard_suites(index: HybridIndex) -> dict[str, float]:
    checks = {
        "guard.extraction_quote": extraction_rejects_invented_quotes(),
        "guard.domain_review_support": domain_review_drops_unsupported(index),
        "guard.findings_remediation": findings_strip_unsupported_remediation(index),
        "guard.fix_verification_quote": fix_verification_requires_quote(),
        "guard.brief_numeric_grounding": brief_rejects_invented_numbers(),
    }
    return {name: float(ok) for name, ok in checks.items()}
