"""Composition root: builds every dependency once at startup. Nothing else constructs providers.

Fail-closed rules:
- stage and prod refuse the fake LLM and in-memory persistence.
- prod refuses API keys; it accepts only OIDC bearer tokens.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pia.agents.change_detection import ChangeDetectionAgent
from pia.agents.decision_brief import DecisionBriefAgent
from pia.agents.domain_review import DomainReviewAgent
from pia.agents.drafting import DraftingAgent
from pia.agents.findings import FindingsAgent
from pia.agents.intake import IntakeAgent
from pia.agents.routing import RoutingRules
from pia.agents.spec_extraction import SpecExtractionAgent
from pia.agents.text_to_sql import ReadOnlySqlExecutor, TextToSqlAgent
from pia.agents.triage import TriageAgent
from pia.api.auth import OIDCVerifier, parse_api_keys
from pia.audit import AuditLog
from pia.cache import Cache, build_cache
from pia.cost import CostTracker, load_prices
from pia.demo_corpus import DEMO_DOCS
from pia.feedback_store import InMemoryFeedbackStore
from pia.llm.client import LLMClient, build_llm
from pia.memory.long_term import LongTermMemory
from pia.memory.short_term import SessionMemory
from pia.observability import MetricsRegistry
from pia.rag.ingest import chunks_from_doc
from pia.rag.qa import GroundedQA
from pia.ratelimit import TokenBucketLimiter
from pia.retrieval.embeddings import HashingEmbedder
from pia.retrieval.index import HybridIndex
from pia.schemas import Principal
from pia.settings import Settings, config_dir, get_settings
from pia.sql_allowlist import SqlAllowlist
from pia.workflow.nodes import AgentSuite
from pia.workflow.service import ReviewWorkflow, build_checkpointer, load_gate_policies


@dataclass
class AppState:
    settings: Settings
    llm: LLMClient
    index: HybridIndex
    cache: Cache
    cost: CostTracker
    audit: Any
    metrics: MetricsRegistry
    limiter: TokenBucketLimiter
    memory: SessionMemory
    long_term: LongTermMemory
    agents: AgentSuite
    workflow: ReviewWorkflow
    rules: RoutingRules
    sql_allowlist: SqlAllowlist
    sql_executor: ReadOnlySqlExecutor | None
    feedback: InMemoryFeedbackStore
    principals: dict[str, Principal]
    oidc: OIDCVerifier | None

    # Backwards-compatible accessors used by existing routes
    @property
    def qa(self) -> GroundedQA:
        return self.agents.qa

    @property
    def drafting(self) -> DraftingAgent:
        return self.agents.drafting


def _check_environment(settings: Settings) -> None:
    if settings.env in {"stage", "prod"} and settings.persistence != "postgres":
        raise RuntimeError(f"{settings.env} requires persistence=postgres")


def build_state(settings: Settings | None = None) -> AppState:
    settings = settings or get_settings()
    _check_environment(settings)
    llm = build_llm(settings)
    metrics = MetricsRegistry()
    embedder = HashingEmbedder(settings.embedding_dim)
    index = HybridIndex(embedder)
    for doc in DEMO_DOCS:
        index.add(chunks_from_doc(doc))

    cache = build_cache(settings.redis_url)
    cost = CostTracker(load_prices(config_dir() / "models.yaml"), settings.review_token_budget)
    rules = RoutingRules.from_yaml(config_dir() / "routing_rules.yaml")

    session_factory = None
    if settings.persistence == "postgres":
        from pia.db.audit_store import SqlAuditLog
        from pia.db.session import make_session_factory

        session_factory = make_session_factory(settings.database_url)
        audit: Any = SqlAuditLog(session_factory)
    else:
        audit = AuditLog()

    agents = AgentSuite(
        intake=IntakeAgent(llm, cost, metrics),
        triage=TriageAgent(llm, cost, metrics),
        spec_extraction=SpecExtractionAgent(llm, cost, metrics),
        drafting=DraftingAgent(llm, cost, metrics),
        domain_reviews={d: DomainReviewAgent(d, llm, cost, metrics) for d in ("risk", "infosec", "privacy")},
        findings=FindingsAgent(llm, cost, metrics),
        brief=DecisionBriefAgent(llm, cost, metrics),
        change_detection=ChangeDetectionAgent(llm, cost, metrics),
        text_to_sql=TextToSqlAgent(llm, cost, metrics),
        qa=GroundedQA(index, llm, cost, metrics=metrics),
    )
    workflow = ReviewWorkflow(
        agents,
        index,
        rules,
        load_gate_policies(config_dir() / "gates.yaml"),
        audit,
        build_checkpointer(settings.persistence, settings.database_url),
    )

    oidc = None
    if settings.oidc_issuer and settings.oidc_audience and settings.oidc_jwks_url:
        oidc = OIDCVerifier(
            issuer=settings.oidc_issuer,
            audience=settings.oidc_audience,
            jwks_url=settings.oidc_jwks_url,
            teams_claim=settings.oidc_teams_claim,
        )

    return AppState(
        settings=settings,
        llm=llm,
        index=index,
        cache=cache,
        cost=cost,
        audit=audit,
        metrics=metrics,
        limiter=TokenBucketLimiter(settings.rate_limit_per_minute),
        memory=SessionMemory(cache),
        long_term=LongTermMemory(embedder),
        agents=agents,
        workflow=workflow,
        rules=rules,
        sql_allowlist=SqlAllowlist.from_yaml(config_dir() / "sql_allowlist.yaml"),
        sql_executor=(
            ReadOnlySqlExecutor(session_factory, role=settings.sql_readonly_role) if session_factory else None
        ),
        feedback=InMemoryFeedbackStore(),
        principals={} if settings.env == "prod" else parse_api_keys(settings.api_keys),
        oidc=oidc,
    )
