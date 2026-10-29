"""Workflow nodes. Each node calls one agent and returns a state update.

Agents run with the requester's access, never more: retrieval inside the workflow uses the
requester's teams, so a review can't surface documents its requester could not open.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pia.agents.change_detection import ChangeDetectionAgent
from pia.agents.decision_brief import DecisionBriefAgent
from pia.agents.domain_review import TRACK_TO_DOMAIN, DomainReviewAgent
from pia.agents.drafting import DraftingAgent
from pia.agents.findings import FindingsAgent
from pia.agents.intake import IntakeAgent
from pia.agents.routing import RoutingRules
from pia.agents.spec_extraction import SpecExtractionAgent, facts_as_text
from pia.agents.text_to_sql import TextToSqlAgent
from pia.agents.triage import TriageAgent
from pia.rag.qa import GroundedQA
from pia.retrieval.index import HybridIndex
from pia.schemas import Principal, Question
from pia.workflow.state import ReviewState


@dataclass
class AgentSuite:
    intake: IntakeAgent
    triage: TriageAgent
    spec_extraction: SpecExtractionAgent
    drafting: DraftingAgent
    domain_reviews: dict[str, DomainReviewAgent]
    findings: FindingsAgent
    brief: DecisionBriefAgent
    change_detection: ChangeDetectionAgent
    text_to_sql: TextToSqlAgent
    qa: GroundedQA

    def count(self) -> int:
        return 9 + len(self.domain_reviews)


def _requester(state: ReviewState) -> Principal:
    return Principal(user_id=state["requester_id"], teams=frozenset(state["requester_teams"]), is_human=False)


def make_nodes(suite: AgentSuite, index: HybridIndex, rules: RoutingRules) -> dict[str, Any]:
    def intake(state: ReviewState) -> dict[str, Any]:
        result = suite.intake.run(review_id=state["review_id"], request_text=state["request_text"])
        return {"intake": {**result.fields.model_dump(), "missing": result.missing}, "stage": "intake_ready"}

    def triage(state: ReviewState) -> dict[str, Any]:
        result = suite.triage.triage(review_id=state["review_id"], request_text=state["request_text"], rules=rules)
        return {
            "tracks": result.tracks,
            "triage": {
                "reasons": result.reasons,
                "rejected_proposals": result.rejected_proposals,
                "needs_governance": result.needs_governance,
                "source": result.source,
            },
            "stage": "triage_ready",
        }

    def extraction(state: ReviewState) -> dict[str, Any]:
        result = suite.spec_extraction.run(review_id=state["review_id"], spec_text=state["spec_text"])
        return {"facts": [f.model_dump() for f in result.facts], "stage": "extraction_ready"}

    def _spec_context(state: ReviewState) -> str:
        facts = state.get("facts") or []
        return facts_as_text(facts) if facts else state["spec_text"]

    def drafting(state: ReviewState) -> dict[str, Any]:
        drafts = suite.drafting.draft(
            review_id=state["review_id"],
            questions=[Question(**q) for q in state.get("questions", [])],
            spec_facts=_spec_context(state),
            index=index,
            principal=_requester(state),
        )
        return {"drafts": [d.model_dump() for d in drafts], "stage": "drafts_ready"}

    def domain_review(state: ReviewState) -> dict[str, Any]:
        findings: list[dict[str, Any]] = []
        for track in state.get("tracks", []):
            domain = TRACK_TO_DOMAIN.get(track)
            if domain is None or domain not in suite.domain_reviews:
                continue
            result = suite.domain_reviews[domain].review(
                review_id=state["review_id"],
                spec_text=_spec_context(state),
                index=index,
                principal=_requester(state),
            )
            findings.extend(f.model_dump() for f in result.findings)
        return {"findings": findings, "stage": "review_ready"}

    def findings(state: ReviewState) -> dict[str, Any]:
        notes = (state.get("reviewer_notes") or "").strip()
        if not notes:
            return {"structured_findings": []}
        structured = suite.findings.structure(
            review_id=state["review_id"], notes=notes, index=index, principal=_requester(state)
        )
        return {"structured_findings": [f.model_dump() for f in structured]}

    def brief(state: ReviewState) -> dict[str, Any]:
        all_findings = [*state.get("findings", []), *state.get("structured_findings", [])]
        result = suite.brief.build(review_id=state["review_id"], drafts=state.get("drafts", []), findings=all_findings)
        return {"brief": result.model_dump(), "stage": "awaiting_approval"}

    return {
        "intake": intake,
        "triage": triage,
        "extraction": extraction,
        "drafting": drafting,
        "domain_review": domain_review,
        "findings": findings,
        "brief": brief,
    }
