import assert from "node:assert/strict";
import test from "node:test";
import {
  DEFAULT_BACKLOG_ATTENTION_THRESHOLD_MS,
  readOperationalQueueHealth,
  unavailableOperationalQueueHealth
} from "./operationalQueueHealth.js";

type QueryCall = { sql: string; params: unknown[] };
const now = new Date("2026-08-31T12:00:00.000Z");

test("operational queue health exposes compatible counts plus claimable and scheduled backlog", () => {
  const calls: QueryCall[] = [];
  const database = fakeDatabase(calls, {
    background_jobs: {
      total_count: 18, queued_count: "2", running_count: 3, retry_count: 1,
      succeeded_count: 8, dead_count: 4,
      oldest_pending_or_retry_at: "2026-08-31T11:40:00.000Z",
      claimable_now_count: 2, scheduled_retry_count: 1,
      oldest_claimable_at: "2026-08-31T11:45:00.000Z",
      expired_running_lease_count: 2, missing_running_lease_count: 0
    },
    post_harvest_integration_events: {
      total_count: 21, pending_count: 5, processing_count: 2, sent_count: 10,
      error_count: 3, dead_count: 1,
      oldest_pending_or_error_at: new Date("2026-08-31T10:30:00.000Z"),
      claimable_now_count: 5, scheduled_retry_count: 2,
      oldest_claimable_at: "2026-08-31T11:00:00.000Z",
      expired_processing_lease_count: "1", missing_processing_lease_count: 0
    }
  });

  const result = readOperationalQueueHealth(database, true, { now });

  assert.equal(result.ok, false);
  assert.equal(result.available, true);
  assert.equal(result.degraded, true);
  assert.equal(result.attentionRequired, true);
  assert.equal(result.configurationRequired, false);
  assert.equal(result.backlogAttentionThresholdSeconds, 900);
  assert.deepEqual(result.backgroundJobs, {
    ok: false, available: true, attentionRequired: true, draining: false,
    counts: { QUEUED: 2, RUNNING: 3, RETRY: 1, SUCCEEDED: 8, DEAD: 4 },
    oldestPendingOrRetryAt: "2026-08-31T11:40:00.000Z",
    oldestPendingOrRetryAgeSeconds: 1200,
    claimableNowCount: 2, scheduledRetryCount: 1,
    oldestClaimableAt: "2026-08-31T11:45:00.000Z",
    oldestClaimableAgeSeconds: 900,
    lastSucceededAt: null, lastSucceededAgeSeconds: null,
    deadCount: 4, expiredRunningLeaseCount: 2,
    missingRunningLeaseCount: 0, unknownStatusCount: 0
  });
  assert.deepEqual(result.postHarvestOutbox, {
    ok: false, available: true, attentionRequired: true, draining: false, deliveryConfigured: true,
    counts: { PENDING: 5, PROCESSING: 2, SENT: 10, ERROR: 3, DEAD: 1 },
    oldestPendingOrErrorAt: "2026-08-31T10:30:00.000Z",
    oldestPendingOrErrorAgeSeconds: 5400,
    claimableNowCount: 5, scheduledRetryCount: 2,
    oldestClaimableAt: "2026-08-31T11:00:00.000Z",
    oldestClaimableAgeSeconds: 3600,
    lastSentAt: null, lastSentAgeSeconds: null,
    deadCount: 1, expiredProcessingLeaseCount: 1,
    missingProcessingLeaseCount: 0, unknownStatusCount: 0
  });
  assert.equal(calls.length, 2);
  assert.ok(calls.every((call) => /^\s*WITH telemetry_clock\b/i.test(call.sql)));
  assert.deepEqual(calls.map((call) => call.params), [
    ["2026-08-31T12:00:00.000Z"],
    ["2026-08-31T12:00:00.000Z"]
  ]);
});

test("disabled delivery with pending backlog waits for configuration without an attention fault", () => {
  const result = readOperationalQueueHealth(fakeDatabase([], {
    background_jobs: {},
    post_harvest_integration_events: {
      total_count: 2061, pending_count: 2061,
      oldest_pending_or_error_at: "2026-06-19T00:00:00.000Z",
      claimable_now_count: 2061, scheduled_retry_count: 0,
      oldest_claimable_at: "2026-06-19T00:00:00.000Z"
    }
  }), false, { now });

  assert.equal(result.ok, false);
  assert.equal(result.degraded, true);
  assert.equal(result.attentionRequired, false);
  assert.equal(result.configurationRequired, true);
  assert.equal(result.state, "WAITING_CONFIGURATION");
  assert.match(result.warning ?? "", /nao esta configurada/i);
  assert.equal(result.postHarvestOutbox.available, true);
  if (result.postHarvestOutbox.available) {
    assert.equal(result.postHarvestOutbox.deliveryConfigured, false);
    assert.equal(result.postHarvestOutbox.claimableNowCount, 2061);
    assert.equal(result.postHarvestOutbox.attentionRequired, false);
  }
});

test("the same old claimable backlog requires attention when delivery is configured", () => {
  const result = readOperationalQueueHealth(fakeDatabase([], {
    background_jobs: {},
    post_harvest_integration_events: {
      total_count: 2, pending_count: 1, error_count: 1,
      claimable_now_count: 1, scheduled_retry_count: 1,
      oldest_claimable_at: "2026-08-31T11:44:59.000Z"
    }
  }), true, { now });

  assert.equal(result.configurationRequired, false);
  assert.equal(result.attentionRequired, true);
  assert.equal(result.state, "ATTENTION");
  assert.equal(result.postHarvestOutbox.available, true);
  if (result.postHarvestOutbox.available) {
    assert.equal(result.postHarvestOutbox.deliveryConfigured, true);
    assert.equal(result.postHarvestOutbox.claimableNowCount, 1);
    assert.equal(result.postHarvestOutbox.scheduledRetryCount, 1);
    assert.equal(result.postHarvestOutbox.oldestClaimableAgeSeconds, 901);
  }
});

test("recent delivery progress marks an old configured backlog as draining", () => {
  const result = readOperationalQueueHealth(fakeDatabase([], {
    background_jobs: {},
    post_harvest_integration_events: {
      total_count: 2, pending_count: 1, sent_count: 1,
      claimable_now_count: 1,
      oldest_claimable_at: "2026-08-31T11:00:00.000Z",
      last_sent_at: "2026-08-31T11:55:00.000Z"
    }
  }), true, { now });

  assert.equal(result.ok, true);
  assert.equal(result.degraded, false);
  assert.equal(result.attentionRequired, false);
  assert.equal(result.draining, true);
  assert.equal(result.state, "DRAINING");
  if (result.postHarvestOutbox.available) {
    assert.equal(result.postHarvestOutbox.draining, true);
    assert.equal(result.postHarvestOutbox.lastSentAt, "2026-08-31T11:55:00.000Z");
    assert.equal(result.postHarvestOutbox.lastSentAgeSeconds, 300);
  }
});

test("an orphaned processing event also requires delivery configuration", () => {
  const result = readOperationalQueueHealth(fakeDatabase([], {
    background_jobs: {},
    post_harvest_integration_events: {
      total_count: 1, processing_count: 1
    }
  }), false, { now });

  assert.equal(result.configurationRequired, true);
  assert.equal(result.attentionRequired, false);
  assert.equal(result.state, "WAITING_CONFIGURATION");
});

test("background jobs always require attention for claimable backlog at the threshold", () => {
  const result = readOperationalQueueHealth(fakeDatabase([], {
    background_jobs: {
      total_count: 1, queued_count: 1, claimable_now_count: 1,
      oldest_claimable_at: "2026-08-31T11:45:00.000Z"
    },
    post_harvest_integration_events: {}
  }), false, { now, backlogAttentionThresholdMs: DEFAULT_BACKLOG_ATTENTION_THRESHOLD_MS });

  assert.equal(result.attentionRequired, true);
  assert.equal(result.configurationRequired, false);
  assert.equal(result.backgroundJobs.available, true);
  if (result.backgroundJobs.available) {
    assert.equal(result.backgroundJobs.oldestClaimableAgeSeconds, 900);
  }
});

test("a future retry remains scheduled and cannot age the claimable backlog", () => {
  const result = readOperationalQueueHealth(fakeDatabase([], {
    background_jobs: {
      total_count: 1, retry_count: 1,
      oldest_pending_or_retry_at: "2026-08-31T10:00:00.000Z",
      claimable_now_count: 0, scheduled_retry_count: 1, oldest_claimable_at: null
    },
    post_harvest_integration_events: {
      total_count: 1, error_count: 1,
      oldest_pending_or_error_at: "2026-08-31T10:00:00.000Z",
      claimable_now_count: 0, scheduled_retry_count: 1, oldest_claimable_at: null
    }
  }), true, { now });

  assert.equal(result.attentionRequired, false);
  assert.equal(result.state, "OK");
  if (result.backgroundJobs.available) {
    assert.equal(result.backgroundJobs.oldestPendingOrRetryAgeSeconds, 7200);
    assert.equal(result.backgroundJobs.claimableNowCount, 0);
    assert.equal(result.backgroundJobs.scheduledRetryCount, 1);
    assert.equal(result.backgroundJobs.oldestClaimableAgeSeconds, null);
  }
  if (result.postHarvestOutbox.available) {
    assert.equal(result.postHarvestOutbox.oldestPendingOrErrorAgeSeconds, 7200);
    assert.equal(result.postHarvestOutbox.claimableNowCount, 0);
    assert.equal(result.postHarvestOutbox.scheduledRetryCount, 1);
    assert.equal(result.postHarvestOutbox.oldestClaimableAgeSeconds, null);
  }
});

test("a telemetry source failure is unavailable and does not invent an attention fault", () => {
  const database = {
    prepare(sql: string) {
      return { get() {
        if (sql.includes("FROM background_jobs")) {
          throw new Error("connection failed at postgresql://operator:secret@db.internal/balanca");
        }
        return {
          total_count: 3, pending_count: 1, sent_count: 2,
          claimable_now_count: 1, oldest_claimable_at: "2026-08-31T11:59:30.000Z"
        };
      } };
    }
  };

  const result = readOperationalQueueHealth(database, false, { now });

  assert.equal(result.ok, false);
  assert.equal(result.available, false);
  assert.equal(result.degraded, true);
  assert.equal(result.attentionRequired, false);
  assert.equal(result.configurationRequired, true);
  assert.equal(result.state, "UNAVAILABLE");
  assert.match(result.message ?? "", /health principal permanece/i);
  assert.deepEqual(result.backgroundJobs, {
    ok: false, available: false, attentionRequired: false, draining: false,
    message: "Falha ao consultar background_jobs: connection failed at postgres://***"
  });
  assert.equal(result.postHarvestOutbox.deliveryConfigured, false);
});

test("unavailable advisory represents a failed core database check without queries", () => {
  const result = unavailableOperationalQueueHealth(false, undefined, { now });

  assert.equal(result.ok, false);
  assert.equal(result.available, false);
  assert.equal(result.attentionRequired, false);
  assert.equal(result.configurationRequired, false);
  assert.equal(result.state, "UNAVAILABLE");
  assert.equal(result.postHarvestOutbox.deliveryConfigured, false);
  assert.match(result.message ?? "", /banco principal esta indisponivel/i);
});

test("empty queues are healthy and missing leases or unknown statuses are not", () => {
  const empty = readOperationalQueueHealth(fakeDatabase([], {
    background_jobs: {}, post_harvest_integration_events: {}
  }), false, { now });
  assert.equal(empty.ok, true);
  assert.equal(empty.state, "OK");

  const anomalous = readOperationalQueueHealth(fakeDatabase([], {
    background_jobs: { total_count: 2, running_count: 1, missing_running_lease_count: 1 },
    post_harvest_integration_events: { total_count: 1, processing_count: 1, missing_processing_lease_count: 1 }
  }), true, { now });
  assert.equal(anomalous.attentionRequired, true);
  if (anomalous.backgroundJobs.available) {
    assert.equal(anomalous.backgroundJobs.unknownStatusCount, 1);
  }
});

function fakeDatabase(calls: QueryCall[], rows: Record<string, Record<string, unknown>>) {
  return {
    prepare(sql: string) {
      return {
        get(...params: unknown[]) {
          calls.push({ sql, params });
          const table = Object.keys(rows).find((candidate) => sql.includes(`FROM ${candidate}`));
          if (!table) throw new Error("unexpected query");
          return rows[table];
        }
      };
    }
  };
}
