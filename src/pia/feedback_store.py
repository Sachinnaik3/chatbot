"""Stores reviewer feedback on drafts for online evaluation. Stores edit ratios, not text."""

from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher


def edit_ratio(original: str, final: str) -> float:
    return 1.0 - SequenceMatcher(None, original, final).ratio()


@dataclass(frozen=True)
class FeedbackRecord:
    review_id: str
    question_id: str
    action: str
    edit_ratio: float | None
    actor: str


class InMemoryFeedbackStore:
    def __init__(self) -> None:
        self._records: list[FeedbackRecord] = []

    def add(
        self, review_id: str, question_id: str, action: str, original: str, final: str | None, actor: str
    ) -> FeedbackRecord:
        ratio = edit_ratio(original, final) if action == "edited" and final is not None else None
        record = FeedbackRecord(review_id, question_id, action, ratio, actor)
        self._records.append(record)
        return record

    def all(self) -> list[FeedbackRecord]:
        return list(self._records)


def summarize_records(records: list[FeedbackRecord]) -> dict[str, float]:
    total = len(records)
    if not total:
        return {
            "feedback.count": 0.0,
            "feedback.acceptance_rate": 0.0,
            "feedback.rejection_rate": 0.0,
            "feedback.mean_edit_ratio": 0.0,
        }
    edited = [r.edit_ratio for r in records if r.edit_ratio is not None]
    return {
        "feedback.count": float(total),
        "feedback.acceptance_rate": sum(r.action == "accepted" for r in records) / total,
        "feedback.rejection_rate": sum(r.action == "rejected" for r in records) / total,
        "feedback.mean_edit_ratio": sum(edited) / len(edited) if edited else 0.0,
    }
