"""Triage agent: proposes review tracks. Deterministic rules are the floor; the AI can add tracks
but unknown track names are rejected and routed to governance."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, Field

from pia.agents.base import Agent
from pia.agents.routing import RoutingRules
from pia.prompts.registry import wrap_untrusted


class TrackProposal(BaseModel):
    track: str = Field(max_length=64)
    reason: str = Field(max_length=300)


class TriageBatch(BaseModel):
    tracks: list[TrackProposal]


@dataclass(frozen=True)
class TriageResult:
    tracks: list[str]
    reasons: dict[str, str]
    rejected_proposals: list[str] = field(default_factory=list)
    needs_governance: bool = False
    source: Literal["rules", "rules+ai"] = "rules"


class TriageAgent(Agent):
    prompt_name = "triage"

    def triage(self, *, review_id: str, request_text: str, rules: RoutingRules) -> TriageResult:
        deterministic = rules.match(request_text)
        out, _, _ = self._invoke(
            f"review:{review_id}",
            TriageBatch,
            allowed_tracks=", ".join(rules.tracks),
            request=wrap_untrusted("request", request_text),
        )
        proposed = {p.track: p.reason for p in out.tracks if p.track in rules.tracks}
        rejected = [p.track for p in out.tracks if p.track not in rules.tracks]

        tracks = sorted(deterministic | set(proposed))
        reasons = {t: "matched routing rule" for t in deterministic}
        reasons.update({t: r for t, r in proposed.items() if t not in deterministic})
        return TriageResult(
            tracks=tracks,
            reasons=reasons,
            rejected_proposals=rejected,
            needs_governance=bool(rejected) or not tracks,
            source="rules+ai" if proposed else "rules",
        )
