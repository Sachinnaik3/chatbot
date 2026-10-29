"""Insight endpoints: grounded Q&A with session memory, and validated read-only SQL."""

from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException, Request

from pia.api.deps import CurrentPrincipal, ctx, require_team
from pia.cache import cache_key
from pia.guardrails.input import scan_input
from pia.schemas import InsightAnswer, InsightQuery, SqlQuestion

router = APIRouter(prefix="/v1/insight", tags=["insight"])


def _reject_injection(state, principal, text: str, action: str) -> str:
    scan = scan_input(text)
    if scan.injection_hits:
        state.metrics.inc("guardrail_blocked_total", {"guard": "injection"})
        state.audit.append(principal.user_id, "human", action, payload={"signals": len(scan.injection_hits)})
        raise HTTPException(status_code=422, detail="request rejected by input policy")
    return scan.text


@router.post("/query", response_model=InsightAnswer)
def insight_query(body: InsightQuery, request: Request, principal: CurrentPrincipal) -> InsightAnswer:
    state = ctx(request)
    question = _reject_injection(state, principal, body.question, "input.injection_rejected")
    history = state.memory.recent(principal.user_id, body.session_id) if body.session_id else []
    key = cache_key("qa", "|".join(sorted(principal.teams)), question)
    if not history:
        cached = state.cache.get(key)
        if cached:
            state.metrics.inc("cache_hits_total", {"cache": "qa"})
            return InsightAnswer.model_validate(json.loads(cached))

    answer = state.agents.qa.ask(question, principal, history=history)
    if body.session_id:
        state.memory.append(principal.user_id, body.session_id, "user", question)
        state.memory.append(principal.user_id, body.session_id, "assistant", answer.answer or "")
    if not history:
        state.cache.set(key, answer.model_dump_json(), state.settings.cache_ttl_s)
    state.audit.append(
        principal.user_id, "human", "insight.query", payload={"status": answer.status, "sources": len(answer.sources)}
    )
    return answer


@router.post("/sql")
def insight_sql(body: SqlQuestion, request: Request, principal: CurrentPrincipal) -> dict[str, object]:
    require_team(principal, "governance", "audit", "risk")
    state = ctx(request)
    question = _reject_injection(state, principal, body.question, "input.injection_rejected")
    sql = state.agents.text_to_sql.generate(
        scope=f"sql:{principal.user_id}", question=question, allowlist=state.sql_allowlist
    )
    rows = state.sql_executor.run(sql) if state.sql_executor else None
    state.audit.append(
        principal.user_id,
        "human",
        "insight.sql",
        payload={"executed": rows is not None, "rows": len(rows) if rows is not None else 0},
    )
    return {"sql": sql, "executed": rows is not None, "rows": rows}
