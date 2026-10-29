import json

from pydantic import BaseModel

from pia.agents.drafting import DraftingAgent
from pia.agents.routing import RoutingRules
from pia.agents.triage import TriageAgent
from pia.cost import BudgetExceeded, CostTracker, load_prices
from pia.demo_corpus import DEMO_DOCS
from pia.llm.client import FakeLLM
from pia.llm.structured import StructuredOutputError, call_json
from pia.rag.ingest import chunks_from_doc
from pia.retrieval.embeddings import HashingEmbedder
from pia.retrieval.index import HybridIndex
from pia.schemas import Principal, Question
from pia.settings import config_dir


def _index() -> HybridIndex:
    idx = HybridIndex(HashingEmbedder(256))
    for doc in DEMO_DOCS:
        idx.add(chunks_from_doc(doc))
    return idx


def _cost(budget: int = 1_000_000) -> CostTracker:
    return CostTracker(load_prices(config_dir() / "models.yaml"), budget)


def test_drafting_produces_cited_drafts():
    agent = DraftingAgent(FakeLLM(), _cost())
    principal = Principal(user_id="alice", teams=frozenset({"project", "risk", "infosec"}))
    drafts = agent.draft(
        review_id="r1",
        questions=[Question(id="q1", text="How is payment data encrypted at rest?")],
        spec_facts="Payment data is stored encrypted.",
        index=_index(),
        principal=principal,
    )
    assert drafts[0].status == "drafted"
    assert drafts[0].sources


def test_drafting_downgrades_invented_citations():
    def bad(system, user):
        return json.dumps(
            {
                "answers": [
                    {
                        "question_id": "q1",
                        "answer": "x",
                        "status": "drafted",
                        "cited_source_ids": ["fake-1"],
                    }
                ]
            }
        )

    agent = DraftingAgent(FakeLLM(bad), _cost())
    drafts = agent.draft(
        review_id="r2",
        questions=[Question(id="q1", text="How is payment data encrypted at rest?")],
        spec_facts="x",
        index=_index(),
        principal=Principal(user_id="alice", teams=frozenset({"project"})),
    )
    assert drafts[0].status == "needs_input"
    assert drafts[0].answer is None
    assert drafts[0].sources == []


def test_drafting_never_cites_sources_the_user_cannot_see():
    agent = DraftingAgent(FakeLLM(), _cost())
    drafts = agent.draft(
        review_id="r3",
        questions=[Question(id="q1", text="incident response exercise")],
        spec_facts="x",
        index=_index(),
        principal=Principal(user_id="bob", teams=frozenset({"project"})),
    )
    cited = {s.source_id.split("#")[0] for d in drafts for s in d.sources}
    assert "restricted-review-2025-009" not in cited


def test_triage_rules_are_a_floor_and_unknown_tracks_escalate():
    def proposes_unknown(system, user):
        return json.dumps({"tracks": [{"track": "made_up_track", "reason": "x"}]})

    rules = RoutingRules.from_yaml(config_dir() / "routing_rules.yaml")
    result = TriageAgent(FakeLLM(proposes_unknown), _cost()).triage(
        review_id="r4", request_text="Stores customer data and a payment ledger.", rules=rules
    )
    assert "privacy_review" in result.tracks and "risk_review" in result.tracks
    assert result.needs_governance is True
    assert result.rejected_proposals == ["made_up_track"]


def test_budget_blocks_before_call():
    cost = _cost(budget=1)
    cost.record("review:r5", "fake-1", 10, 10)
    agent = DraftingAgent(FakeLLM(), cost)
    try:
        agent.draft(
            review_id="r5",
            questions=[Question(id="q1", text="encrypted at rest")],
            spec_facts="x",
            index=_index(),
            principal=Principal(user_id="alice", teams=frozenset({"project"})),
        )
        raise AssertionError("expected BudgetExceeded")
    except BudgetExceeded:
        pass


class _Out(BaseModel):
    value: int


def test_structured_output_retries_then_fails_closed():
    calls = []

    def responder(system, user):
        calls.append(user)
        return "not json"

    try:
        call_json(FakeLLM(responder), "sys", "user", _Out, max_attempts=2)
        raise AssertionError("expected StructuredOutputError")
    except StructuredOutputError:
        pass
    assert len(calls) == 2
    assert "invalid" in calls[1]


def test_structured_output_accepts_fenced_json():
    def responder(system, user):
        return '```json\n{"value": 7}\n```'

    out, _ = call_json(FakeLLM(responder), "sys", "user", _Out)
    assert out.value == 7
