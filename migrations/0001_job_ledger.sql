-- Run with:
--   npx wrangler d1 migrations apply smm-agent-db --remote
-- after adding the DB binding in wrangler.jsonc.

CREATE TABLE IF NOT EXISTS job_runs (
    run_id TEXT PRIMARY KEY,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    status TEXT NOT NULL CHECK (status IN ('started', 'succeeded', 'failed')),
    error TEXT
);

CREATE TABLE IF NOT EXISTS post_runs (
    idempotency_key TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    channel_id TEXT NOT NULL,
    text_hash TEXT NOT NULL,
    due_at TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('processing', 'succeeded', 'failed')),
    buffer_post_id TEXT,
    created_at TEXT NOT NULL,
    error TEXT,
    FOREIGN KEY (run_id) REFERENCES job_runs(run_id)
);

CREATE INDEX IF NOT EXISTS idx_post_runs_run_id ON post_runs(run_id);

-- Imported keyword source rows from Google Docs. This table is intentionally
-- not read by the weekly job yet; it is provisioned for a later content-source
-- integration. SQLite/D1 stores the datetime as an ISO-8601 TEXT value.
CREATE TABLE IF NOT EXISTS keywords (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    text TEXT NOT NULL,
    used_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_keywords_used_at ON keywords(used_at);
