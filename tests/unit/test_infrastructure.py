import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from sqlalchemy import text

from evals.online.judge import AnswerJudge, cohens_kappa
from evals.online.shadow import ShadowPair, shadow_metrics
from pia.agents.text_to_sql import ReadOnlySqlExecutor
from pia.api.auth import OIDCVerifier
from pia.db.audit_store import SqlAuditLog
from pia.db.models import AuditRow, Base
from pia.db.session import make_session_factory
from pia.llm.client import FakeLLM
from pia.ratelimit import TokenBucketLimiter


# OIDC
@pytest.fixture(scope="module")
def keypair():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return key, key.public_key()


def _token(key, **overrides):
    now = int(time.time())
    claims = {
        "iss": "https://idp.example",
        "aud": "pia",
        "sub": "user-1",
        "iat": now,
        "exp": now + 300,
        "groups": ["risk"],
        "principal_type": "human",
    }
    claims.update(overrides)
    return jwt.encode({k: v for k, v in claims.items() if v is not None}, key, algorithm="RS256")


def _verifier(public):
    return OIDCVerifier(issuer="https://idp.example", audience="pia", key_resolver=lambda t: public)


def test_oidc_valid_token(keypair):
    priv, pub = keypair
    p = _verifier(pub).verify(_token(priv))
    assert p.user_id == "user-1" and p.teams == frozenset({"risk"}) and p.is_human


@pytest.mark.parametrize(
    "overrides",
    [{"aud": "other"}, {"iss": "https://evil"}, {"exp": int(time.time()) - 3600}, {"sub": None}],
)
def test_oidc_rejects_bad_claims(keypair, overrides):
    priv, pub = keypair
    with pytest.raises(jwt.PyJWTError):
        _verifier(pub).verify(_token(priv, **overrides))


def test_oidc_rejects_wrong_signing_key(keypair):
    _, pub = keypair
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    with pytest.raises(jwt.PyJWTError):
        _verifier(pub).verify(_token(other))


def test_oidc_principal_defaults_to_non_human(keypair):
    priv, pub = keypair
    assert not _verifier(pub).verify(_token(priv, principal_type=None)).is_human


# Rate limiting
def test_token_bucket_limits_and_refills():
    now = [0.0]
    limiter = TokenBucketLimiter(per_minute=60, burst=2, clock=lambda: now[0])
    assert limiter.allow("a") and limiter.allow("a") and not limiter.allow("a")
    assert limiter.allow("b")
    now[0] = 1.0
    assert limiter.allow("a")


# Database-backed audit and SQL executor (SQLite stands in for Postgres here)
@pytest.fixture
def sf(tmp_path):
    factory = make_session_factory(f"sqlite:///{tmp_path}/t.db")
    Base.metadata.create_all(factory.kw["bind"])
    return factory


def test_sql_audit_log_chains_and_detects_tampering(sf):
    log = SqlAuditLog(sf)
    log.append("alice", "human", "gate.decided", "r1", {"passed": True})
    log.append("wf", "system", "review.stage", "r1", {"stage": "approved"})
    assert log.verify() and len(log.events("r1")) == 2
    with sf() as s, s.begin():
        s.get(AuditRow, 1).actor = "mallory"
    assert not log.verify()


def test_readonly_executor_runs_validated_sql(sf):
    with sf() as s, s.begin():
        s.execute(text("INSERT INTO reviews (review_id, project_id, stage) VALUES ('r1', 'p1', 'approved')"))
    rows = ReadOnlySqlExecutor(sf, role=None, max_rows=10).run("SELECT review_id, stage FROM reviews LIMIT 10")
    assert rows == [{"review_id": "r1", "stage": "approved"}]


def test_executor_rejects_unsafe_role_name(sf):
    with pytest.raises(ValueError):
        ReadOnlySqlExecutor(sf, role="x; DROP TABLE reviews")


# Online evals
def test_shadow_metrics():
    m = shadow_metrics(
        [ShadowPair("q1", "drafted", True), ShadowPair("q2", "needs_input", True), ShadowPair("q3", "drafted", False)]
    )
    assert m["shadow.coverage"] == 0.5 and m["shadow.overreach_rate"] == 0.5


def test_cohens_kappa():
    assert cohens_kappa([1, 2, 3, 4], [1, 2, 3, 4]) == 1.0
    assert cohens_kappa([1, 1, 2, 2], [2, 2, 1, 1]) < 0


def test_judge_parses_score():
    assert AnswerJudge(FakeLLM()).score(question="q", answer="a", sources="s").score == 4
