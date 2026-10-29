-- Initial schema. Runs once when the database container starts.
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS reviews (
    review_id   VARCHAR(64) PRIMARY KEY,
    project_id  VARCHAR(64) NOT NULL,
    stage       VARCHAR(32) NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS reviews_project_idx ON reviews (project_id);

CREATE TABLE IF NOT EXISTS drafts (
    id              BIGSERIAL PRIMARY KEY,
    review_id       VARCHAR(64) NOT NULL REFERENCES reviews (review_id),
    question_id     VARCHAR(64) NOT NULL,
    answer          TEXT,
    status          VARCHAR(16) NOT NULL CHECK (status IN ('drafted', 'needs_input')),
    model           VARCHAR(64) NOT NULL,
    prompt_version  INTEGER NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS drafts_review_idx ON drafts (review_id);

-- Hash-chained, append-only audit log.
CREATE TABLE IF NOT EXISTS audit_events (
    seq         BIGINT PRIMARY KEY,
    ts          VARCHAR(40) NOT NULL,  -- ISO-8601 text, hashed exactly as stored
    actor       VARCHAR(128) NOT NULL,
    actor_type  VARCHAR(16) NOT NULL CHECK (actor_type IN ('human', 'ai', 'system')),
    action      VARCHAR(64) NOT NULL,
    review_id   VARCHAR(64),
    payload     JSONB NOT NULL DEFAULT '{}'::jsonb,
    prev_hash   VARCHAR(64) NOT NULL,
    hash        VARCHAR(64) NOT NULL UNIQUE
);
CREATE INDEX IF NOT EXISTS audit_review_idx ON audit_events (review_id);

CREATE TABLE IF NOT EXISTS draft_feedback (
    id          BIGSERIAL PRIMARY KEY,
    review_id   VARCHAR(64) NOT NULL,
    question_id VARCHAR(64) NOT NULL,
    action      VARCHAR(16) NOT NULL CHECK (action IN ('accepted', 'edited', 'rejected')),
    edit_ratio  DOUBLE PRECISION,
    actor       VARCHAR(128) NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS feedback_review_idx ON draft_feedback (review_id);

CREATE TABLE IF NOT EXISTS knowledge_chunks (
    chunk_id    VARCHAR(128) PRIMARY KEY,
    source_id   VARCHAR(128) NOT NULL,
    source_type VARCHAR(32) NOT NULL,
    version     VARCHAR(32) NOT NULL,
    owner       VARCHAR(128) NOT NULL,
    text        TEXT NOT NULL,
    teams       TEXT[] NOT NULL,
    retired     BOOLEAN NOT NULL DEFAULT false,
    embedding   vector(256) NOT NULL
);
CREATE INDEX IF NOT EXISTS knowledge_source_idx ON knowledge_chunks (source_id);
CREATE INDEX IF NOT EXISTS knowledge_teams_gin ON knowledge_chunks USING gin (teams);
CREATE INDEX IF NOT EXISTS knowledge_embedding_hnsw
    ON knowledge_chunks USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS knowledge_text_fts
    ON knowledge_chunks USING gin (to_tsvector('english', text));

-- Enforce append-only at the database level. The application role must NOT own these tables,
-- otherwise the owner can still alter them. Grant the app role INSERT and SELECT only.
REVOKE UPDATE, DELETE, TRUNCATE ON audit_events FROM PUBLIC;

-- Read-only role for text-to-SQL. Row-level security restricts rows by team.
DO $$ BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'pia_sql_readonly') THEN
        CREATE ROLE pia_sql_readonly NOLOGIN;
    END IF;
END $$;
-- Column-level grants mirror configs/sql_allowlist.yaml. Content columns are not granted.
GRANT SELECT (review_id, project_id, stage, created_at) ON reviews TO pia_sql_readonly;
GRANT SELECT (id, review_id, question_id, status, model, prompt_version, created_at) ON drafts TO pia_sql_readonly;
-- The application login role must be a member of pia_sql_readonly to SET ROLE to it:
--   GRANT pia_sql_readonly TO pia_app;
