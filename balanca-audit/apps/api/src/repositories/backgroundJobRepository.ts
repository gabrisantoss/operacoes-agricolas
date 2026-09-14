import { randomUUID } from "node:crypto";

type Statement = {
  all(...params: unknown[]): unknown[];
  get(...params: unknown[]): unknown;
  run(...params: unknown[]): { changes: number };
};

type AppDatabase = {
  prepare(sql: string): Statement;
};

export type BackgroundJobKind = "RECONCILE_ORPHANS";
export type BackgroundJobStatus = "QUEUED" | "RUNNING" | "RETRY" | "SUCCEEDED" | "DEAD";

export type BackgroundJobRecord<TPayload = unknown> = {
  id: string;
  kind: BackgroundJobKind;
  dedupeKey: string;
  payload: TPayload;
  status: BackgroundJobStatus;
  attemptCount: number;
  maxAttempts: number;
  availableAt: string;
  leaseOwner?: string | null;
  leaseExpiresAt?: string | null;
  progressPercent: number;
  progressStage: string;
  progressMessage: string;
  lastError?: string | null;
  startedAt?: string | null;
  finishedAt?: string | null;
  createdAt: string;
  updatedAt: string;
};

type BackgroundJobRow = {
  id: string;
  kind: BackgroundJobKind;
  dedupe_key: string;
  payload_json: unknown;
  status: BackgroundJobStatus;
  attempt_count: number;
  max_attempts: number;
  available_at: string;
  lease_owner: string | null;
  lease_expires_at: string | null;
  progress_percent: number;
  progress_stage: string;
  progress_message: string;
  last_error: string | null;
  started_at: string | null;
  finished_at: string | null;
  created_at: string;
  updated_at: string;
};

export type BackgroundJobFailureDisposition = {
  status: "RETRY" | "DEAD";
  delayMs: number;
  availableAt: string;
};

export class BackgroundJobRepository {
  constructor(private readonly db: AppDatabase) {}

  enqueue<TPayload>(input: {
    kind: BackgroundJobKind;
    dedupeKey: string;
    payload: TPayload;
    maxAttempts?: number;
  }): BackgroundJobRecord<TPayload> {
    const row = this.db.prepare(`
      INSERT INTO background_jobs (
        id, kind, dedupe_key, payload_json, status, max_attempts,
        available_at, progress_percent, progress_stage, progress_message,
        created_at, updated_at
      )
      VALUES (?, ?, ?, ?::jsonb, 'QUEUED', ?, CURRENT_TIMESTAMP, 0, 'queued',
              'Aguardando processamento.', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
      ON CONFLICT (kind, dedupe_key)
        WHERE status IN ('QUEUED', 'RETRY', 'RUNNING')
      DO UPDATE SET
        payload_json = EXCLUDED.payload_json,
        max_attempts = GREATEST(background_jobs.max_attempts, EXCLUDED.max_attempts),
        updated_at = CURRENT_TIMESTAMP
      RETURNING *
    `).get(
      randomUUID(),
      input.kind,
      normalizeDedupeKey(input.dedupeKey),
      JSON.stringify(input.payload ?? {}),
      normalizeMaxAttempts(input.maxAttempts)
    ) as BackgroundJobRow;

    return mapBackgroundJob<TPayload>(row);
  }

  claimNext<TPayload>(input: {
    kind: BackgroundJobKind;
    workerId: string;
    leaseMs?: number;
  }): BackgroundJobRecord<TPayload> | null {
    const row = this.db.prepare(`
      WITH candidate AS (
        SELECT id
        FROM background_jobs
        WHERE kind = ?
          AND (
            (status IN ('QUEUED', 'RETRY') AND available_at <= CURRENT_TIMESTAMP)
            OR (status = 'RUNNING' AND lease_expires_at < CURRENT_TIMESTAMP)
          )
        ORDER BY available_at ASC, created_at ASC, id ASC
        FOR UPDATE SKIP LOCKED
        LIMIT 1
      )
      UPDATE background_jobs AS job
      SET status = 'RUNNING',
          attempt_count = job.attempt_count + 1,
          lease_owner = ?,
          lease_expires_at = CURRENT_TIMESTAMP + (? * INTERVAL '1 millisecond'),
          started_at = COALESCE(job.started_at, CURRENT_TIMESTAMP),
          finished_at = NULL,
          updated_at = CURRENT_TIMESTAMP
      FROM candidate
      WHERE job.id = candidate.id
      RETURNING job.*
    `).get(input.kind, input.workerId, normalizeLeaseMs(input.leaseMs)) as BackgroundJobRow | undefined;

    return row ? mapBackgroundJob<TPayload>(row) : null;
  }

  updateProgress(
    id: string,
    workerId: string,
    input: { percent: number; stage: string; message: string; leaseMs?: number }
  ) {
    const row = this.db.prepare(`
      UPDATE background_jobs
      SET progress_percent = GREATEST(progress_percent, ?),
          progress_stage = ?,
          progress_message = ?,
          lease_expires_at = CURRENT_TIMESTAMP + (? * INTERVAL '1 millisecond'),
          updated_at = CURRENT_TIMESTAMP
      WHERE id = ? AND status = 'RUNNING' AND lease_owner = ?
      RETURNING *
    `).get(
      normalizeProgress(input.percent),
      input.stage.slice(0, 100),
      input.message.slice(0, 1000),
      normalizeLeaseMs(input.leaseMs),
      id,
      workerId
    ) as BackgroundJobRow | undefined;

    return row ? mapBackgroundJob(row) : null;
  }

  complete<TPayload = unknown>(id: string, workerId: string) {
    const row = this.db.prepare(`
      UPDATE background_jobs
      SET status = 'SUCCEEDED',
          progress_percent = 100,
          progress_stage = 'done',
          progress_message = 'Processamento concluido.',
          lease_owner = NULL,
          lease_expires_at = NULL,
          last_error = NULL,
          finished_at = CURRENT_TIMESTAMP,
          updated_at = CURRENT_TIMESTAMP
      WHERE id = ? AND status = 'RUNNING' AND lease_owner = ?
      RETURNING *
    `).get(id, workerId) as BackgroundJobRow | undefined;

    return row ? mapBackgroundJob<TPayload>(row) : null;
  }

  fail<TPayload>(job: BackgroundJobRecord<TPayload>, workerId: string, error: unknown, now = new Date()) {
    const disposition = backgroundJobFailureDisposition(job.attemptCount, job.maxAttempts, now);
    const row = this.db.prepare(`
      UPDATE background_jobs
      SET status = ?,
          available_at = ?,
          lease_owner = NULL,
          lease_expires_at = NULL,
          last_error = ?,
          progress_stage = ?,
          progress_message = ?,
          finished_at = CASE WHEN ? = 'DEAD' THEN CURRENT_TIMESTAMP ELSE NULL END,
          updated_at = CURRENT_TIMESTAMP
      WHERE id = ? AND status = 'RUNNING' AND lease_owner = ?
      RETURNING *
    `).get(
      disposition.status,
      disposition.availableAt,
      truncateError(error),
      disposition.status === "DEAD" ? "dead-letter" : "retry",
      disposition.status === "DEAD" ? "Falha definitiva; revisao manual necessaria." : "Falha temporaria; nova tentativa agendada.",
      disposition.status,
      job.id,
      workerId
    ) as BackgroundJobRow | undefined;

    return row ? mapBackgroundJob<TPayload>(row) : null;
  }

  findById<TPayload>(id: string) {
    const row = this.db.prepare("SELECT * FROM background_jobs WHERE id = ?").get(id) as BackgroundJobRow | undefined;
    return row ? mapBackgroundJob<TPayload>(row) : null;
  }

  findLatest<TPayload>(kind: BackgroundJobKind, dedupeKey: string) {
    const row = this.db.prepare(`
      SELECT *
      FROM background_jobs
      WHERE kind = ? AND dedupe_key = ?
      ORDER BY created_at DESC, id DESC
      LIMIT 1
    `).get(kind, normalizeDedupeKey(dedupeKey)) as BackgroundJobRow | undefined;
    return row ? mapBackgroundJob<TPayload>(row) : null;
  }

  countQueuedBefore(kind: BackgroundJobKind, job: BackgroundJobRecord) {
    const row = this.db.prepare(`
      SELECT COUNT(*) AS count
      FROM background_jobs
      WHERE kind = ?
        AND status IN ('QUEUED', 'RETRY')
        AND (available_at, created_at, id) <= (?, ?, ?)
    `).get(kind, job.availableAt, job.createdAt, job.id) as { count?: number } | undefined;
    return Number(row?.count ?? 0);
  }
}

export function backgroundJobFailureDisposition(
  attemptCount: number,
  maxAttempts: number,
  now = new Date()
): BackgroundJobFailureDisposition {
  const attempts = Math.max(1, Math.trunc(attemptCount));
  const maximum = normalizeMaxAttempts(maxAttempts);

  if (attempts >= maximum) {
    return { status: "DEAD", delayMs: 0, availableAt: now.toISOString() };
  }

  const delayMs = Math.min(30 * 60_000, 5_000 * 2 ** Math.min(attempts - 1, 10));
  return {
    status: "RETRY",
    delayMs,
    availableAt: new Date(now.getTime() + delayMs).toISOString()
  };
}

function mapBackgroundJob<TPayload = unknown>(row: BackgroundJobRow): BackgroundJobRecord<TPayload> {
  return {
    id: row.id,
    kind: row.kind,
    dedupeKey: row.dedupe_key,
    payload: parsePayload(row.payload_json) as TPayload,
    status: row.status,
    attemptCount: Number(row.attempt_count),
    maxAttempts: Number(row.max_attempts),
    availableAt: row.available_at,
    leaseOwner: row.lease_owner,
    leaseExpiresAt: row.lease_expires_at,
    progressPercent: Number(row.progress_percent),
    progressStage: row.progress_stage,
    progressMessage: row.progress_message,
    lastError: row.last_error,
    startedAt: row.started_at,
    finishedAt: row.finished_at,
    createdAt: row.created_at,
    updatedAt: row.updated_at
  };
}

function parsePayload(value: unknown) {
  if (typeof value !== "string") {
    return value ?? {};
  }

  try {
    return JSON.parse(value);
  } catch {
    return {};
  }
}

function normalizeDedupeKey(value: string) {
  const normalized = value.trim();
  if (!normalized || normalized.length > 500) {
    throw new Error("dedupeKey deve ter entre 1 e 500 caracteres.");
  }
  return normalized;
}

function normalizeMaxAttempts(value: number | undefined) {
  return Math.min(Math.max(Math.trunc(value ?? 5), 1), 20);
}

function normalizeLeaseMs(value: number | undefined) {
  return Math.min(Math.max(Math.trunc(value ?? 10 * 60_000), 30_000), 60 * 60_000);
}

function normalizeProgress(value: number) {
  return Math.min(Math.max(Math.round(value), 0), 100);
}

function truncateError(error: unknown) {
  const message = error instanceof Error ? error.message : String(error);
  return message.length > 4000 ? `${message.slice(0, 4000)}...` : message;
}
