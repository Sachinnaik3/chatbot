"""Online metrics from reviewer feedback. Edit distance measures how much a reviewer changed a draft."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from pia.feedback_store import edit_ratio

Action = Literal["accepted", "edited", "rejected"]


@dataclass(frozen=True)
class FeedbackEvent:
    draft_id: str
    action: Action
    original: str
    final: str | None


def summarize(events: list[FeedbackEvent]) -> dict[str, float]:
    total = len(events)
    if total == 0:
        return {
            "feedback.count": 0,
            "feedback.acceptance_rate": 0.0,
            "feedback.rejection_rate": 0.0,
        }
    accepted = sum(e.action == "accepted" for e in events)
    rejected = sum(e.action == "rejected" for e in events)
    edited = [e for e in events if e.action == "edited" and e.final is not None]
    return {
        "feedback.count": float(total),
        "feedback.acceptance_rate": accepted / total,
        "feedback.rejection_rate": rejected / total,
        "feedback.mean_edit_ratio": (sum(edit_ratio(e.original, e.final) for e in edited) / len(edited))
        if edited
        else 0.0,
    }
