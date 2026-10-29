"""Workflow state for one review. The checkpointer persists it after every node, so a crash or a
duplicate request resumes from the last completed step instead of starting over."""

from __future__ import annotations

from typing import Any, TypedDict


class ReviewState(TypedDict, total=False):
    review_id: str
    requester_id: str
    requester_teams: list[str]
    request_text: str
    spec_text: str
    questions: list[dict[str, Any]]
    intake: dict[str, Any]
    tracks: list[str]
    triage: dict[str, Any]
    facts: list[dict[str, Any]]
    drafts: list[dict[str, Any]]
    findings: list[dict[str, Any]]
    reviewer_notes: str
    structured_findings: list[dict[str, Any]]
    brief: dict[str, Any]
    gate_decisions: dict[str, dict[str, Any]]
    decision_log: list[dict[str, Any]]
    stage: str
