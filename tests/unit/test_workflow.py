import pytest

from pia.agents.change_detection import ChangeDetectionAgent
from pia.agents.decision_brief import DecisionBriefAgent
from pia.agents.domain_review import DomainReviewAgent
from pia.agents.drafting import DraftingAgent
from pia.agents.findings import FindingsAgent
from pia.agents.intake import IntakeAgent
from pia.agents.routing import RoutingRules
from pia.agents.spec_extraction import SpecExtractionAgent
from pia.agents.text_to_sql import TextToSqlAgent
from pia.agents.triage import TriageAgent
from pia.audit import AuditLog
from pia.demo_corpus import DEMO_DOCS
from pia.llm.client import FakeLLM
from pia.rag.ingest import chunks_from_doc
from pia.rag.qa import GroundedQA
from pia.retrieval.embeddings import HashingEmbedder
from pia.retrieval.index import HybridIndex
from pia.schemas import Principal
from pia.settings import config_dir
from pia.workflow.nodes import AgentSuite
from pia.workflow.service import (
    Conflict,
    Forbidden,
    ReviewWorkflow,
    WorkflowError,
    build_checkpointer,
    load_gate_policies,
)

ALICE = Principal(user_id="alice", teams=frozenset({"project", "risk"}))
GINA = Principal(user_id="gina", teams=frozenset({"governance"}))
RITA = Principal(user_id="rita", teams=frozenset({"risk", "infosec", "privacy"}))
BOB = Principal(user_id="bob", teams=frozenset({"business_owner"}))
BOT = Principal(user_id="bot", teams=frozenset({"governance"}), is_human=False)


@pytest.fixture
def wf():
    llm = FakeLLM()
    idx = HybridIndex(HashingEmbedder(256))
    for d in DEMO_DOCS:
        idx.add(chunks_from_doc(d))
    suite = AgentSuite(
        IntakeAgent(llm),
        TriageAgent(llm),
        SpecExtractionAgent(llm),
        DraftingAgent(llm),
        {d: DomainReviewAgent(d, llm) for d in ("risk", "infosec", "privacy")},
        FindingsAgent(llm),
        DecisionBriefAgent(llm),
        ChangeDetectionAgent(llm),
        TextToSqlAgent(llm),
        GroundedQA(idx, llm),
    )
    audit = AuditLog()
    flow = ReviewWorkflow(
        suite,
        idx,
        RoutingRules.from_yaml(config_dir() / "routing_rules.yaml"),
        load_gate_policies(config_dir() / "gates.yaml"),
        audit,
        build_checkpointer("memory", ""),
    )
    flow.audit = audit
    return flow


def start(wf, rid="rev-1"):
    return wf.start(
        review_id=rid,
        principal=ALICE,
        request_text="Store customer personal data and payment data in the EU with encryption. Retention is 2 years.",
        spec_text="Payment preferences are stored in a new database. Data is encrypted at rest with AES-256.",
        questions=[{"id": "q1", "text": "How is payment data encrypted at rest?"}],
    )


def advance(wf, rid="rev-1", until="approval"):
    order = [
        ("intake", ALICE),
        ("triage", GINA),
        ("extraction", ALICE),
        ("draft", ALICE),
        ("review", RITA),
        ("approval", BOB),
    ]
    status = None
    for gate, who in order:
        status = wf.decide(review_id=rid, gate=gate, principal=who, passed=True)
        if gate == until:
            break
    return status


def test_review_pauses_at_first_gate(wf):
    status = start(wf)
    assert status["waiting_for_gate"] == "intake"
    assert status["intake"]["summary"]


def test_full_review_reaches_approval_and_audit_verifies(wf):
    start(wf)
    final = advance(wf)
    assert final["stage"] == "approved" and final["waiting_for_gate"] is None
    assert final["facts"] and final["drafts"] and final["findings"] and final["brief"]
    assert len(final["decision_log"]) == 6
    assert wf.audit.verify()


def test_duplicate_review_id_conflicts(wf):
    start(wf)
    with pytest.raises(Conflict):
        start(wf)


def test_ai_principal_cannot_decide(wf):
    start(wf)
    with pytest.raises(Forbidden):
        wf.decide(review_id="rev-1", gate="intake", principal=BOT, passed=True)


def test_wrong_team_cannot_decide(wf):
    start(wf)
    advance(wf, until="intake")
    with pytest.raises(Forbidden):
        wf.decide(review_id="rev-1", gate="triage", principal=ALICE, passed=True)


def test_requester_cannot_approve_own_review(wf):
    alice_owner = Principal(user_id="alice", teams=frozenset({"project", "risk", "business_owner"}))
    wf.start(
        review_id="rev-2",
        principal=alice_owner,
        request_text="Store payment data in the EU. Retention 1 year.",
        spec_text="Payment preferences are stored in a new database.",
        questions=[],
    )
    for gate, who in [
        ("intake", alice_owner),
        ("triage", GINA),
        ("extraction", alice_owner),
        ("draft", alice_owner),
        ("review", RITA),
    ]:
        wf.decide(review_id="rev-2", gate=gate, principal=who, passed=True)
    with pytest.raises(Forbidden):
        wf.decide(review_id="rev-2", gate="approval", principal=alice_owner, passed=True)


def test_out_of_order_and_replayed_decisions_conflict(wf):
    start(wf)
    with pytest.raises(Conflict):
        wf.decide(review_id="rev-1", gate="triage", principal=GINA, passed=True)
    wf.decide(review_id="rev-1", gate="intake", principal=ALICE, passed=True)
    with pytest.raises(Conflict):
        wf.decide(review_id="rev-1", gate="intake", principal=ALICE, passed=True)


def test_returned_gate_reruns_with_correction(wf):
    start(wf)
    advance(wf, until="intake")
    advance_to_extraction = wf.decide(review_id="rev-1", gate="triage", principal=GINA, passed=True)
    assert advance_to_extraction["waiting_for_gate"] == "extraction"
    new_spec = "Payment preferences are stored in a new database. The service sends events to the ledger API."
    status = wf.decide(
        review_id="rev-1", gate="extraction", principal=ALICE, passed=False, updates={"spec_text": new_spec}
    )
    assert status["waiting_for_gate"] == "extraction"
    assert any(f["category"] == "data_flow" for f in status["facts"])


def test_only_allowed_fields_can_be_updated(wf):
    start(wf)
    with pytest.raises(Forbidden):
        wf.decide(review_id="rev-1", gate="intake", principal=ALICE, passed=True, updates={"tracks": []})


def test_governance_can_override_tracks_within_allowed_set(wf):
    start(wf)
    advance(wf, until="intake")
    with pytest.raises(WorkflowError):
        wf.decide(review_id="rev-1", gate="triage", principal=GINA, passed=True, updates={"tracks": ["made_up"]})
    status = wf.decide(
        review_id="rev-1", gate="triage", principal=GINA, passed=True, updates={"tracks": ["infosec_review"]}
    )
    assert status["tracks"] == ["infosec_review"]


def test_rejected_approval_ends_review(wf):
    start(wf)
    advance(wf, until="review")
    final = wf.decide(review_id="rev-1", gate="approval", principal=BOB, passed=False, note="risk too high")
    assert final["stage"] == "rejected" and final["waiting_for_gate"] is None


def test_reviewer_notes_become_structured_findings(wf):
    start(wf)
    advance(wf, until="draft")
    status = wf.decide(
        review_id="rev-1",
        gate="review",
        principal=RITA,
        passed=True,
        updates={"reviewer_notes": "High: missing rotation evidence"},
    )
    assert status["structured_findings"] and status["brief"]["stats"]["findings_high"] >= 1


def test_visibility(wf):
    start(wf)
    assert wf.can_view(ALICE, "rev-1")
    assert wf.can_view(GINA, "rev-1")
    assert not wf.can_view(Principal(user_id="eve", teams=frozenset({"marketing"})), "rev-1")
