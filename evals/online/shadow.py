"""Shadow mode: AI drafts are generated but hidden from reviewers. After humans answer, compare.

The most important number is the miss rate on questions the human could answer but the AI marked
'needs_input' (lost help) versus questions the AI drafted that the human could not answer
(possible overreach, which needs investigation before drafts are shown to anyone).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ShadowPair:
    question_id: str
    ai_status: str
    human_answered: bool


def shadow_metrics(pairs: list[ShadowPair]) -> dict[str, float]:
    total = len(pairs)
    if not total:
        return {"shadow.count": 0.0}
    drafted = [p for p in pairs if p.ai_status == "drafted"]
    answerable = [p for p in pairs if p.human_answered]
    overreach = sum(not p.human_answered for p in drafted)
    covered = sum(p.ai_status == "drafted" for p in answerable)
    return {
        "shadow.count": float(total),
        "shadow.coverage": covered / len(answerable) if answerable else 0.0,
        "shadow.overreach_rate": overreach / len(drafted) if drafted else 0.0,
        "shadow.agreement": sum((p.ai_status == "drafted") == p.human_answered for p in pairs) / total,
    }
