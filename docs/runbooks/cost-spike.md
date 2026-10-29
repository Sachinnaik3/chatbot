# Runbook: cost spike

Signal: `agent_tokens_total` jumps; 429 `budget_exceeded` errors.
1. Find the agent and scope from `/metrics` and `/v1/costs/review/{id}`.
2. Common causes: very long specs, retries from invalid output, a prompt change. Check the eval report for token changes.
3. Budgets are per scope (`review_token_budget`); raise only with a recorded reason.
