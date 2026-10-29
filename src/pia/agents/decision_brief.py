"""Decision brief agent: a short brief for the approver with traceable claims.

Numeric grounding: every count in the brief is computed from records by code. If the model's
summary contains a number that is not one of those counts, the summary is replaced with a
deterministic template. Claims whose evidence ids are not real items are dropped.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from pia.agents.base import Agent
from pia.guardrails.output import numbers_in
from pia.prompts.registry import wrap_untrusted


class Claim(BaseModel):
    text: str = Field(max_length=500)
    evidence_ids: list[str] = Field(default_factory=list)


class BriefOut(BaseModel):
    summary: str = Field(max_length=2000)
    claims: list[Claim] = Field(default_factory=list, max_length=20)


class DecisionBrief(BaseModel):
    review_id: str
    summary: str
    claims: list[Claim]
    stats: dict[str, int]
    open_finding_ids: list[str]
    dropped_claims: int
    summary_replaced: bool


def compute_stats(drafts: list[dict[str, Any]], findings: list[dict[str, Any]]) -> dict[str, int]:
    stats = {
        "questions_total": len(drafts),
        "questions_drafted": sum(d.get("status") == "drafted" for d in drafts),
        "questions_needing_input": sum(d.get("status") == "needs_input" for d in drafts),
        "findings_total": len(findings),
        "findings_open": sum(f.get("status", "candidate") in {"candidate", "confirmed", "open"} for f in findings),
    }
    for sev in ("critical", "high", "medium", "low"):
        stats[f"findings_{sev}"] = sum(f.get("severity") == sev for f in findings)
    return stats


def build_items(drafts: list[dict[str, Any]], findings: list[dict[str, Any]]) -> tuple[str, set[str]]:
    lines: list[str] = []
    ids: set[str] = set()
    for d in drafts:
        item_id = f"draft:{d['question_id']}"
        ids.add(item_id)
        lines.append(
            f'<item id="{item_id}" kind="draft" status="{d.get("status")}">{(d.get("answer") or "")[:300]}</item>'
        )
    for f in findings:
        ids.add(f["finding_id"])
        lines.append(
            f'<item id="{f["finding_id"]}" kind="finding" severity="{f.get("severity")}">'
            f"{f.get('title', '')[:200]}</item>"
        )
    return "\n".join(lines), ids


def template_summary(stats: dict[str, int]) -> str:
    return (
        f"{stats['questions_drafted']} of {stats['questions_total']} questions have drafted answers and "
        f"{stats['questions_needing_input']} need input. There are {stats['findings_open']} open findings, "
        f"including {stats['findings_critical']} critical and {stats['findings_high']} high."
    )


class DecisionBriefAgent(Agent):
    prompt_name = "decision_brief"
    max_tokens = 1500

    def build(self, *, review_id: str, drafts: list[dict[str, Any]], findings: list[dict[str, Any]]) -> DecisionBrief:
        stats = compute_stats(drafts, findings)
        items, ids = build_items(drafts, findings)
        out, _, _ = self._invoke(f"review:{review_id}", BriefOut, items=wrap_untrusted("items", items or "(none)"))

        claims = [c for c in out.claims if c.evidence_ids and set(c.evidence_ids) <= ids]
        dropped = len(out.claims) - len(claims)
        allowed_numbers = {str(v) for v in stats.values()}
        replaced = bool(numbers_in(out.summary) - allowed_numbers) or not out.summary.strip()
        summary = template_summary(stats) if replaced else f"{out.summary} {template_summary(stats)}"
        open_ids = [
            f["finding_id"] for f in findings if f.get("status", "candidate") in {"candidate", "confirmed", "open"}
        ]
        return DecisionBrief(
            review_id=review_id,
            summary=summary,
            claims=claims,
            stats=stats,
            open_finding_ids=open_ids,
            dropped_claims=dropped,
            summary_replaced=replaced,
        )
