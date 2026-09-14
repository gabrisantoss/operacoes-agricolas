import assert from "node:assert/strict";
import os from "node:os";
import test, { after } from "node:test";
import type { Server } from "node:http";
import bcrypt from "bcryptjs";
import { createPostgresTestDatabase } from "./testSupport/postgresTestDatabase.js";

process.env.NODE_ENV = "test";
process.env.JWT_SECRET = "balanca-health-details-test-secret-with-more-than-48-characters";
process.env.UPLOAD_DIR = os.tmpdir();
process.env.POST_HARVEST_WEBHOOK_URL = "";
process.env.POST_HARVEST_WEBHOOK_TOKEN = "";
const testDatabaseUrl = process.env.BALANCA_TEST_DATABASE_URL?.trim();

if (!testDatabaseUrl) {
  test.skip("health details integration requires BALANCA_TEST_DATABASE_URL", () => {});
} else {
  const testDatabase = await createPostgresTestDatabase();
  const { createUser, db } = await import("./db.js");
  const { createApp } = await import("./app.js");
  const password = "senha-health-123";
  const passwordHash = await bcrypt.hash(password, 4);

  createUser({
    id: "health-admin",
    name: "Health Admin",
    email: "admin-health@example.invalid",
    passwordHash,
    role: "ADMIN",
    active: true
  });
  createUser({
    id: "health-viewer",
    name: "Health Viewer",
    email: "visitante@example.invalid",
    passwordHash,
    role: "VIEWER",
    active: true
  });

  const server = await listen(createApp());
  const address = server.address();
  if (!address || typeof address === "string") {
    throw new Error("Servidor de teste nao abriu uma porta TCP.");
  }
  const baseUrl = `http://127.0.0.1:${address.port}`;

  after(async () => {
    await new Promise<void>((resolve) => server.close(() => resolve()));
    await Promise.resolve(db.close?.());
    await testDatabase.cleanup();
  });

  test("public health remains minimal and anonymous", async () => {
    const response = await fetch(`${baseUrl}/health`);
    const payload = await response.json() as Record<string, unknown>;

    assert.equal(response.status, 200);
    assert.deepEqual(Object.keys(payload).sort(), ["ok", "service", "timestamp"]);
    assert.equal("checks" in payload, false);
  });

  test("health details keeps authentication and admin authorization", async () => {
    const anonymous = await fetch(`${baseUrl}/health/details`);
    assert.equal(anonymous.status, 401);

    const viewerToken = await login("visitante@example.invalid");
    const viewer = await fetch(`${baseUrl}/health/details`, {
      headers: { Authorization: `Bearer ${viewerToken}` }
    });
    assert.equal(viewer.status, 403);
  });

  test("admin health details includes the read-only persistent queue snapshot", async () => {
    db.prepare(`
      INSERT INTO post_harvest_integration_events (
        id, event_id, event_type, order_number, farm_name, field_code, payload_json, status
      ) VALUES ('health-pending', 'health-pending', 'POST_HARVEST_RELEASED',
                'OS-HEALTH', 'Fazenda Health', '01', '{}', 'PENDING')
    `).run();
    const adminToken = await login("admin-health@example.invalid");
    const response = await fetch(`${baseUrl}/health/details`, {
      headers: { Authorization: `Bearer ${adminToken}` }
    });
    const payload = await response.json() as {
      ok?: boolean;
      checks?: {
        persistentQueues?: {
          ok?: boolean;
          state?: string;
          configurationRequired?: boolean;
          backgroundJobs?: { counts?: Record<string, number> };
          postHarvestOutbox?: {
            counts?: Record<string, number>;
            deliveryConfigured?: boolean;
          };
        };
      };
    };

    assert.equal(response.status, 200);
    assert.equal(payload.ok, true);
    assert.equal(payload.checks?.persistentQueues?.ok, false);
    assert.equal(payload.checks?.persistentQueues?.state, "WAITING_CONFIGURATION");
    assert.equal(payload.checks?.persistentQueues?.configurationRequired, true);
    assert.equal(payload.checks?.persistentQueues?.backgroundJobs?.counts?.DEAD, 0);
    assert.equal(payload.checks?.persistentQueues?.postHarvestOutbox?.counts?.DEAD, 0);
    assert.equal(payload.checks?.persistentQueues?.postHarvestOutbox?.deliveryConfigured, false);
  });

  async function login(email: string) {
    const response = await fetch(`${baseUrl}/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password })
    });
    assert.equal(response.status, 200);
    const payload = await response.json() as { token?: string };
    assert.ok(payload.token);
    return payload.token;
  }

  function listen(app: ReturnType<typeof createApp>) {
    return new Promise<Server>((resolve, reject) => {
      const candidate = app.listen(0, "127.0.0.1", () => resolve(candidate));
      candidate.on("error", reject);
    });
  }
}
