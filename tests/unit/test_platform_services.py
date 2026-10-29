from pia.audit import GENESIS, AuditLog
from pia.cache import FailOpenCache, InMemoryCache, cache_key
from pia.cost import CostTracker, estimate_usd
from pia.memory.long_term import LongTermMemory
from pia.memory.short_term import SessionMemory
from pia.retrieval.embeddings import HashingEmbedder
from pia.workflow.graph import build_graph


def test_audit_chain_verifies_and_detects_tampering():
    log = AuditLog()
    log.append("alice", "human", "gate.decided", "r1", {"gate": "triage", "passed": True})
    log.append("ai", "ai", "drafts.generated", "r1", {"drafted": 2})
    assert log.verify()
    log._events[0] = type(log._events[0])(**{**log._events[0].__dict__, "actor": "mallory"})
    assert not log.verify()


def test_audit_first_event_chains_from_genesis():
    log = AuditLog()
    e = log.append("alice", "human", "x")
    assert e.prev_hash == GENESIS


def test_cache_expires_and_fails_open():
    now = [0.0]
    cache = InMemoryCache(clock=lambda: now[0])
    cache.set("k", "v", ttl_s=10)
    assert cache.get("k") == "v"
    now[0] = 11
    assert cache.get("k") is None

    class Broken:
        def get(self, key):
            raise ConnectionError

        def set(self, key, value, ttl_s):
            raise ConnectionError

    safe = FailOpenCache(Broken())
    assert safe.get("k") is None
    safe.set("k", "v", 1)


def test_cache_key_separates_teams():
    assert cache_key("qa", "risk", "q") != cache_key("qa", "security", "q")


def test_session_memory_is_per_user_and_redacted():
    cache = InMemoryCache()
    mem = SessionMemory(cache)
    mem.append("alice", "s1", "user", "my email is a@b.com")
    assert "a@b.com" not in mem.recent("alice", "s1")[0]["content"]
    assert mem.recent("bob", "s1") == []


def test_long_term_memory_forget_erases_user_data():
    ltm = LongTermMemory(HashingEmbedder(256))
    ltm.remember("alice", "Prefers concise drafts with citations")
    assert ltm.recall("alice", "concise drafts")
    assert ltm.recall("bob", "concise drafts") == []
    assert ltm.forget("alice") == 1
    assert ltm.recall("alice", "concise drafts") == []


def test_cost_estimate_and_scope_accounting():
    prices = {"m": {"input": 3.0, "output": 15.0}}
    assert estimate_usd(prices, "m", 1_000_000, 0) == 3.0
    tracker = CostTracker(prices, token_budget_per_scope=100)
    tracker.record("s", "m", 40, 10)
    assert tracker.tokens("s") == 50
    assert tracker.usd("s") > 0


def test_graph_compiles_with_human_gates():
    import pytest

    pytest.importorskip("langgraph")
    noop = lambda s: {}  # noqa: E731
    nodes = {n: noop for n in ("intake", "triage", "extraction", "drafting", "domain_review", "findings", "brief")}
    graph = build_graph(nodes)
    names = set(graph.get_graph().nodes)
    assert set(nodes) <= names
    assert {f"gate_{g}" for g in ("intake", "triage", "extraction", "draft", "review", "approval")} <= names


def test_graph_refuses_missing_nodes():
    import pytest

    with pytest.raises(ValueError, match="missing workflow nodes"):
        build_graph({"intake": lambda s: {}})
