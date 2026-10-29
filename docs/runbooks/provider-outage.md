# Runbook: LLM provider outage

Signal: `agent_calls_total{outcome="error"}` rising; 502 `model_output_invalid` or timeouts.
1. Confirm on the provider status page.
2. Reviews continue manually: humans can still decide gates; AI steps fail without changing state.
3. Do not switch to an unevaluated model. A fallback model must pass `make eval-stage` first.
4. After recovery, resume affected reviews by having the gate owner return the gate, which reruns the step.
