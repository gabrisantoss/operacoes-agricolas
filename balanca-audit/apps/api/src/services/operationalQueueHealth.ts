type Statement = {
  get(...params: unknown[]): unknown;
};

type AppDatabase = {
  prepare(sql: string): Statement;
};

type SourceError = {
  ok: false;
  available: false;
  attentionRequired: false;
  draining: false;
  message: string;
};

export const DEFAULT_BACKLOG_ATTENTION_THRESHOLD_MS = 15 * 60_000;

export type OperationalQueueHealthOptions = {
  now?: Date;
  backlogAttentionThresholdMs?: number;
};

export type BackgroundJobsHealth = {
  ok: boolean;
  available: true;
  attentionRequired: boolean;
  draining: boolean;
  counts: {
    QUEUED: number;
    RUNNING: number;
    RETRY: number;
    SUCCEEDED: number;
    DEAD: number;
  };
  oldestPendingOrRetryAt: string | null;
  oldestPendingOrRetryAgeSeconds: number | null;
  claimableNowCount: number;
  scheduledRetryCount: number;
  oldestClaimableAt: string | null;
  oldestClaimableAgeSeconds: number | null;
  lastSucceededAt: string | null;
  lastSucceededAgeSeconds: number | null;
  deadCount: number;
  expiredRunningLeaseCount: number;
  missingRunningLeaseCount: number;
  unknownStatusCount: number;
};

export type PostHarvestOutboxHealth = {
  ok: boolean;
  available: true;
  attentionRequired: boolean;
  draining: boolean;
  deliveryConfigured: boolean;
  counts: {
    PENDING: number;
    PROCESSING: number;
    SENT: number;
    ERROR: number;
    DEAD: number;
  };
  oldestPendingOrErrorAt: string | null;
  oldestPendingOrErrorAgeSeconds: number | null;
  claimableNowCount: number;
  scheduledRetryCount: number;
  oldestClaimableAt: string | null;
  oldestClaimableAgeSeconds: number | null;
  lastSentAt: string | null;
  lastSentAgeSeconds: number | null;
  deadCount: number;
  expiredProcessingLeaseCount: number;
  missingProcessingLeaseCount: number;
  unknownStatusCount: number;
};

export type OperationalQueueHealth = {
  ok: boolean;
  state: "OK" | "DRAINING" | "ATTENTION" | "WAITING_CONFIGURATION" | "UNAVAILABLE";
  available: boolean;
  degraded: boolean;
  attentionRequired: boolean;
  draining: boolean;
  configurationRequired: boolean;
  backlogAttentionThresholdSeconds: number;
  collectedAt: string;
  message?: string;
  warning?: string;
  backgroundJobs: BackgroundJobsHealth | SourceError;
  postHarvestOutbox: PostHarvestOutboxHealth | (SourceError & { deliveryConfigured: boolean });
};

type BackgroundJobsRow = {
  total_count?: unknown;
  queued_count?: unknown;
  running_count?: unknown;
  retry_count?: unknown;
  succeeded_count?: unknown;
  dead_count?: unknown;
  oldest_pending_or_retry_at?: unknown;
  claimable_now_count?: unknown;
  scheduled_retry_count?: unknown;
  oldest_claimable_at?: unknown;
  last_succeeded_at?: unknown;
  expired_running_lease_count?: unknown;
  missing_running_lease_count?: unknown;
};

type PostHarvestOutboxRow = {
  total_count?: unknown;
  pending_count?: unknown;
  processing_count?: unknown;
  sent_count?: unknown;
  error_count?: unknown;
  dead_count?: unknown;
  oldest_pending_or_error_at?: unknown;
  claimable_now_count?: unknown;
  scheduled_retry_count?: unknown;
  oldest_claimable_at?: unknown;
  last_sent_at?: unknown;
  expired_processing_lease_count?: unknown;
  missing_processing_lease_count?: unknown;
};

export function readOperationalQueueHealth(
  db: AppDatabase,
  postHarvestDeliveryConfigured: boolean,
  options: OperationalQueueHealthOptions = {}
): OperationalQueueHealth {
  const now = options.now ?? new Date();
  const backlogAttentionThresholdMs = normalizeBacklogAttentionThreshold(options.backlogAttentionThresholdMs);
  const collectedAt = now.toISOString();
  const backgroundJobs = readTelemetrySource(
    "background_jobs",
    () => readBackgroundJobsHealth(db, now, backlogAttentionThresholdMs)
  );
  const postHarvestOutbox = readTelemetrySource(
    "post_harvest_integration_events",
    () => readPostHarvestOutboxHealth(db, postHarvestDeliveryConfigured, now, backlogAttentionThresholdMs),
    { deliveryConfigured: postHarvestDeliveryConfigured }
  );
  const available = backgroundJobs.available && postHarvestOutbox.available;
  const attentionRequired = backgroundJobs.attentionRequired || postHarvestOutbox.attentionRequired;
  const draining = (backgroundJobs.available && backgroundJobs.draining)
    || (postHarvestOutbox.available && postHarvestOutbox.draining);
  const configurationRequired = postHarvestOutbox.available
    && !postHarvestOutbox.deliveryConfigured
    && (
      postHarvestOutbox.counts.PENDING > 0
      || postHarvestOutbox.counts.ERROR > 0
      || postHarvestOutbox.counts.PROCESSING > 0
    );
  const state = !available
    ? "UNAVAILABLE"
    : attentionRequired
      ? "ATTENTION"
      : configurationRequired
        ? "WAITING_CONFIGURATION"
        : draining
          ? "DRAINING"
          : "OK";
  const ok = state === "OK" || state === "DRAINING";

  return {
    ok,
    state,
    available,
    degraded: !ok,
    attentionRequired,
    draining,
    configurationRequired,
    backlogAttentionThresholdSeconds: backlogAttentionThresholdMs / 1000,
    collectedAt,
    message: !available
      ? "Telemetria operacional incompleta; o health principal permanece baseado em banco e disco."
      : attentionRequired
        ? "Uma ou mais filas persistentes exigem atencao operacional."
        : undefined,
    warning: configurationRequired
      ? "A entrega pos-colheita nao esta configurada e existem eventos ativos aguardando configuracao."
      : undefined,
    backgroundJobs,
    postHarvestOutbox
  };
}

export function unavailableOperationalQueueHealth(
  postHarvestDeliveryConfigured: boolean,
  message = "Telemetria operacional nao consultada porque o banco principal esta indisponivel.",
  options: OperationalQueueHealthOptions = {}
): OperationalQueueHealth {
  const now = options.now ?? new Date();
  const backlogAttentionThresholdMs = normalizeBacklogAttentionThreshold(options.backlogAttentionThresholdMs);
  const safeMessage = safeErrorMessage(message);
  const sourceError: SourceError = {
    ok: false,
    available: false,
    attentionRequired: false,
    draining: false,
    message: safeMessage
  };

  return {
    ok: false,
    state: "UNAVAILABLE",
    available: false,
    degraded: true,
    attentionRequired: false,
    draining: false,
    configurationRequired: false,
    backlogAttentionThresholdSeconds: backlogAttentionThresholdMs / 1000,
    collectedAt: now.toISOString(),
    message: safeMessage,
    backgroundJobs: { ...sourceError },
    postHarvestOutbox: { ...sourceError, deliveryConfigured: postHarvestDeliveryConfigured }
  };
}

export function readBackgroundJobsHealth(
  db: AppDatabase,
  now = new Date(),
  backlogAttentionThresholdMs = DEFAULT_BACKLOG_ATTENTION_THRESHOLD_MS
): BackgroundJobsHealth {
  const row = db.prepare(`
    WITH telemetry_clock AS (
      SELECT ?::timestamptz AS observed_at
    )
    SELECT
      COUNT(*) AS total_count,
      COUNT(*) FILTER (WHERE status = 'QUEUED') AS queued_count,
      COUNT(*) FILTER (WHERE status = 'RUNNING') AS running_count,
      COUNT(*) FILTER (WHERE status = 'RETRY') AS retry_count,
      COUNT(*) FILTER (WHERE status = 'SUCCEEDED') AS succeeded_count,
      COUNT(*) FILTER (WHERE status = 'DEAD') AS dead_count,
      MIN(created_at) FILTER (WHERE status IN ('QUEUED', 'RETRY')) AS oldest_pending_or_retry_at,
      COUNT(*) FILTER (
        WHERE (status IN ('QUEUED', 'RETRY') AND available_at <= telemetry_clock.observed_at)
          OR (status = 'RUNNING' AND lease_expires_at < telemetry_clock.observed_at)
      ) AS claimable_now_count,
      COUNT(*) FILTER (
        WHERE status = 'RETRY' AND available_at > telemetry_clock.observed_at
      ) AS scheduled_retry_count,
      MIN(
        CASE
          WHEN status IN ('QUEUED', 'RETRY') AND available_at <= telemetry_clock.observed_at THEN available_at
          WHEN status = 'RUNNING' AND lease_expires_at < telemetry_clock.observed_at THEN lease_expires_at
          ELSE NULL
        END
      ) AS oldest_claimable_at,
      MAX(finished_at) FILTER (WHERE status = 'SUCCEEDED') AS last_succeeded_at,
      COUNT(*) FILTER (
        WHERE status = 'RUNNING'
          AND lease_expires_at IS NOT NULL
          AND lease_expires_at < telemetry_clock.observed_at
      ) AS expired_running_lease_count,
      COUNT(*) FILTER (
        WHERE status = 'RUNNING' AND lease_expires_at IS NULL
      ) AS missing_running_lease_count
    FROM background_jobs
    CROSS JOIN telemetry_clock
  `).get(now.toISOString()) as BackgroundJobsRow | undefined;

  const counts = {
    QUEUED: asCount(row?.queued_count),
    RUNNING: asCount(row?.running_count),
    RETRY: asCount(row?.retry_count),
    SUCCEEDED: asCount(row?.succeeded_count),
    DEAD: asCount(row?.dead_count)
  };
  const oldestPendingOrRetryAt = asTimestamp(row?.oldest_pending_or_retry_at);
  const claimableNowCount = asCount(row?.claimable_now_count);
  const scheduledRetryCount = asCount(row?.scheduled_retry_count);
  const oldestClaimableAt = asTimestamp(row?.oldest_claimable_at);
  const oldestClaimableAgeSeconds = ageSeconds(oldestClaimableAt, now);
  const lastSucceededAt = asTimestamp(row?.last_succeeded_at);
  const lastSucceededAgeSeconds = ageSeconds(lastSucceededAt, now);
  const expiredRunningLeaseCount = asCount(row?.expired_running_lease_count);
  const missingRunningLeaseCount = asCount(row?.missing_running_lease_count);
  const unknownStatusCount = Math.max(0, asCount(row?.total_count) - sumCounts(counts));
  const oldClaimableBacklog = isBacklogOlderThan(oldestClaimableAt, now, backlogAttentionThresholdMs);
  const draining = oldClaimableBacklog && isRecent(lastSucceededAt, now, backlogAttentionThresholdMs);
  const attentionRequired = counts.DEAD > 0
    || missingRunningLeaseCount > 0
    || unknownStatusCount > 0
    || (oldClaimableBacklog && !draining);

  return {
    ok: !attentionRequired,
    available: true,
    attentionRequired,
    draining,
    counts,
    oldestPendingOrRetryAt,
    oldestPendingOrRetryAgeSeconds: ageSeconds(oldestPendingOrRetryAt, now),
    claimableNowCount,
    scheduledRetryCount,
    oldestClaimableAt,
    oldestClaimableAgeSeconds,
    lastSucceededAt,
    lastSucceededAgeSeconds,
    deadCount: counts.DEAD,
    expiredRunningLeaseCount,
    missingRunningLeaseCount,
    unknownStatusCount
  };
}

export function readPostHarvestOutboxHealth(
  db: AppDatabase,
  deliveryConfigured: boolean,
  now = new Date(),
  backlogAttentionThresholdMs = DEFAULT_BACKLOG_ATTENTION_THRESHOLD_MS
): PostHarvestOutboxHealth {
  const row = db.prepare(`
    WITH telemetry_clock AS (
      SELECT ?::timestamptz AS observed_at
    )
    SELECT
      COUNT(*) AS total_count,
      COUNT(*) FILTER (WHERE status = 'PENDING') AS pending_count,
      COUNT(*) FILTER (WHERE status = 'PROCESSING') AS processing_count,
      COUNT(*) FILTER (WHERE status = 'SENT') AS sent_count,
      COUNT(*) FILTER (WHERE status = 'ERROR') AS error_count,
      COUNT(*) FILTER (WHERE status = 'DEAD') AS dead_count,
      MIN(created_at) FILTER (WHERE status IN ('PENDING', 'ERROR')) AS oldest_pending_or_error_at,
      COUNT(*) FILTER (
        WHERE (status IN ('PENDING', 'ERROR') AND available_at <= telemetry_clock.observed_at)
          OR (status = 'PROCESSING' AND lease_expires_at < telemetry_clock.observed_at)
      ) AS claimable_now_count,
      COUNT(*) FILTER (
        WHERE status = 'ERROR' AND available_at > telemetry_clock.observed_at
      ) AS scheduled_retry_count,
      MIN(
        CASE
          WHEN status IN ('PENDING', 'ERROR') AND available_at <= telemetry_clock.observed_at THEN available_at
          WHEN status = 'PROCESSING' AND lease_expires_at < telemetry_clock.observed_at THEN lease_expires_at
          ELSE NULL
        END
      ) AS oldest_claimable_at,
      MAX(sent_at) FILTER (WHERE status = 'SENT') AS last_sent_at,
      COUNT(*) FILTER (
        WHERE status = 'PROCESSING'
          AND lease_expires_at IS NOT NULL
          AND lease_expires_at < telemetry_clock.observed_at
      ) AS expired_processing_lease_count,
      COUNT(*) FILTER (
        WHERE status = 'PROCESSING' AND lease_expires_at IS NULL
      ) AS missing_processing_lease_count
    FROM post_harvest_integration_events
    CROSS JOIN telemetry_clock
  `).get(now.toISOString()) as PostHarvestOutboxRow | undefined;

  const counts = {
    PENDING: asCount(row?.pending_count),
    PROCESSING: asCount(row?.processing_count),
    SENT: asCount(row?.sent_count),
    ERROR: asCount(row?.error_count),
    DEAD: asCount(row?.dead_count)
  };
  const oldestPendingOrErrorAt = asTimestamp(row?.oldest_pending_or_error_at);
  const claimableNowCount = asCount(row?.claimable_now_count);
  const scheduledRetryCount = asCount(row?.scheduled_retry_count);
  const oldestClaimableAt = asTimestamp(row?.oldest_claimable_at);
  const oldestClaimableAgeSeconds = ageSeconds(oldestClaimableAt, now);
  const lastSentAt = asTimestamp(row?.last_sent_at);
  const lastSentAgeSeconds = ageSeconds(lastSentAt, now);
  const expiredProcessingLeaseCount = asCount(row?.expired_processing_lease_count);
  const missingProcessingLeaseCount = asCount(row?.missing_processing_lease_count);
  const unknownStatusCount = Math.max(0, asCount(row?.total_count) - sumCounts(counts));
  const oldClaimableBacklog = deliveryConfigured
    && isBacklogOlderThan(oldestClaimableAt, now, backlogAttentionThresholdMs);
  const draining = oldClaimableBacklog && isRecent(lastSentAt, now, backlogAttentionThresholdMs);
  const attentionRequired = counts.DEAD > 0
    || missingProcessingLeaseCount > 0
    || unknownStatusCount > 0
    || (oldClaimableBacklog && !draining);

  return {
    ok: !attentionRequired,
    available: true,
    attentionRequired,
    draining,
    deliveryConfigured,
    counts,
    oldestPendingOrErrorAt,
    oldestPendingOrErrorAgeSeconds: ageSeconds(oldestPendingOrErrorAt, now),
    claimableNowCount,
    scheduledRetryCount,
    oldestClaimableAt,
    oldestClaimableAgeSeconds,
    lastSentAt,
    lastSentAgeSeconds,
    deadCount: counts.DEAD,
    expiredProcessingLeaseCount,
    missingProcessingLeaseCount,
    unknownStatusCount
  };
}

function readTelemetrySource<T extends { available: true }, TErrorDetails extends object = Record<string, never>>(
  name: string,
  read: () => T,
  errorDetails?: TErrorDetails
): T | (SourceError & TErrorDetails) {
  try {
    return read();
  } catch (error) {
    return {
      ...(errorDetails ?? {} as TErrorDetails),
      ok: false,
      available: false,
      attentionRequired: false,
      draining: false,
      message: `Falha ao consultar ${name}: ${safeErrorMessage(error)}`
    } as SourceError & TErrorDetails;
  }
}

function sumCounts(counts: Record<string, number>) {
  return Object.values(counts).reduce((total, count) => total + count, 0);
}

function asCount(value: unknown) {
  const parsed = Number(value ?? 0);
  return Number.isFinite(parsed) && parsed >= 0 ? Math.trunc(parsed) : 0;
}

function asTimestamp(value: unknown): string | null {
  if (value instanceof Date && Number.isFinite(value.getTime())) {
    return value.toISOString();
  }
  if (typeof value !== "string" || !value.trim()) {
    return null;
  }
  const parsed = new Date(value);
  return Number.isFinite(parsed.getTime()) ? parsed.toISOString() : null;
}

function ageSeconds(timestamp: string | null, now: Date) {
  if (!timestamp) {
    return null;
  }
  return Math.max(0, Math.floor((now.getTime() - new Date(timestamp).getTime()) / 1000));
}

function isBacklogOlderThan(timestamp: string | null, now: Date, thresholdMs: number) {
  if (!timestamp) {
    return false;
  }
  return now.getTime() - new Date(timestamp).getTime() >= thresholdMs;
}

function isRecent(timestamp: string | null, now: Date, thresholdMs: number) {
  if (!timestamp) {
    return false;
  }
  const ageMs = now.getTime() - new Date(timestamp).getTime();
  return ageMs >= 0 && ageMs < thresholdMs;
}

function normalizeBacklogAttentionThreshold(value: number | undefined) {
  if (!Number.isFinite(value) || value === undefined || value < 0) {
    return DEFAULT_BACKLOG_ATTENTION_THRESHOLD_MS;
  }
  return Math.trunc(value);
}

function safeErrorMessage(error: unknown) {
  const raw = error instanceof Error
    ? error.message
    : typeof error === "string"
      ? error
      : "Erro desconhecido.";
  return raw
    .replace(/postgres(?:ql)?:\/\/[^\s]+/gi, "postgres://***")
    .slice(0, 500);
}
