"""Change detection agent: decides whether changes to an approved design need re-review.

The diff is computed by code. Deterministic rules are the floor: a new data store, data flow,
vendor, or integration, or a removed control, always requires re-review. The model can add
reasons but cannot downgrade a rule match. With no diff, the model is not called.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from pia.agents.base import Agent
from pia.guardrails.output import normalize_text
from pia.prompts.registry import wrap_untrusted

MATERIAL_ADDITIONS = {"data_store", "data_flow", "vendor", "integration"}


class ChangeOut(BaseModel):
    rereview_required: bool
    reasons: list[str] = Field(default_factory=list, max_length=20)


class ChangeDecision(BaseModel):
    rereview_required: bool
    reasons: list[str]
    added: list[dict[str, Any]]
    removed: list[dict[str, Any]]
    source: Literal["no_change", "rules", "rules+ai"]


def _key(fact: dict[str, Any]) -> tuple[str, str]:
    return fact["category"], normalize_text(fact["name"])


def diff_facts(approved: list[dict[str, Any]], current: list[dict[str, Any]]) -> tuple[list[dict], list[dict]]:
    a = {_key(f): f for f in approved}
    c = {_key(f): f for f in current}
    added = [c[k] for k in c.keys() - a.keys()]
    removed = [a[k] for k in a.keys() - c.keys()]
    return sorted(added, key=_key), sorted(removed, key=_key)


def rule_reasons(added: list[dict[str, Any]], removed: list[dict[str, Any]]) -> list[str]:
    reasons = [f"new {f['category']}: {f['name']}" for f in added if f["category"] in MATERIAL_ADDITIONS]
    reasons += [f"removed control: {f['name']}" for f in removed if f["category"] == "control"]
    return reasons


class ChangeDetectionAgent(Agent):
    prompt_name = "change_detection"

    def detect(
        self, *, scope: str, approved_facts: list[dict[str, Any]], current_facts: list[dict[str, Any]]
    ) -> ChangeDecision:
        added, removed = diff_facts(approved_facts, current_facts)
        if not added and not removed:
            return ChangeDecision(rereview_required=False, reasons=[], added=[], removed=[], source="no_change")
        floor = rule_reasons(added, removed)
        diff_text = "\n".join(
            [
                *(f"added {f['category']}: {f['name']}" for f in added),
                *(f"removed {f['category']}: {f['name']}" for f in removed),
            ]
        )
        out, _, _ = self._invoke(scope, ChangeOut, diff=wrap_untrusted("diff", diff_text))
        reasons = list(dict.fromkeys([*floor, *(r[:300] for r in out.reasons)]))
        return ChangeDecision(
            rereview_required=bool(floor) or out.rereview_required,
            reasons=reasons,
            added=added,
            removed=removed,
            source="rules+ai" if out.rereview_required or out.reasons else "rules",
        )
