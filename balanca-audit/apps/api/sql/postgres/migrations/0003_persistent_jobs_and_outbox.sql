CREATE TABLE IF NOT EXISTS background_jobs (
  id text PRIMARY KEY,
  kind text NOT NULL,
  dedupe_key text NOT NULL,
  payload_json jsonb NOT NULL DEFAULT '{}'::jsonb,
  status text NOT NULL DEFAULT 'QUEUED',
  attempt_count integer NOT NULL DEFAULT 0,
  max_attempts integer NOT NULL DEFAULT 5,
  available_at timestamptz NOT NULL DEFAULT now(),
  lease_owner text,
  lease_expires_at timestamptz,
  progress_percent integer NOT NULL DEFAULT 0,
  progress_stage text NOT NULL DEFAULT 'queued',
  progress_message text NOT NULL DEFAULT 'Aguardando processamento.',
  last_error text,
  started_at timestamptz,
  finished_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_background_jobs_claim
  ON background_jobs(kind, status, available_at, lease_expires_at);

CREATE INDEX IF NOT EXISTS idx_background_jobs_dedupe_history
  ON background_jobs(kind, dedupe_key, created_at DESC);

CREATE UNIQUE INDEX IF NOT EXISTS idx_background_jobs_active_dedupe
  ON background_jobs(kind, dedupe_key)
  WHERE status IN ('QUEUED', 'RETRY', 'RUNNING');

ALTER TABLE post_harvest_integration_events
  ADD COLUMN IF NOT EXISTS event_version integer NOT NULL DEFAULT 1,
  ADD COLUMN IF NOT EXISTS max_attempts integer NOT NULL DEFAULT 8,
  ADD COLUMN IF NOT EXISTS available_at timestamptz NOT NULL DEFAULT now(),
  ADD COLUMN IF NOT EXISTS lease_owner text,
  ADD COLUMN IF NOT EXISTS lease_expires_at timestamptz,
  ADD COLUMN IF NOT EXISTS dead_at timestamptz;

UPDATE post_harvest_integration_events
SET available_at = now()
WHERE available_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_post_harvest_dispatch_claim
  ON post_harvest_integration_events(status, available_at, lease_expires_at);
