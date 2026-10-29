"""LLM-as-judge for answer quality, plus calibration against human labels.

A judge is only trusted after its scores agree with human reviewers on a labeled sample.
Track Cohen's kappa over time; recalibrate when it drops.
"""

from __future__ import annotations

from collections import Counter

from pydantic import BaseModel, Field

from pia.agents.base import Agent
from pia.prompts.registry import wrap_untrusted


class JudgeScore(BaseModel):
    score: int = Field(ge=1, le=5)
    rationale: str = Field(default="", max_length=1000)


class AnswerJudge(Agent):
    prompt_name = "judge"

    def score(self, *, question: str, answer: str, sources: str) -> JudgeScore:
        out, _, _ = self._invoke(
            "eval:judge",
            JudgeScore,
            question=wrap_untrusted("question", question),
            answer=wrap_untrusted("answer", answer),
            sources=wrap_untrusted("sources", sources),
        )
        return out


def cohens_kappa(a: list[int], b: list[int]) -> float:
    if len(a) != len(b) or not a:
        raise ValueError("label lists must be non-empty and the same length")
    n = len(a)
    observed = sum(x == y for x, y in zip(a, b, strict=True)) / n
    ca, cb = Counter(a), Counter(b)
    expected = sum(ca[k] * cb[k] for k in set(ca) | set(cb)) / (n * n)
    return 1.0 if expected == 1 else (observed - expected) / (1 - expected)
