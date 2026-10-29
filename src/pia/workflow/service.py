"""Review workflow service: starts reviews, records human gate decisions, and resumes the graph.

Controls enforced here (not in the UI):
- Only humans decide gates. Service and AI principals are refused.
- Only the teams configured for a gate may decide it.
- Separation of duties: the requester cannot decide gates marked for it (maker-checker).
- A decision is accepted only for the gate the review is actually waiting at, which also makes
  duplicate submissions harmless.
- Humans may change only the fields allowed for that gate.
- Every decision is written to the audit log.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from pia.agents.routing import RoutingRules
from pia.schemas import Principal
from pia.workflow.graph import GATES, build_graph
from pia.workflow.nodes import AgentSuite, make_nodes

STATUS_KEYS = (
    "review_id",
    "stage",
    "tracks",
    "intake",
    "triage",
    "facts",
    "drafts",
    "findings",
    "structured_findings",
    "brief",
    "decision_log",
)


class WorkflowError(Exception):
    status_code = 400


class NotFound(WorkflowError):
    status_code = 404


class Conflict(WorkflowError):
    status_code = 409


class Forbidden(WorkflowError):
    status_code = 403


@dataclass(frozen=True)
class GatePolicy:
    teams: frozenset[str]
    allowed_updates: frozenset[str] = field(default_factory=frozenset)
    separation_of_duties: bool = False


def load_gate_policies(path: Path) -> dict[str, GatePolicy]:
    data = yaml.safe_load(path.read_text()) or {}
    policies = {
        name: GatePolicy(
            teams=frozenset(spec.get("teams", [])),
            allowed_updates=frozenset(spec.get("allowed_updates", [])),
            separation_of_duties=bool(spec.get("separation_of_duties", False)),
        )
        for name, spec in data.get("gates", {}).items()
    }
    missing = {g for g, _, _ in GATES} - policies.keys()
    if missing:
        raise ValueError(f"gate policies missing for: {sorted(missing)}")
    return policies


class ReviewWorkflow:
    def __init__(
        self, suite: AgentSuite, index, rules: RoutingRules, policies: dict[str, GatePolicy], audit, checkpointer
    ):
        self._graph = build_graph(make_nodes(suite, index, rules), checkpointer=checkpointer)
        self._rules = rules
        self._policies = policies
        self._audit = audit

    @staticmethod
    def _config(review_id: str) -> dict[str, Any]:
        return {"configurable": {"thread_id": review_id}}

    def _values(self, review_id: str) -> dict[str, Any]:
        return dict(self._graph.get_state(self._config(review_id)).values or {})

    def waiting_for(self, review_id: str) -> str | None:
        nxt = self._graph.get_state(self._config(review_id)).next
        return nxt[0].removeprefix("gate_") if nxt else None

    def exists(self, review_id: str) -> bool:
        return bool(self._values(review_id))

    def can_view(self, principal: Principal, review_id: str) -> bool:
        values = self._values(review_id)
        if not values:
            return False
        gate_teams = frozenset().union(*(p.teams for p in self._policies.values()))
        return (
            principal.user_id == values.get("requester_id")
            or bool(principal.teams & gate_teams)
            or "audit" in principal.teams
        )

    def status(self, review_id: str) -> dict[str, Any]:
        values = self._values(review_id)
        if not values:
            raise NotFound("review not found")
        out = {k: values.get(k) for k in STATUS_KEYS}
        out["waiting_for_gate"] = self.waiting_for(review_id)
        return out

    def start(
        self,
        *,
        review_id: str,
        principal: Principal,
        request_text: str,
        spec_text: str,
        questions: list[dict[str, Any]],
    ) -> dict[str, Any]:
        if self.exists(review_id):
            raise Conflict("review already exists")
        initial = {
            "review_id": review_id,
            "requester_id": principal.user_id,
            "requester_teams": sorted(principal.teams),
            "request_text": request_text,
            "spec_text": spec_text,
            "questions": questions,
            "gate_decisions": {},
            "decision_log": [],
            "stage": "submitted",
        }
        self._audit.append(principal.user_id, "human", "review.started", review_id, {"questions": len(questions)})
        self._graph.invoke(initial, self._config(review_id))
        self._audit.append(
            "workflow", "system", "review.stage", review_id, {"stage": self._values(review_id).get("stage")}
        )
        return self.status(review_id)

    def decide(
        self,
        *,
        review_id: str,
        gate: str,
        principal: Principal,
        passed: bool,
        note: str = "",
        updates: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        values = self._values(review_id)
        if not values:
            raise NotFound("review not found")
        if gate not in self._policies:
            raise NotFound("unknown gate")
        if not principal.is_human:
            raise Forbidden("AI and service principals cannot decide review gates")
        policy = self._policies[gate]
        if not (principal.teams & policy.teams):
            raise Forbidden(f"gate '{gate}' requires one of: {sorted(policy.teams)}")
        if policy.separation_of_duties and principal.user_id == values.get("requester_id"):
            raise Forbidden("separation of duties: the requester cannot decide this gate")
        waiting = self.waiting_for(review_id)
        if waiting != gate:
            raise Conflict(f"review is waiting for gate '{waiting}', not '{gate}'")

        updates = dict(updates or {})
        disallowed = set(updates) - policy.allowed_updates
        if disallowed:
            raise Forbidden(f"fields not editable at gate '{gate}': {sorted(disallowed)}")
        if "tracks" in updates:
            tracks = updates["tracks"]
            if not isinstance(tracks, list) or not set(tracks) <= set(self._rules.tracks):
                raise WorkflowError(f"tracks must be a subset of {self._rules.tracks}")

        decision = {
            "passed": passed,
            "by": principal.user_id,
            "note": note[:1000],
            "at": datetime.now(UTC).isoformat(),
        }
        decisions = {**values.get("gate_decisions", {}), gate: decision}
        log = [*values.get("decision_log", []), {"gate": gate, **decision, "updated_fields": sorted(updates)}]
        self._graph.update_state(self._config(review_id), {**updates, "gate_decisions": decisions, "decision_log": log})
        self._audit.append(
            principal.user_id,
            "human",
            "gate.decided",
            review_id,
            {"gate": gate, "passed": passed, "updated_fields": sorted(updates)},
        )
        self._graph.invoke(None, self._config(review_id))
        stage = self._values(review_id).get("stage")
        self._audit.append("workflow", "system", "review.stage", review_id, {"stage": stage})
        return self.status(review_id)


def build_checkpointer(persistence: str, database_url: str):
    if persistence == "postgres":
        try:
            from langgraph.checkpoint.postgres import PostgresSaver
        except ImportError as exc:
            raise RuntimeError("install the 'postgres' extra for Postgres checkpoints") from exc
        import psycopg

        conn = psycopg.connect(database_url.replace("+psycopg", ""), autocommit=True, prepare_threshold=0)
        saver = PostgresSaver(conn)
        saver.setup()
        return saver
    from langgraph.checkpoint.memory import InMemorySaver

    return InMemorySaver()
