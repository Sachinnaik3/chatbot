"""Audit, online metrics, cost, and memory administration."""

from __future__ import annotations

from fastapi import APIRouter, Request

from pia.api.deps import CurrentPrincipal, ctx, require_team
from pia.feedback_store import summarize_records

router = APIRouter(tags=["admin"])


@router.get("/v1/audit/verify")
def verify_audit(request: Request, principal: CurrentPrincipal) -> dict[str, object]:
    require_team(principal, "audit")
    state = ctx(request)
    return {"valid": state.audit.verify(), "events": len(state.audit.events())}


@router.get("/v1/audit/reviews/{review_id}")
def review_audit(review_id: str, request: Request, principal: CurrentPrincipal) -> list[dict[str, object]]:
    require_team(principal, "audit")
    return [e.body() | {"hash": e.hash} for e in ctx(request).audit.events(review_id)]


@router.get("/v1/metrics/online")
def online_metrics(request: Request, principal: CurrentPrincipal) -> dict[str, float]:
    require_team(principal, "governance", "audit")
    return summarize_records(ctx(request).feedback.all())


@router.get("/v1/costs/{scope_type}/{scope_id}")
def cost(scope_type: str, scope_id: str, request: Request, principal: CurrentPrincipal) -> dict[str, object]:
    require_team(principal, "governance", "audit")
    scope = f"{scope_type}:{scope_id}"
    tracker = ctx(request).cost
    return {"scope": scope, "tokens": tracker.tokens(scope), "usd": tracker.usd(scope)}


@router.delete("/v1/me/memory")
def forget_me(request: Request, principal: CurrentPrincipal) -> dict[str, object]:
    """Right to erasure for the caller's long-term memory."""
    state = ctx(request)
    removed = state.long_term.forget(principal.user_id)
    state.audit.append(principal.user_id, "human", "memory.erased", payload={"items": removed})
    return {"removed": removed}
