import assert from "node:assert/strict";
import test from "node:test";
import { internalHealthResponse, publicHealthResponse } from "./healthResponse.js";

test("advisory telemetry can degrade without changing the core health status", () => {
  const response = internalHealthResponse({
    service: "balanca-api",
    timestamp: "2026-08-31T12:00:00.000Z",
    uptimeSeconds: 10,
    coreChecks: {
      database: { ok: true },
      disk: { ok: true }
    },
    advisoryChecks: {
      persistentQueues: { ok: false, degraded: true, message: "telemetry unavailable" }
    }
  });

  assert.equal(response.ok, true);
  assert.deepEqual(response.checks.persistentQueues, {
    ok: false,
    degraded: true,
    message: "telemetry unavailable"
  });
});

test("a failed core check still marks the service unhealthy", () => {
  const response = internalHealthResponse({
    service: "balanca-api",
    timestamp: "2026-08-31T12:00:00.000Z",
    uptimeSeconds: 10,
    coreChecks: {
      database: { ok: false },
      disk: { ok: true }
    },
    advisoryChecks: {
      persistentQueues: { ok: true }
    }
  });

  assert.equal(response.ok, false);
});

test("public health omits operational and database details", () => {
  const response = publicHealthResponse({
    ok: false,
    service: "balanca-api",
    timestamp: "2026-08-31T12:00:00.000Z",
    uptimeSeconds: 10,
    checks: { database: { ok: false, target: "sensitive-target", message: "internal error" } }
  });

  assert.deepEqual(response, {
    ok: false,
    service: "balanca-api",
    timestamp: "2026-08-31T12:00:00.000Z"
  });
  assert.equal("checks" in response, false);
  assert.equal("uptimeSeconds" in response, false);
});
