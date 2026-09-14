import { randomUUID } from "node:crypto";

type Statement = {
  all(...params: unknown[]): unknown[];
  get(...params: unknown[]): unknown;
  run(...params: unknown[]): { changes: number };
  runMany(paramsList: any[]): { changes: number };
};

type AppDatabase = { prepare(sql: string): Statement };

export type PostHarvestIntegrationEventStatus = "PENDING" | "PROCESSING" | "SENT" | "ERROR" | "DEAD";

export type PostHarvestIntegrationEventRecord = {
  id: string;
  eventId: string;
  eventType: string;
  eventVersion: number;
  orderId?: string | null;
  orderNumber: string;
  farmId?: string | null;
  farmCode?: string | null;
  farmName: string;
  fieldId?: string | null;
  fieldCode: string;
  frontNumbers: number[];
  payload: unknown;
  status: PostHarvestIntegrationEventStatus;
  attemptCount: number;
  maxAttempts: number;
  availableAt: string;
  leaseOwner?: string | null;
  leaseExpiresAt?: string | null;
  lastHttpStatus?: number | null;
  lastResponseBody?: string | null;
  lastError?: string | null;
  sentAt?: string | null;
  deadAt?: string | null;
  createdAt: string;
  updatedAt: string;
};

export type CreatePostHarvestIntegrationEventInput = {
  eventId: string;
  eventType: string;
  eventVersion?: number;
  orderId: string;
  orderNumber: string;
  farmId?: string | null;
  farmCode?: string | null;
  farmName: string;
  fieldId?: string | null;
  fieldCode: string;
  frontNumbers: number[];
  payload: unknown;
};

type PostHarvestIntegrationEventRow = {
  id: string;
  event_id: string;
  event_type: string;
  event_version: number;
  order_id: string | null;
  order_number: string;
  farm_id: string | null;
  farm_code: string | null;
  farm_name: string;
  field_id: string | null;
  field_code: string;
  front_numbers: string | unknown[];
  payload_json: string | unknown;
  status: PostHarvestIntegrationEventStatus;
  attempt_count: number;
  max_attempts: number;
  available_at: string;
  lease_owner: string | null;
  lease_expires_at: string | null;
  last_http_status: number | null;
  last_response_body: string | null;
  last_error: string | null;
  sent_at: string | null;
  dead_at: string | null;
  created_at: string;
  updated_at: string;
};

export class PostHarvestIntegrationRepository {
  constructor(private readonly db: AppDatabase) {}

  createEvents(inputs: CreatePostHarvestIntegrationEventInput[]) {
    if (inputs.length === 0) return [];

    const insert = this.db.prepare(`
      INSERT INTO post_harvest_integration_events (
        id, event_id, event_type, event_version, order_id, order_number,
        farm_id, farm_code, farm_name, field_id, field_code, front_numbers,
        payload_json, status, available_at, created_at, updated_at
      )
      VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'PENDING', CURRENT_TIMESTAMP,
              CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
      ON CONFLICT(event_id) DO NOTHING
    `);
    insert.runMany(inputs.map((input) => [
      randomUUID(), input.eventId, input.eventType, input.eventVersion ?? 1,
      input.orderId, input.orderNumber, input.farmId ?? null, input.farmCode ?? null,
      input.farmName, input.fieldId ?? null, input.fieldCode,
      JSON.stringify(input.frontNumbers), JSON.stringify(input.payload)
    ]));

    return this.findEventsByEventIds(inputs.map((input) => input.eventId));
  }

  listEvents(input: { status?: PostHarvestIntegrationEventStatus; limit?: number; offset?: number } = {}) {
    const params: unknown[] = [];
    const where = input.status ? "WHERE status = ?" : "";
    if (input.status) params.push(input.status);
    const rows = this.db.prepare(`
      SELECT * FROM post_harvest_integration_events
      ${where}
      ORDER BY created_at DESC, id DESC
      LIMIT ? OFFSET ?
    `).all(...params, normalizeLimit(input.limit), normalizeOffset(input.offset)) as PostHarvestIntegrationEventRow[];
    return rows.map(mapPostHarvestIntegrationEvent);
  }

  countEvents(status?: PostHarvestIntegrationEventStatus) {
    const row = this.db.prepare(`
      SELECT COUNT(*) AS count FROM post_harvest_integration_events
      ${status ? "WHERE status = ?" : ""}
    `).get(...(status ? [status] : [])) as { count?: number } | undefined;
    return Number(row?.count ?? 0);
  }

  summarizeEvents() {
    const rows = this.db.prepare(`
      SELECT status, COUNT(*) AS count
      FROM post_harvest_integration_events
      GROUP BY status
    `).all() as Array<{ status: PostHarvestIntegrationEventStatus; count: number }>;
    const count = (status: PostHarvestIntegrationEventStatus) => Number(rows.find((row) => row.status === status)?.count ?? 0);
    return { pending: count("PENDING"), processing: count("PROCESSING"), sent: count("SENT"), error: count("ERROR"), dead: count("DEAD") };
  }

  claimDispatchableEvents(input: { workerId: string; limit?: number; leaseMs?: number }) {
    const rows = this.db.prepare(`
      WITH candidates AS (
        SELECT id
        FROM post_harvest_integration_events
        WHERE (
          (status IN ('PENDING', 'ERROR') AND available_at <= CURRENT_TIMESTAMP)
          OR (status = 'PROCESSING' AND lease_expires_at < CURRENT_TIMESTAMP)
        )
        ORDER BY available_at ASC, created_at ASC, id ASC
        FOR UPDATE SKIP LOCKED
        LIMIT ?
      )
      UPDATE post_harvest_integration_events AS event
      SET status = 'PROCESSING',
          attempt_count = event.attempt_count + 1,
          lease_owner = ?,
          lease_expires_at = CURRENT_TIMESTAMP + (? * INTERVAL '1 millisecond'),
          updated_at = CURRENT_TIMESTAMP
      FROM candidates
      WHERE event.id = candidates.id
      RETURNING event.*
    `).all(normalizeLimit(input.limit), input.workerId, normalizeLeaseMs(input.leaseMs)) as PostHarvestIntegrationEventRow[];
    return rows.map(mapPostHarvestIntegrationEvent).sort((a, b) => a.createdAt.localeCompare(b.createdAt));
  }

  claimEventById(id: string, workerId: string, leaseMs?: number) {
    const row = this.db.prepare(`
      UPDATE post_harvest_integration_events
      SET status = 'PROCESSING',
          attempt_count = attempt_count + 1,
          lease_owner = ?,
          lease_expires_at = CURRENT_TIMESTAMP + (? * INTERVAL '1 millisecond'),
          updated_at = CURRENT_TIMESTAMP
      WHERE id = ?
        AND (
          (status IN ('PENDING', 'ERROR') AND available_at <= CURRENT_TIMESTAMP)
          OR (status = 'PROCESSING' AND lease_expires_at < CURRENT_TIMESTAMP)
        )
      RETURNING *
    `).get(workerId, normalizeLeaseMs(leaseMs), id) as PostHarvestIntegrationEventRow | undefined;
    return row ? mapPostHarvestIntegrationEvent(row) : null;
  }

  findEventById(id: string) {
    const row = this.db.prepare("SELECT * FROM post_harvest_integration_events WHERE id = ?").get(id) as PostHarvestIntegrationEventRow | undefined;
    return row ? mapPostHarvestIntegrationEvent(row) : null;
  }

  findEventsByEventIds(eventIds: string[]) {
    const uniqueIds = Array.from(new Set(eventIds.filter(Boolean)));
    if (uniqueIds.length === 0) return [];
    const placeholders = uniqueIds.map(() => "?").join(",");
    const rows = this.db.prepare(`
      SELECT * FROM post_harvest_integration_events
      WHERE event_id IN (${placeholders})
      ORDER BY created_at ASC, id ASC
    `).all(...uniqueIds) as PostHarvestIntegrationEventRow[];
    return rows.map(mapPostHarvestIntegrationEvent);
  }

  markSent(id: string, workerId: string, input: { httpStatus: number; responseBody?: string | null }) {
    const row = this.db.prepare(`
      UPDATE post_harvest_integration_events
      SET status = 'SENT', last_http_status = ?, last_response_body = ?, last_error = NULL,
          sent_at = CURRENT_TIMESTAMP, dead_at = NULL, lease_owner = NULL,
          lease_expires_at = NULL, updated_at = CURRENT_TIMESTAMP
      WHERE id = ? AND status = 'PROCESSING' AND lease_owner = ?
      RETURNING *
    `).get(input.httpStatus, truncateText(input.responseBody), id, workerId) as PostHarvestIntegrationEventRow | undefined;
    return row ? mapPostHarvestIntegrationEvent(row) : null;
  }

  markError(
    event: PostHarvestIntegrationEventRecord,
    workerId: string,
    input: { httpStatus?: number | null; responseBody?: string | null; error: string },
    now = new Date()
  ) {
    const disposition = postHarvestFailureDisposition(event.attemptCount, event.maxAttempts, now);
    const row = this.db.prepare(`
      UPDATE post_harvest_integration_events
      SET status = ?, available_at = ?, last_http_status = ?, last_response_body = ?,
          last_error = ?, dead_at = CASE WHEN ? = 'DEAD' THEN CURRENT_TIMESTAMP ELSE NULL END,
          lease_owner = NULL, lease_expires_at = NULL, updated_at = CURRENT_TIMESTAMP
      WHERE id = ? AND status = 'PROCESSING' AND lease_owner = ?
      RETURNING *
    `).get(
      disposition.status, disposition.availableAt, input.httpStatus ?? null,
      truncateText(input.responseBody), truncateText(input.error), disposition.status,
      event.id, workerId
    ) as PostHarvestIntegrationEventRow | undefined;
    return row ? mapPostHarvestIntegrationEvent(row) : null;
  }
}

export function postHarvestFailureDisposition(attemptCount: number, maxAttempts: number, now = new Date()) {
  const attempts = Math.max(1, Math.trunc(attemptCount));
  const maximum = Math.min(Math.max(Math.trunc(maxAttempts || 8), 1), 50);
  if (attempts >= maximum) {
    return { status: "DEAD" as const, delayMs: 0, availableAt: now.toISOString() };
  }
  const delayMs = Math.min(6 * 60 * 60_000, 30_000 * 2 ** Math.min(attempts - 1, 10));
  return { status: "ERROR" as const, delayMs, availableAt: new Date(now.getTime() + delayMs).toISOString() };
}

function mapPostHarvestIntegrationEvent(row: PostHarvestIntegrationEventRow): PostHarvestIntegrationEventRecord {
  return {
    id: row.id, eventId: row.event_id, eventType: row.event_type,
    eventVersion: Number(row.event_version ?? 1), orderId: row.order_id,
    orderNumber: row.order_number, farmId: row.farm_id, farmCode: row.farm_code,
    farmName: row.farm_name, fieldId: row.field_id, fieldCode: row.field_code,
    frontNumbers: parseNumberArray(row.front_numbers), payload: parsePayload(row.payload_json),
    status: row.status, attemptCount: Number(row.attempt_count ?? 0),
    maxAttempts: Number(row.max_attempts ?? 8), availableAt: row.available_at,
    leaseOwner: row.lease_owner, leaseExpiresAt: row.lease_expires_at,
    lastHttpStatus: row.last_http_status, lastResponseBody: row.last_response_body,
    lastError: row.last_error, sentAt: row.sent_at, deadAt: row.dead_at,
    createdAt: row.created_at, updatedAt: row.updated_at
  };
}

function parseNumberArray(value: string | unknown[]) {
  if (Array.isArray(value)) return value.map(Number).filter(Number.isInteger);
  try {
    const parsed = JSON.parse(value);
    return Array.isArray(parsed) ? parsed.map(Number).filter(Number.isInteger) : [];
  } catch { return []; }
}

function parsePayload(value: string | unknown) {
  if (typeof value !== "string") return value;
  try { return JSON.parse(value); } catch { return {}; }
}

function normalizeLimit(value: number | undefined) { return Math.min(Math.max(Math.trunc(value ?? 100), 1), 500); }
function normalizeOffset(value: number | undefined) { return Math.max(Math.trunc(value ?? 0), 0); }
function normalizeLeaseMs(value: number | undefined) { return Math.min(Math.max(Math.trunc(value ?? 60_000), 10_000), 10 * 60_000); }
function truncateText(value: string | null | undefined) {
  if (!value) return null;
  return value.length > 4000 ? `${value.slice(0, 4000)}...` : value;
}
