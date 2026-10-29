"""Shared API and domain models. Every boundary is validated here."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

DraftStatus = Literal["drafted", "needs_input"]


class Principal(BaseModel):
    model_config = ConfigDict(frozen=True)

    user_id: str
    teams: frozenset[str]
    is_human: bool = True


class SourceRef(BaseModel):
    source_id: str
    source_type: str
    version: str
    owner: str
    excerpt: str = Field(max_length=500)


class DraftAnswer(BaseModel):
    question_id: str
    answer: str | None
    status: DraftStatus
    sources: list[SourceRef] = Field(default_factory=list)
    model: str
    prompt_version: int


class InsightAnswer(BaseModel):
    answer: str | None
    status: DraftStatus
    sources: list[SourceRef] = Field(default_factory=list)
    model: str
    prompt_version: int


class InsightQuery(BaseModel):
    question: str = Field(min_length=3, max_length=2000)
    session_id: str | None = Field(default=None, max_length=64)


class Question(BaseModel):
    id: str = Field(min_length=1, max_length=64)
    text: str = Field(min_length=3, max_length=2000)


class DraftRequest(BaseModel):
    review_id: str = Field(min_length=1, max_length=64)
    questions: list[Question] = Field(min_length=1, max_length=100)
    spec_facts: str = Field(min_length=1, max_length=50_000)


class GateRequest(BaseModel):
    passed: bool
    note: str = Field(default="", max_length=1000)


class StartReviewRequest(BaseModel):
    review_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_.-]+$")
    request_text: str = Field(min_length=10, max_length=20_000)
    spec_text: str = Field(min_length=10, max_length=100_000)
    questions: list[Question] = Field(default_factory=list, max_length=200)


class GateDecisionRequest(BaseModel):
    passed: bool
    note: str = Field(default="", max_length=1000)
    updates: dict[str, object] = Field(default_factory=dict)


class TextRequest(BaseModel):
    review_id: str = Field(min_length=1, max_length=64)
    text: str = Field(min_length=3, max_length=100_000)


class FixVerificationRequest(BaseModel):
    review_id: str = Field(min_length=1, max_length=64)
    finding_id: str = Field(min_length=1, max_length=128)
    finding_text: str = Field(min_length=3, max_length=5000)
    revised_spec: str = Field(min_length=3, max_length=100_000)


class ChangeDetectionRequest(BaseModel):
    project_id: str = Field(min_length=1, max_length=64)
    approved_facts: list[dict[str, str]] = Field(max_length=500)
    current_spec: str = Field(min_length=3, max_length=100_000)


class SqlQuestion(BaseModel):
    question: str = Field(min_length=3, max_length=2000)


class FeedbackRequest(BaseModel):
    action: Literal["accepted", "edited", "rejected"]
    original: str = Field(default="", max_length=20_000)
    final: str | None = Field(default=None, max_length=20_000)
