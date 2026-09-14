import assert from "node:assert/strict";
import test, { after } from "node:test";
import { createPostgresTestDatabase } from "../testSupport/postgresTestDatabase.js";

process.env.NODE_ENV = "test";
const testDatabaseUrl = process.env.BALANCA_TEST_DATABASE_URL?.trim();

if (!testDatabaseUrl) {
  test.skip("operational queue health integration requires BALANCA_TEST_DATABASE_URL", () => {});
} else {
  const testDatabase = await createPostgresTestDatabase();
  const { db } = await import("../db.js");
  const { readOperationalQueueHealth } = await import("./operationalQueueHealth.js");
  const now = new Date("2026-08-31T12:00:00.000Z");

  after(async () => {
    await Promise.resolve(db.close?.());
    await testDatabase.cleanup();
  });

  test("PostgreSQL separates claimable backlog from future retries and honors delivery configuration", () => {
    insertBackgroundJob({
      id: "job-recent", status: "QUEUED",
      createdAt: "2026-08-31T11:50:00.000Z", availableAt: "2026-08-31T11:50:00.000Z"
    });
    insertBackgroundJob({
      id: "job-future", status: "RETRY",
      createdAt: "2026-08-31T10:00:00.000Z", availableAt: "2026-08-31T12:30:00.000Z"
    });
    insertOutboxEvent({
      id: "event-old-pending", status: "PENDING",
      createdAt: "2026-08-31T11:00:00.000Z", availableAt: "2026-08-31T11:00:00.000Z"
    });
    insertOutboxEvent({
      id: "event-future-error", status: "ERROR",
      createdAt: "2026-08-31T09:00:00.000Z", availableAt: "2026-08-31T12:30:00.000Z"
    });
    insertOutboxEvent({
      id: "event-recent-sent", status: "SENT",
      createdAt: "2026-08-31T11:54:00.000Z", availableAt: "2026-08-31T11:54:00.000Z",
      sentAt: "2026-08-31T11:55:00.000Z"
    });

    const disabled = readOperationalQueueHealth(db, false, { now });

    assert.equal(disabled.state, "WAITING_CONFIGURATION");
    assert.equal(disabled.ok, false);
    assert.equal(disabled.attentionRequired, false);
    assert.equal(disabled.configurationRequired, true);
    assert.equal(disabled.backgroundJobs.available, true);
    if (disabled.backgroundJobs.available) {
      assert.equal(disabled.backgroundJobs.claimableNowCount, 1);
      assert.equal(disabled.backgroundJobs.scheduledRetryCount, 1);
      assert.equal(disabled.backgroundJobs.oldestClaimableAt, "2026-08-31T11:50:00.000Z");
      assert.equal(disabled.backgroundJobs.oldestClaimableAgeSeconds, 600);
      assert.equal(disabled.backgroundJobs.oldestPendingOrRetryAgeSeconds, 7200);
      assert.equal(disabled.backgroundJobs.attentionRequired, false);
    }
    assert.equal(disabled.postHarvestOutbox.available, true);
    if (disabled.postHarvestOutbox.available) {
      assert.equal(disabled.postHarvestOutbox.deliveryConfigured, false);
      assert.equal(disabled.postHarvestOutbox.claimableNowCount, 1);
      assert.equal(disabled.postHarvestOutbox.scheduledRetryCount, 1);
      assert.equal(disabled.postHarvestOutbox.oldestClaimableAt, "2026-08-31T11:00:00.000Z");
      assert.equal(disabled.postHarvestOutbox.oldestClaimableAgeSeconds, 3600);
      assert.equal(disabled.postHarvestOutbox.oldestPendingOrErrorAgeSeconds, 10800);
      assert.equal(disabled.postHarvestOutbox.attentionRequired, false);
    }

    const enabled = readOperationalQueueHealth(db, true, { now });
    assert.equal(enabled.state, "DRAINING");
    assert.equal(enabled.configurationRequired, false);
    assert.equal(enabled.attentionRequired, false);
    assert.equal(enabled.draining, true);
    assert.equal(enabled.postHarvestOutbox.available, true);
    if (enabled.postHarvestOutbox.available) {
      assert.equal(enabled.postHarvestOutbox.deliveryConfigured, true);
      assert.equal(enabled.postHarvestOutbox.attentionRequired, false);
      assert.equal(enabled.postHarvestOutbox.draining, true);
      assert.equal(enabled.postHarvestOutbox.lastSentAt, "2026-08-31T11:55:00.000Z");
    }

    insertBackgroundJob({
      id: "job-old", status: "QUEUED",
      createdAt: "2026-08-31T11:40:00.000Z", availableAt: "2026-08-31T11:40:00.000Z"
    });
    const oldBackgroundJob = readOperationalQueueHealth(db, false, { now });
    assert.equal(oldBackgroundJob.backgroundJobs.available, true);
    if (oldBackgroundJob.backgroundJobs.available) {
      assert.equal(oldBackgroundJob.backgroundJobs.claimableNowCount, 2);
      assert.equal(oldBackgroundJob.backgroundJobs.oldestClaimableAgeSeconds, 1200);
      assert.equal(oldBackgroundJob.backgroundJobs.attentionRequired, true);
    }
  });

  function insertBackgroundJob(input: {
    id: string;
    status: string;
    createdAt: string;
    availableAt: string;
    leaseExpiresAt?: string | null;
  }) {
    db.prepare(`
      INSERT INTO background_jobs (
        id, kind, dedupe_key, status, created_at, updated_at, available_at, lease_expires_at
      ) VALUES (?, 'RECONCILE_ORPHANS', ?, ?, ?::timestamptz, ?::timestamptz, ?::timestamptz, ?::timestamptz)
    `).run(
      input.id, input.id, input.status, input.createdAt,
      input.createdAt, input.availableAt, input.leaseExpiresAt ?? null
    );
  }

  function insertOutboxEvent(input: {
    id: string;
    status: string;
    createdAt: string;
    availableAt: string;
    leaseExpiresAt?: string | null;
    sentAt?: string | null;
  }) {
    db.prepare(`
      INSERT INTO post_harvest_integration_events (
        id, event_id, event_type, order_number, farm_name, field_code,
        payload_json, status, created_at, updated_at, available_at, lease_expires_at, sent_at
      ) VALUES (?, ?, 'POST_HARVEST_RELEASED', 'OS-TEST', 'Fazenda Teste', '01',
                '{}', ?, ?::timestamptz, ?::timestamptz, ?::timestamptz, ?::timestamptz, ?::timestamptz)
    `).run(
      input.id, input.id, input.status, input.createdAt,
      input.createdAt, input.availableAt, input.leaseExpiresAt ?? null, input.sentAt ?? null
    );
  }
}
