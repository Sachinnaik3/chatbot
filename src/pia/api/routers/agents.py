"""Direct agent endpoints, for use outside the workflow (for example, a team checking a draft
spec before submitting). They return proposals only and never change review state."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from pia.agents.spec_extraction import facts_as_text
from pia.api.deps import CurrentPrincipal, ctx, require_team
from pia.guardrails.input import scan_input
from pia.schemas import ChangeDetectionRequest, DraftAnswer, DraftRequest, FixVerificationRequest, TextRequest

router = APIRouter(prefix="/v1/agents", tags=["agents"])
DOMAINS = ("risk", "infosec", "privacy")


def _clean(state, principal, review_id: str, text: str) -> str:
    scan = scan_input(text)
    if scan.injection_hits:
        state.metrics.inc("guardrail_flagged_total", {"guard": "injection"})
        state.audit.append(
            principal.user_id, "system", "security.injection_flagged", review_id, {"signals": len(scan.injection_hits)}
        )
    return scan.text


@router.post("/intake")
def intake(body: TextRequest, request: Request, principal: CurrentPrincipal) -> dict[str, object]:
    state = ctx(request)
    result = state.agents.intake.run(
        review_id=body.review_id, request_text=_clean(state, principal, body.review_id, body.text)
    )
    return {"fields": result.fields.model_dump(), "missing": result.missing}


@router.post("/spec-extraction")
def spec_extraction(body: TextRequest, request: Request, principal: CurrentPrincipal) -> dict[str, object]:
    state = ctx(request)
    result = state.agents.spec_extraction.run(
        review_id=body.review_id, spec_text=_clean(state, principal, body.review_id, body.text)
    )
    return {"facts": [f.model_dump() for f in result.facts], "dropped_ungrounded": result.dropped_ungrounded}


@router.post("/drafting", response_model=list[DraftAnswer])
def drafting(body: DraftRequest, request: Request, principal: CurrentPrincipal) -> list[DraftAnswer]:
    state = ctx(request)
    drafts = state.agents.drafting.draft(
        review_id=body.review_id,
        questions=body.questions,
        spec_facts=_clean(state, principal, body.review_id, body.spec_facts),
        index=state.index,
        principal=principal,
    )
    state.audit.append(
        principal.user_id,
        "human",
        "drafts.generated",
        body.review_id,
        {"questions": len(body.questions), "drafted": sum(d.status == "drafted" for d in drafts)},
    )
    return drafts


@router.post("/domain-review/{domain}")
def domain_review(domain: str, body: TextRequest, request: Request, principal: CurrentPrincipal) -> dict[str, object]:
    if domain not in DOMAINS:
        raise HTTPException(status_code=404, detail="unknown domain")
    require_team(principal, domain, "governance")
    state = ctx(request)
    result = state.agents.domain_reviews[domain].review(
        review_id=body.review_id,
        spec_text=_clean(state, principal, body.review_id, body.text),
        index=state.index,
        principal=principal,
    )
    return {"findings": [f.model_dump() for f in result.findings], "dropped_unsupported": result.dropped_unsupported}


@router.post("/findings")
def findings(body: TextRequest, request: Request, principal: CurrentPrincipal) -> dict[str, object]:
    require_team(principal, *DOMAINS, "governance")
    state = ctx(request)
    structured = state.agents.findings.structure(
        review_id=body.review_id,
        notes=_clean(state, principal, body.review_id, body.text),
        index=state.index,
        principal=principal,
    )
    return {"findings": [f.model_dump() for f in structured]}


@router.post("/findings/verify-fix")
def verify_fix(body: FixVerificationRequest, request: Request, principal: CurrentPrincipal) -> dict[str, object]:
    state = ctx(request)
    result = state.agents.findings.verify_fix(
        review_id=body.review_id,
        finding_id=body.finding_id,
        finding_text=body.finding_text,
        revised_spec=_clean(state, principal, body.review_id, body.revised_spec),
    )
    return result.model_dump()


@router.post("/change-detection")
def change_detection(body: ChangeDetectionRequest, request: Request, principal: CurrentPrincipal) -> dict[str, object]:
    require_team(principal, "governance", "project")
    state = ctx(request)
    spec = _clean(state, principal, body.project_id, body.current_spec)
    current = state.agents.spec_extraction.run(review_id=f"change:{body.project_id}", spec_text=spec)
    decision = state.agents.change_detection.detect(
        scope=f"change:{body.project_id}",
        approved_facts=body.approved_facts,
        current_facts=[f.model_dump() for f in current.facts],
    )
    state.audit.append(
        principal.user_id,
        "human",
        "change.detected",
        payload={"project_id": body.project_id, "rereview_required": decision.rereview_required},
    )
    return {**decision.model_dump(), "current_facts_text": facts_as_text(current.facts)}
