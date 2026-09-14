import assert from "node:assert/strict";
import test from "node:test";
import { postHarvestFailureDisposition } from "./postHarvestIntegrationRepository.js";

test("post-harvest outbox retries with backoff and reaches dead-letter", () => {
  const now = new Date("2026-08-31T12:00:00.000Z");
  assert.deepEqual(postHarvestFailureDisposition(1, 3, now), {
    status: "ERROR", delayMs: 30_000, availableAt: "2026-08-31T12:00:30.000Z"
  });
  assert.equal(postHarvestFailureDisposition(2, 3, now).delayMs, 60_000);
  assert.deepEqual(postHarvestFailureDisposition(3, 3, now), {
    status: "DEAD", delayMs: 0, availableAt: now.toISOString()
  });
});
