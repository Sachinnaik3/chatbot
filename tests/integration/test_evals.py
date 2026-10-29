from evals.offline.run_eval import run_all


def test_offline_release_gate_passes():
    metrics, failures = run_all("fake")
    assert failures == [], failures
    assert metrics["retrieval.access_leakage"] == 0
    assert metrics["workflow.gate_bypass_blocked_rate"] == 1.0
