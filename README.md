# PIA AI Platform

AI assistant for Project Impact Assessment (PIA) reviews in a payments company. Twelve agents draft, extract, pre-screen, structure, and brief. Humans decide every gate. Grounding is enforced in code, and every decision is audited in a hash chain.

## Quick start

    python -m venv .venv && source .venv/bin/activate
    make install
    make test        # unit and integration tests
    make eval        # offline release gate (fake model, deterministic)
    make run         # http://localhost:8000/docs in dev

Docker: `cp .env.example .env && make up`, then `curl localhost:8000/readyz`.

## Try a full review (dev)

    H='X-API-Key: dev-alice-key'
    curl -s -XPOST localhost:8000/v1/reviews -H "$H" -H 'Content-Type: application/json' -d '{
      "review_id": "rev-1",
      "request_text": "Store customer personal data for payment preferences in the EU. Retention is 2 years.",
      "spec_text": "Payment preferences are stored in a new database. Data is encrypted at rest with AES-256.",
      "questions": [{"id": "q1", "text": "How is payment data encrypted at rest?"}]}'
    # Then decide gates in order with the right people:
    # intake: alice, triage: gina, extraction: alice, draft: alice, review: rita, approval: bob
    curl -s -XPOST localhost:8000/v1/reviews/rev-1/gates/intake -H "$H" -H 'Content-Type: application/json' -d '{"passed": true}'

## What is in it

| Area | Where | Notes |
|---|---|---|
| 12 agents | `src/pia/agents/`, `src/pia/rag/qa.py` | See `docs/agents.md` |
| Review workflow | `src/pia/workflow/` | LangGraph, six human gates, separation of duties, returns rerun steps |
| RAG | `src/pia/rag/`, `src/pia/retrieval/` | Chunking, hybrid BM25 + vector with RRF, access filter before scoring, pgvector adapter with tsvector + cosine |
| Memory | `src/pia/memory/` | Short-term per-user sessions (TTL, PII redacted); long-term per-user memory with erasure |
| Guardrails | `src/pia/guardrails/` | Injection signals, PII and Luhn card redaction, citation and quote grounding, numeric grounding, SQL validator |
| Prompts | `src/pia/prompts/templates/` | Versioned files; untrusted content wrapped and escaped |
| API | `src/pia/api/` | FastAPI routers; OIDC or dev API keys; rate limiting; security headers; metrics |
| Data | `src/pia/db/`, `migrations/` | Postgres + pgvector schema, append-only audit, column-level read-only SQL role |
| Evals | `evals/` | Offline gate (safety, guard, quality, workflow, latency, cost) and online (shadow, feedback, judge); see `docs/evaluation.md` |
| Deploy | `Dockerfile`, `docker-compose.yml`, `deploy/k8s/` | Non-root image; kustomize base + dev/stage/prod overlays; network policy, HPA, PDB |
| CI/CD | `.github/workflows/` | Lint, tests, eval gate, dependency audit, secret scan; stage eval on real model; manual prod approval |
| Decisions | `docs/adr/` | Seven ADRs |
| Operations | `docs/runbooks/` | Provider outage, injection incident, bad knowledge item, cost spike |

## Environments

| Env | LLM | Persistence | Auth | Startup checks |
|---|---|---|---|---|
| dev | fake (deterministic) | in-memory | API keys | none |
| stage | anthropic | Postgres (audit, checkpoints) | OIDC (API keys allowed for testing) | refuses fake LLM and in-memory persistence |
| prod | anthropic | Postgres | OIDC only | refuses fake LLM, in-memory persistence, and API keys |

Non-secret settings: `configs/`. Secrets: environment variables only. An environment variable overrides YAML.

## Verified here vs not

Verified in this repository: 99 tests, the offline gate, a mutation check of four guards, lint, and a clean-venv install of the built wheel.

Not verified here (no Postgres, Redis, Docker, cluster, or model API in the build environment): the Postgres checkpointer, pgvector queries, the Docker build, Kubernetes manifests beyond YAML parsing, and real model quality. Run `make up`, `make eval-stage`, and a stage deploy before relying on them.

Before production also: replace the synthetic golden sets and demo corpus with anonymized real data; load the knowledge base into `knowledge_chunks` with a real embedding model; set real eval thresholds from a measured baseline; complete the PIA of this system itself.
