import json

import pytest

from pia.agents.change_detection import ChangeDetectionAgent, diff_facts
from pia.agents.decision_brief import DecisionBriefAgent, compute_stats
from pia.agents.domain_review import DomainReviewAgent
from pia.agents.findings import FindingsAgent
from pia.agents.intake import IntakeAgent
from pia.agents.spec_extraction import SpecExtractionAgent
from pia.agents.text_to_sql import TextToSqlAgent
from pia.demo_corpus import DEMO_DOCS
from pia.guardrails.sql import SQLViolation
from pia.llm.client import FakeLLM
from pia.llm.structured import StructuredOutputError
from pia.observability import MetricsRegistry
from pia.rag.ingest import chunks_from_doc
from pia.retrieval.embeddings import HashingEmbedder
from pia.retrieval.index import HybridIndex
from pia.schemas import Principal
from pia.sql_allowlist import SqlAllowlist

SPEC = "Payment preferences are stored in a new database. Data is encrypted at rest with AES-256."
P = Principal(user_id="u", teams=frozenset({"project", "risk", "infosec", "privacy"}))


def fake(payload):
    return FakeLLM(lambda s, u: json.dumps(payload))


@pytest.fixture
def index():
    idx = HybridIndex(HashingEmbedder(256))
    for d in DEMO_DOCS:
        idx.add(chunks_from_doc(d))
    return idx


# Intake
def test_intake_flags_missing_retention_and_region():
    result = IntakeAgent(FakeLLM()).run(review_id="r", request_text="Store personal data for customers.")
    assert "retention period for personal data" in result.missing
    assert "regions where data is stored or processed" in result.missing


def test_intake_rules_cannot_be_removed_by_model():
    llm = fake({"summary": "", "data_types": [], "customer_facing": None, "missing_information": []})
    result = IntakeAgent(llm).run(review_id="r", request_text="Something vague.")
    assert {"summary of the change", "types of data involved", "whether customers are affected"} <= set(result.missing)


# Spec extraction
def test_extraction_keeps_only_quoted_facts():
    llm = fake(
        {
            "facts": [
                {
                    "category": "data_store",
                    "name": "prefs db",
                    "evidence": "Payment preferences are stored in a new database.",
                },
                {"category": "vendor", "name": "Acme", "evidence": "We send data to Acme."},
            ]
        }
    )
    result = SpecExtractionAgent(llm).run(review_id="r", spec_text=SPEC)
    assert [f.name for f in result.facts] == ["prefs db"]
    assert result.dropped_ungrounded == 1


def test_extraction_rejects_unknown_category():
    llm = fake({"facts": [{"category": "made_up", "name": "x", "evidence": "Payment preferences are stored"}]})
    with pytest.raises(StructuredOutputError):
        SpecExtractionAgent(llm).run(review_id="r", spec_text=SPEC)


# Domain review
@pytest.mark.parametrize("domain", ["risk", "infosec", "privacy"])
def test_domain_review_findings_are_candidates_with_support(domain, index):
    result = DomainReviewAgent(domain, FakeLLM()).review(review_id="r", spec_text=SPEC, index=index, principal=P)
    assert result.findings
    for f in result.findings:
        assert f.status == "candidate"
        assert f.sources or f.spec_evidence


def test_domain_review_drops_unsupported_finding(index):
    llm = fake(
        {
            "findings": [
                {"title": "x", "severity": "high", "cited_source_ids": ["nope"], "spec_evidence": "not in spec text"}
            ]
        }
    )
    result = DomainReviewAgent("risk", llm).review(review_id="r", spec_text=SPEC, index=index, principal=P)
    assert result.findings == [] and result.dropped_unsupported == 1


def test_domain_review_never_cites_restricted_sources(index):
    restricted = "restricted-review-2025-009#0"
    llm = fake(
        {"findings": [{"title": "x", "severity": "low", "cited_source_ids": [restricted], "spec_evidence": None}]}
    )
    project_only = Principal(user_id="u", teams=frozenset({"project"}))
    result = DomainReviewAgent("infosec", llm).review(
        review_id="r", spec_text=SPEC, index=index, principal=project_only
    )
    assert result.findings == []


# Findings
def test_findings_remediation_requires_citation(index):
    llm = fake(
        {
            "findings": [
                {
                    "title": "a",
                    "severity": "high",
                    "owner_role": "infosec",
                    "remediation": "Do X.",
                    "remediation_source_ids": ["fake"],
                }
            ]
        }
    )
    out = FindingsAgent(llm).structure(review_id="r", notes="rotation missing", index=index, principal=P)
    assert out[0].remediation is None


def test_findings_structures_notes_with_precedent(index):
    out = FindingsAgent(FakeLLM()).structure(
        review_id="r",
        notes="High: key rotation evidence missing\nEncryption key ownership unclear",
        index=index,
        principal=P,
    )
    assert len(out) == 2
    assert out[0].severity == "high"
    assert all(f.status == "open" for f in out)


def test_fix_verification_needs_exact_quote():
    ok = FindingsAgent(FakeLLM()).verify_fix(
        review_id="r", finding_id="f", finding_text="Encryption at rest is missing", revised_spec=SPEC
    )
    assert ok.verdict == "appears_addressed" and ok.evidence
    bad = FindingsAgent(fake({"addressed": True, "evidence": "invented sentence here", "explanation": ""})).verify_fix(
        review_id="r", finding_id="f", finding_text="x", revised_spec=SPEC
    )
    assert bad.verdict == "not_verified" and bad.evidence is None


# Decision brief
def test_brief_counts_come_from_records():
    drafts = [{"question_id": "q1", "status": "drafted"}, {"question_id": "q2", "status": "needs_input"}]
    findings = [{"finding_id": "f1", "severity": "high", "status": "candidate"}]
    stats = compute_stats(drafts, findings)
    assert stats["questions_needing_input"] == 1 and stats["findings_high"] == 1


def test_brief_replaces_summary_with_invented_numbers():
    llm = fake({"summary": "There are 99 critical problems.", "claims": []})
    brief = DecisionBriefAgent(llm).build(
        review_id="r", drafts=[{"question_id": "q1", "status": "drafted"}], findings=[]
    )
    assert brief.summary_replaced and "99" not in brief.summary


def test_brief_drops_claims_with_unknown_evidence():
    llm = fake(
        {
            "summary": "Fine.",
            "claims": [{"text": "a", "evidence_ids": ["draft:q1"]}, {"text": "b", "evidence_ids": ["ghost"]}],
        }
    )
    brief = DecisionBriefAgent(llm).build(
        review_id="r", drafts=[{"question_id": "q1", "status": "drafted"}], findings=[]
    )
    assert [c.text for c in brief.claims] == ["a"] and brief.dropped_claims == 1


# Change detection
def test_diff_is_by_category_and_normalized_name():
    added, removed = diff_facts(
        [{"category": "data_store", "name": "Prefs  DB"}], [{"category": "data_store", "name": "prefs db"}]
    )
    assert added == [] and removed == []


def test_new_vendor_always_requires_rereview_even_if_model_says_no():
    llm = fake({"rereview_required": False, "reasons": []})
    decision = ChangeDetectionAgent(llm).detect(
        scope="c", approved_facts=[], current_facts=[{"category": "vendor", "name": "Acme", "evidence": "x"}]
    )
    assert decision.rereview_required and decision.source == "rules"


def test_no_change_skips_the_model():
    calls = []
    llm = FakeLLM(lambda s, u: calls.append(1) or "{}")
    facts = [{"category": "control", "name": "x", "evidence": "y"}]
    decision = ChangeDetectionAgent(llm).detect(scope="c", approved_facts=facts, current_facts=facts)
    assert decision.source == "no_change" and calls == []


# Text to SQL
def test_text_to_sql_applies_column_allowlist():
    allow = SqlAllowlist({"reviews": ("review_id", "stage")})
    sql = TextToSqlAgent(fake({"sql": "SELECT stage FROM reviews"})).generate(scope="s", question="q?", allowlist=allow)
    assert "LIMIT" in sql.upper()
    with pytest.raises(SQLViolation):
        TextToSqlAgent(fake({"sql": "SELECT answer FROM reviews"})).generate(scope="s", question="q?", allowlist=allow)


# Metrics
def test_agent_records_latency_and_outcome():
    metrics = MetricsRegistry()
    IntakeAgent(FakeLLM(), metrics=metrics).run(review_id="r", request_text="Store personal data in the EU.")
    assert metrics.counter("agent_calls_total", {"agent": "intake", "outcome": "ok"}) == 1
    assert metrics.samples("agent_latency_seconds")
    assert "agent_latency_seconds" in metrics.render()
