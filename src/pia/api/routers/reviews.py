"""Review workflow endpoints: start, read status, decide gates, read the brief, and give draft feedback."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from pia.api.deps import CurrentPrincipal, ctx
from pia.guardrails.input import scan_input
from pia.schemas import FeedbackRequest, GateDecisionRequest, StartReviewRequest
from pia.workflow.service import WorkflowError

router = APIRouter(prefix="/v1/reviews", tags=["reviews"])


def _http(exc: WorkflowError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=str(exc))


def _visible(state, principal, review_id: str) -> None:
    # 404 instead of 403, so callers can't probe which review IDs exist.
    if not state.workflow.can_view(principal, review_id):
        raise HTTPException(status_code=404, detail="review not found")


@router.post("", status_code=201)
def start_review(body: StartReviewRequest, request: Request, principal: CurrentPrincipal) -> dict[str, object]:
    state = ctx(request)
    if not principal.is_human:
        raise HTTPException(status_code=403, detail="reviews must be submitted by a person")
    request_scan, spec_scan = scan_input(body.request_text), scan_input(body.spec_text)
    if request_scan.injection_hits or spec_scan.injection_hits:
        state.metrics.inc("guardrail_flagged_total", {"guard": "injection"})
        state.audit.append(
            "guardrails",
            "system",
            "security.injection_flagged",
            body.review_id,
            {"signals": len(request_scan.injection_hits) + len(spec_scan.injection_hits)},
        )
    try:
        return state.workflow.start(
            review_id=body.review_id,
            principal=principal,
            request_text=request_scan.text,
            spec_text=spec_scan.text,
            questions=[q.model_dump() for q in body.questions],
        )
    except WorkflowError as exc:
        raise _http(exc) from exc


@router.get("/{review_id}")
def get_review(review_id: str, request: Request, principal: CurrentPrincipal) -> dict[str, object]:
    state = ctx(request)
    _visible(state, principal, review_id)
    return state.workflow.status(review_id)


@router.post("/{review_id}/gates/{gate}")
def decide_gate(
    review_id: str, gate: str, body: GateDecisionRequest, request: Request, principal: CurrentPrincipal
) -> dict[str, object]:
    state = ctx(request)
    _visible(state, principal, review_id)
    updates = dict(body.updates)
    for key in ("request_text", "spec_text", "reviewer_notes"):
        if isinstance(updates.get(key), str):
            updates[key] = scan_input(updates[key]).text
    try:
        return state.workflow.decide(
            review_id=review_id, gate=gate, principal=principal, passed=body.passed, note=body.note, updates=updates
        )
    except WorkflowError as exc:
        raise _http(exc) from exc


@router.get("/{review_id}/brief")
def get_brief(review_id: str, request: Request, principal: CurrentPrincipal) -> dict[str, object]:
    state = ctx(request)
    _visible(state, principal, review_id)
    brief = state.workflow.status(review_id).get("brief")
    if not brief:
        raise HTTPException(status_code=404, detail="brief not ready")
    return brief


@router.post("/{review_id}/drafts/{question_id}/feedback", status_code=201)
def draft_feedback(
    review_id: str, question_id: str, body: FeedbackRequest, request: Request, principal: CurrentPrincipal
) -> dict[str, object]:
    state = ctx(request)
    _visible(state, principal, review_id)
    record = state.feedback.add(review_id, question_id, body.action, body.original, body.final, principal.user_id)
    state.audit.append(
        principal.user_id, "human", "draft.feedback", review_id, {"question_id": question_id, "action": body.action}
    )
    return {"recorded": True, "edit_ratio": record.edit_ratio}
