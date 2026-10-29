# Runbook: suspected prompt injection

Signal: `security.injection_flagged` audit events or `guardrail_flagged_total{guard="injection"}` spike.
1. Pull the review's audit trail (`/v1/audit/reviews/{id}`) and the flagged document.
2. Check whether any draft or finding from that review was accepted; re-review those by hand.
3. Add the pattern to `evals/golden/injection.jsonl` and, if needed, to `guardrails/input.py`.
4. Notify security. Injection detection is a signal; the citation and quote checks are the controls that stop impact.
