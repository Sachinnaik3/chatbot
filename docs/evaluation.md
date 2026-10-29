# Evaluation

## Offline (release gate)

`make eval` runs in CI with a deterministic fake model. `make eval-stage` runs the same suites on the real model against `thresholds.stage.yaml`.

| Group | Suites | Purpose |
|---|---|---|
| Safety | retrieval access leakage, SQL validator, injection detector, PII redaction | Controls that must be perfect |
| Guard | extraction quote, domain-review support, findings remediation, fix-verification quote, brief numeric grounding, drafting citation | Feed a misbehaving model; the guard must catch it |
| Quality | retrieval recall@5, triage exact match, intake gap recall, extraction category recall, drafting status accuracy, change-detection recall | Agent behavior on golden data |
| Workflow | reached approval, gate bypass blocked rate, audit chain valid | End-to-end control checks |
| Operations | agent latency p50/p95, tokens per full review | Latency and cost budgets |

On the fake model, quality scores test plumbing, not model quality. Real quality numbers come only from `make eval-stage`, with thresholds set from a measured baseline.

**Mutation check.** The gate has been verified by breaking guards on purpose: quote grounding, the access filter, the human-only gate rule, and numeric grounding. Each break fails the gate with a named metric. Repeat this whenever you add a guard.

## Online

- **Shadow mode** (`evals/online/shadow.py`): drafts hidden from reviewers; coverage, overreach, agreement.
- **Reviewer feedback** (`/v1/reviews/{id}/drafts/{q}/feedback`, `/v1/metrics/online`): acceptance, rejection, mean edit ratio. Stores edit ratios, not text.
- **LLM judge** (`evals/online/judge.py`): rubric scoring, trusted only after Cohen's kappa against human labels is acceptable. Recalibrate when it drops.
- **Runtime metrics** (`/metrics`): agent latency quantiles, calls by outcome, tokens, guardrail blocks, HTTP latency by route.

## Golden data

All files in `evals/golden/` are synthetic. Replace them with anonymized past reviews, versioned, with an owner, and add every production miss as a new case.
