"""Intake agent: turns a free-text change request into structured fields and lists gaps.

Deterministic completeness rules are the floor. The model can add missing items, never remove them.
"""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel, Field

from pia.agents.base import Agent
from pia.prompts.registry import wrap_untrusted


class IntakeFields(BaseModel):
    summary: str = Field(default="", max_length=2000)
    data_types: list[str] = Field(default_factory=list, max_length=20)
    customer_facing: bool | None = None
    vendors: list[str] = Field(default_factory=list, max_length=20)
    regions: list[str] = Field(default_factory=list, max_length=20)
    missing_information: list[str] = Field(default_factory=list, max_length=20)


@dataclass(frozen=True)
class IntakeResult:
    fields: IntakeFields
    missing: list[str]


def deterministic_gaps(fields: IntakeFields, request_text: str) -> list[str]:
    low = request_text.lower()
    gaps: list[str] = []
    if not fields.summary.strip():
        gaps.append("summary of the change")
    if not fields.data_types:
        gaps.append("types of data involved")
    if fields.customer_facing is None:
        gaps.append("whether customers are affected")
    personal = any("personal" in t.lower() or "card" in t.lower() for t in fields.data_types)
    if personal and "retention" not in low and "retain" not in low:
        gaps.append("retention period for personal data")
    if fields.data_types and not fields.regions:
        gaps.append("regions where data is stored or processed")
    if fields.vendors and "contract" not in low and "dpa" not in low:
        gaps.append("vendor contract or data processing agreement status")
    return gaps


class IntakeAgent(Agent):
    prompt_name = "intake"

    def run(self, *, review_id: str, request_text: str) -> IntakeResult:
        fields, _, _ = self._invoke(
            f"review:{review_id}", IntakeFields, request=wrap_untrusted("request", request_text)
        )
        missing: list[str] = []
        for item in [*deterministic_gaps(fields, request_text), *fields.missing_information]:
            if item and item not in missing:
                missing.append(item[:200])
        return IntakeResult(fields=fields, missing=missing)
