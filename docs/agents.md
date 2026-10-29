# Agents

Twelve agents, one shared contract (`src/pia/agents/base.py`): versioned prompt, typed output, token budget, cost and latency metrics. No agent can change review status, write audit events, or pass a gate.

| # | Agent | File | Stage | Grounding rule enforced in code | Human checkpoint |
|---|---|---|---|---|---|
| 1 | Intake | agents/intake.py | Intake | Deterministic completeness rules are the floor; the model can add gaps, never remove them | Requester (intake gate) |
| 2 | Triage | agents/triage.py | Triage | Keyword routing rules are the floor; unknown tracks are rejected and escalated | Governance (triage gate) |
| 3 | Spec extraction | agents/spec_extraction.py | Documentation | Every fact must quote the spec exactly; others are dropped and counted | Architect or project (extraction gate) |
| 4 | Drafting | agents/drafting.py | Documentation | A draft must cite a source retrieved for that question and visible to the requester | Project team (draft gate) |
| 5 | Risk review | agents/domain_review.py | Review | Finding needs a valid citation or an exact spec quote; starts as candidate | Risk reviewer (review gate) |
| 6 | Infosec review | agents/domain_review.py | Review | Same as risk | Infosec reviewer |
| 7 | Privacy review | agents/domain_review.py | Review | Same as risk | Privacy reviewer |
| 8 | Findings | agents/findings.py | Remediation | Remediation kept only with a cited precedent; fix verification needs an exact quote; never closes findings | Reviewer |
| 9 | Decision brief | agents/decision_brief.py | Approval | Counts computed by code; summaries with invented numbers are replaced; claims need real item ids | Approver (approval gate) |
| 10 | Change detection | agents/change_detection.py | Post-launch | Diff computed by code; material additions and removed controls always require re-review | Governance |
| 11 | Text-to-SQL | agents/text_to_sql.py | Any | Single SELECT, allowlisted tables and columns, denied functions, row cap; read-only transaction and role | Asker sees the SQL |
| 12 | Grounded Q&A | rag/qa.py | Any | Answers only with citations to retrieved, accessible sources | Asker |

## Workflow

`src/pia/workflow/graph.py` wires agents 1 to 9 into one LangGraph review with six human gates:

    intake -> [intake] -> triage -> [triage] -> extraction -> [extraction] -> drafting -> [draft]
    -> domain review -> [review] -> findings -> brief -> [approval] -> approved | rejected

Gate rules (`configs/gates.yaml`, enforced in `workflow/service.py`): humans only; configured teams only; separation of duties at review and approval; decisions accepted only for the gate the review is waiting at; only allowed fields editable per gate; every decision audited. A returned gate reruns the step that produced the work.

## Adding an agent

1. Add `prompts/templates/<name>.v1.md` (system block, `---`, user block).
2. Subclass `Agent`, define a Pydantic output model, and enforce grounding in code after `_invoke`.
3. Add a guard suite in `evals/offline/guards.py` that feeds a misbehaving model and checks the guard.
4. Add a quality suite and golden data, then thresholds in both thresholds files.
5. Run a mutation check: break your guard and confirm the eval gate fails.
