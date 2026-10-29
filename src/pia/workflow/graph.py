"""Review graph: every AI step is followed by a human gate.

    intake -> [intake gate] -> triage -> [triage gate] -> extraction -> [extraction gate]
    -> drafting -> [draft gate] -> domain_review -> [review gate] -> findings -> brief
    -> [approval gate] -> END

Gates are interrupt points. The graph pauses before each gate until a human decides through
the API. 'Returned' sends the review back to the step that produced the work, so it can be
redone with the human's corrections. A rejected approval ends the review.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pia.workflow.state import ReviewState

Node = Callable[[ReviewState], dict[str, Any]]

FINISH = "__finish__"

# (gate, producing node, next node on pass)
GATES: list[tuple[str, str, str]] = [
    ("intake", "intake", "triage"),
    ("triage", "triage", "extraction"),
    ("extraction", "extraction", "drafting"),
    ("draft", "drafting", "domain_review"),
    ("review", "domain_review", "findings"),
    ("approval", "brief", FINISH),
]
GATE_NODES = [f"gate_{g}" for g, _, _ in GATES]


def _gate_node(gate: str) -> Node:
    def node(state: ReviewState) -> dict[str, Any]:
        decision = state.get("gate_decisions", {}).get(gate, {})
        if decision.get("passed"):
            return {"stage": "approved" if gate == "approval" else f"{gate}_passed"}
        return {"stage": "rejected" if gate == "approval" else f"{gate}_returned"}

    return node


def _route(gate: str, on_return: str, on_pass: str) -> Callable[[ReviewState], str]:
    def route(state: ReviewState) -> str:
        from langgraph.graph import END

        passed = state.get("gate_decisions", {}).get(gate, {}).get("passed")
        if passed:
            return END if on_pass == FINISH else on_pass
        return END if gate == "approval" else on_return

    return route


def build_graph(nodes: dict[str, Node], checkpointer: Any | None = None):
    from langgraph.graph import END, StateGraph

    required = {"intake", "triage", "extraction", "drafting", "domain_review", "findings", "brief"}
    missing = required - nodes.keys()
    if missing:
        raise ValueError(f"missing workflow nodes: {sorted(missing)}")

    g = StateGraph(ReviewState)
    for name in required:
        g.add_node(name, nodes[name])
    for gate, _, _ in GATES:
        g.add_node(f"gate_{gate}", _gate_node(gate))

    g.set_entry_point("intake")
    g.add_edge("intake", "gate_intake")
    g.add_edge("triage", "gate_triage")
    g.add_edge("extraction", "gate_extraction")
    g.add_edge("drafting", "gate_draft")
    g.add_edge("domain_review", "gate_review")
    g.add_edge("findings", "brief")
    g.add_edge("brief", "gate_approval")
    for gate, producer, nxt in GATES:
        targets = [producer, END] if nxt == FINISH else [producer, nxt]
        g.add_conditional_edges(f"gate_{gate}", _route(gate, producer, nxt), targets)

    return g.compile(checkpointer=checkpointer, interrupt_before=GATE_NODES)
