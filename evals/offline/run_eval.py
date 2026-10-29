"""Offline evaluation gate.

Three groups of suites:
- Guard suites: misbehaving fake model -> guardrail must catch it. Always fake LLM.
- Safety suites: SQL validator, injection detector, PII redaction, access leakage. No LLM.
- Quality suites: retrieval, triage, intake, extraction, drafting, change detection, workflow.
  Use --llm anthropic in stage to run these against the real model.

Also reports latency (p50/p95 per agent call) and tokens per review.
Exit code 1 if any metric violates the thresholds file.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from evals.offline.guards import run_guard_suites
from evals.offline.metrics import rate, recall_at_k
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
from pia.cost import CostTracker, load_prices
from pia.guardrails.input import redact_pii, scan_input
from pia.guardrails.sql import SQLViolation, validate_sql
from pia.llm.client import FakeLLM, LLMClient
from pia.observability import MetricsRegistry, percentile
from pia.rag.ingest import KnowledgeDoc, chunks_from_doc
from pia.rag.qa import GroundedQA
from pia.retrieval.embeddings import HashingEmbedder
from pia.retrieval.index import HybridIndex
from pia.schemas import Principal, Question
from pia.settings import config_dir

HERE = Path(__file__).resolve().parent
GOLDEN = HERE.parent / "golden"
REPORTS = HERE.parent / "reports"


def _load(name: str) -> list[dict[str, Any]]:
    return [json.loads(line) for line in (GOLDEN / f"{name}.jsonl").read_text().splitlines() if line.strip()]


def _corpus() -> list[KnowledgeDoc]:
    return [
        KnowledgeDoc(d["source_id"], d["source_type"], d["version"], d["owner"], frozenset(d["teams"]), d["text"])
        for d in _load("corpus")
    ]


def _index(corpus: list[KnowledgeDoc]) -> HybridIndex:
    index = HybridIndex(HashingEmbedder(256))
    for doc in corpus:
        index.add(chunks_from_doc(doc))
    return index


# ---------- safety suites ----------
def eval_retrieval(index: HybridIndex) -> dict[str, float]:
    recalls: list[float] = []
    leaks = 0
    for case in _load("retrieval"):
        teams = frozenset(case["teams"])
        hits = index.search(case["query"], teams, k=5)
        leaks += int(any(not (h.chunk.teams & teams) for h in hits))
        if case["expected_source_ids"]:
            recalls.append(recall_at_k([h.chunk.source_id for h in hits], set(case["expected_source_ids"]), k=5))
    return {
        "retrieval.recall_at_5": sum(recalls) / len(recalls) if recalls else 0.0,
        "retrieval.access_leakage": float(leaks),
    }


def eval_sql() -> dict[str, float]:
    blocked = unsafe = passed_safe = safe = 0
    for case in _load("sql"):
        try:
            validate_sql(case["sql"], frozenset(case["allowed_tables"]))
            ok = True
        except SQLViolation:
            ok = False
        if case["expected_safe"]:
            safe += 1
            passed_safe += int(ok)
        else:
            unsafe += 1
            blocked += int(not ok)
    return {"sql.unsafe_blocked_rate": rate(blocked, unsafe), "sql.safe_pass_rate": rate(passed_safe, safe)}


def eval_injection() -> dict[str, float]:
    attacks = benign = caught = false_pos = 0
    for case in _load("injection"):
        flagged = bool(scan_input(case["text"]).injection_hits)
        if case["is_attack"]:
            attacks += 1
            caught += int(flagged)
        else:
            benign += 1
            false_pos += int(flagged)
    return {"injection.detection_rate": rate(caught, attacks), "injection.false_positive_rate": rate(false_pos, benign)}


def eval_pii() -> dict[str, float]:
    cases = _load("pii")
    leaks = sum(any(s in redact_pii(c["text"])[0] for s in c["must_not_appear"]) for c in cases)
    return {"pii.leak_rate": rate(leaks, len(cases))}


# ---------- quality suites ----------
class Harness:
    def __init__(self, llm: LLMClient, corpus: list[KnowledgeDoc]) -> None:
        self.llm = llm
        self.corpus = corpus
        self.metrics = MetricsRegistry()
        self.cost = CostTracker(load_prices(config_dir() / "models.yaml"), token_budget_per_scope=10_000_000)
        self.index = _index(corpus)
        self.rules = RoutingRules.from_yaml(config_dir() / "routing_rules.yaml")

    def agent(self, cls, *args):
        return cls(*args, self.llm, self.cost, self.metrics)


def eval_triage(h: Harness) -> dict[str, float]:
    agent = h.agent(TriageAgent)
    cases = _load("triage")
    exact = sum(
        set(agent.triage(review_id=f"t-{c['id']}", request_text=c["request"], rules=h.rules).tracks)
        == set(c["expected_tracks"])
        for c in cases
    )
    return {"triage.exact_match": rate(exact, len(cases))}


def eval_intake(h: Harness) -> dict[str, float]:
    agent = h.agent(IntakeAgent)
    flagged = expected = wrong = 0
    for c in _load("intake"):
        missing = set(agent.run(review_id=f"i-{c['id']}", request_text=c["request"]).missing)
        expected += len(c["must_flag"])
        flagged += len(set(c["must_flag"]) & missing)
        wrong += len(set(c["must_not_flag"]) & missing)
    return {"intake.gap_recall": rate(flagged, expected), "intake.false_gaps": float(wrong)}


def eval_extraction(h: Harness) -> dict[str, float]:
    agent = h.agent(SpecExtractionAgent)
    found = expected = 0
    for c in _load("extraction"):
        cats = {f.category for f in agent.run(review_id=f"e-{c['id']}", spec_text=c["spec"]).facts}
        expected += len(c["expected_categories"])
        found += len(set(c["expected_categories"]) & cats)
    return {"extraction.category_recall": rate(found, expected)}


def _drafting_responder(behavior: str):
    import re

    src, qre = re.compile(r'<source id="([^"]+)"'), re.compile(r"^- id=([^:]+): ", re.M)

    def respond(system: str, user: str) -> str:
        ids = src.findall(user)
        answers = []
        for qid in qre.findall(user):
            if behavior == "cite_invalid":
                answers.append(
                    {"question_id": qid, "answer": "Claim.", "status": "drafted", "cited_source_ids": ["made-up"]}
                )
            elif behavior == "no_answer":
                answers.append({"question_id": qid, "answer": None, "status": "needs_input", "cited_source_ids": []})
            else:
                answers.append(
                    {"question_id": qid, "answer": "Supported.", "status": "drafted", "cited_source_ids": ids}
                )
        return json.dumps({"answers": answers})

    return respond


def eval_drafting(h: Harness, use_behaviors: bool) -> dict[str, float]:
    ok = total = unsupported = drafted = invalid_cases = invalid_caught = 0
    for case in _load("drafting"):
        llm = FakeLLM(_drafting_responder(case["fake_behavior"])) if use_behaviors else h.llm
        agent = DraftingAgent(llm, h.cost, h.metrics)
        drafts = agent.draft(
            review_id=case["id"],
            questions=[Question(id=q["id"], text=q["text"]) for q in case["questions"]],
            spec_facts=case["spec_facts"],
            index=h.index,
            principal=Principal(user_id="eval", teams=frozenset(case["teams"])),
        )
        expected = {q["id"]: q["expected_status"] for q in case["questions"]}
        for d in drafts:
            total += 1
            ok += int(d.status == expected[d.question_id])
            if d.status == "drafted":
                drafted += 1
                unsupported += int(not d.sources)
        if use_behaviors and case["fake_behavior"] == "cite_invalid":
            invalid_cases += 1
            invalid_caught += int(all(d.status == "needs_input" for d in drafts))
    out = {
        "drafting.status_accuracy": rate(ok, total),
        "drafting.unsupported_claim_rate": rate(unsupported, drafted) if drafted else 0.0,
    }
    if use_behaviors:
        out["drafting.guard_catch_rate"] = rate(invalid_caught, invalid_cases)
    return out


def eval_change(h: Harness) -> dict[str, float]:
    extractor, detector = h.agent(SpecExtractionAgent), h.agent(ChangeDetectionAgent)
    correct = must = caught = 0
    cases = _load("change")
    for c in cases:
        facts = [f.model_dump() for f in extractor.run(review_id=f"c-{c['id']}", spec_text=c["current_spec"]).facts]
        decision = detector.detect(scope=f"c-{c['id']}", approved_facts=c["approved"], current_facts=facts)
        correct += int(decision.rereview_required == c["expected_rereview"])
        if c["expected_rereview"]:
            must += 1
            caught += int(decision.rereview_required)
    return {"change.accuracy": rate(correct, len(cases)), "change.rereview_recall": rate(caught, must)}


def eval_workflow(h: Harness) -> dict[str, float]:
    """End to end: a review must reach approval only through every human gate, and
    AI or requester principals must be refused where policy says so."""
    from pia.workflow.nodes import AgentSuite
    from pia.workflow.service import Forbidden, ReviewWorkflow, WorkflowError, build_checkpointer, load_gate_policies

    suite = AgentSuite(
        intake=h.agent(IntakeAgent),
        triage=h.agent(TriageAgent),
        spec_extraction=h.agent(SpecExtractionAgent),
        drafting=DraftingAgent(h.llm, h.cost, h.metrics),
        domain_reviews={d: DomainReviewAgent(d, h.llm, h.cost, h.metrics) for d in ("risk", "infosec", "privacy")},
        findings=h.agent(FindingsAgent),
        brief=h.agent(DecisionBriefAgent),
        change_detection=h.agent(ChangeDetectionAgent),
        text_to_sql=h.agent(TextToSqlAgent),
        qa=GroundedQA(h.index, h.llm, h.cost, metrics=h.metrics),
    )
    audit = AuditLog()
    wf = ReviewWorkflow(
        suite,
        h.index,
        h.rules,
        load_gate_policies(config_dir() / "gates.yaml"),
        audit,
        build_checkpointer("memory", ""),
    )
    alice = Principal(user_id="alice", teams=frozenset({"project", "risk", "business_owner"}))
    bot = Principal(user_id="bot", teams=frozenset({"governance"}), is_human=False)
    gina = Principal(user_id="gina", teams=frozenset({"governance"}))
    rita = Principal(user_id="rita", teams=frozenset({"risk", "infosec", "privacy"}))
    bob = Principal(user_id="bob", teams=frozenset({"business_owner"}))
    wf.start(
        review_id="wf-1",
        principal=alice,
        request_text="Store customer personal data for payment preferences in the EU with encryption.",
        spec_text="Payment preferences are stored in a new database. Data is encrypted at rest with AES-256.",
        questions=[{"id": "q1", "text": "How is payment data encrypted at rest?"}],
    )
    bypass_blocked = 0
    attempts = 0
    for gate, who in [
        ("intake", alice),
        ("triage", gina),
        ("extraction", alice),
        ("draft", alice),
        ("review", rita),
        ("approval", bob),
    ]:
        # A bot tries every gate first; the requester tries the separation-of-duties gates.
        for intruder in [bot, *([alice] if gate in {"review", "approval"} else [])]:
            attempts += 1
            try:
                wf.decide(review_id="wf-1", gate=gate, principal=intruder, passed=True)
            except Forbidden:
                bypass_blocked += 1
            except WorkflowError:
                pass  # an earlier bypass already moved the review; counted as not blocked
        with contextlib.suppress(WorkflowError):
            wf.decide(review_id="wf-1", gate=gate, principal=who, passed=True)
    final = wf.status("wf-1")
    return {
        "workflow.reached_approval": float(final["stage"] == "approved"),
        "workflow.gate_bypass_blocked_rate": rate(bypass_blocked, attempts),
        "workflow.audit_chain_valid": float(audit.verify()),
    }


def eval_ops(h: Harness) -> dict[str, float]:
    latencies = h.metrics.samples("agent_latency_seconds")
    review_scopes = [s for s in ("review:wf-1",)]
    return {
        "latency.agent_p50_s": percentile(latencies, 0.5),
        "latency.agent_p95_s": percentile(latencies, 0.95),
        "cost.tokens_per_full_review": float(sum(h.cost.tokens(s) for s in review_scopes)),
    }


def check(metrics: dict[str, float], thresholds: dict[str, dict[str, Any]]) -> list[str]:
    ops = {"min": lambda a, v: a >= v, "max": lambda a, v: a <= v, "eq": lambda a, v: a == v}
    failures = []
    for name, rule in thresholds.items():
        if name not in metrics:
            failures.append(f"{name}: metric missing")
        elif not ops[rule["op"]](metrics[name], rule["value"]):
            failures.append(f"{name}: {metrics[name]:.4f} violates {rule['op']} {rule['value']}")
    return failures


def _build_llm(kind: str) -> LLMClient:
    if kind == "fake":
        return FakeLLM()
    from pia.llm.client import build_llm
    from pia.settings import get_settings

    return build_llm(get_settings())


def run_all(llm_kind: str = "fake", thresholds_path: Path | None = None) -> tuple[dict[str, float], list[str]]:
    corpus = _corpus()
    h = Harness(_build_llm(llm_kind), corpus)
    metrics: dict[str, float] = {}
    metrics.update(eval_retrieval(h.index))
    metrics.update(eval_sql())
    metrics.update(eval_injection())
    metrics.update(eval_pii())
    metrics.update(run_guard_suites(h.index))
    metrics.update(eval_triage(h))
    metrics.update(eval_intake(h))
    metrics.update(eval_extraction(h))
    metrics.update(eval_drafting(h, use_behaviors=llm_kind == "fake"))
    metrics.update(eval_change(h))
    metrics.update(eval_workflow(h))
    metrics.update(eval_ops(h))
    path = thresholds_path or HERE / ("thresholds.yaml" if llm_kind == "fake" else "thresholds.stage.yaml")
    return metrics, check(metrics, yaml.safe_load(path.read_text()))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--llm", choices=["fake", "anthropic"], default="fake")
    parser.add_argument("--thresholds", type=Path, default=None)
    args = parser.parse_args()
    metrics, failures = run_all(args.llm, args.thresholds)
    REPORTS.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    report = {"run_at": stamp, "llm": args.llm, "metrics": metrics, "failures": failures, "passed": not failures}
    (REPORTS / f"eval-{args.llm}-{stamp}.json").write_text(json.dumps(report, indent=2))
    for name, value in sorted(metrics.items()):
        print(f"{name:42s} {value:.4f}")
    if failures:
        print("\nRELEASE GATE FAILED:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("\nrelease gate passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
