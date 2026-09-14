import assert from "node:assert/strict";
import test from "node:test";
import { backgroundJobFailureDisposition } from "./backgroundJobRepository.js";

test("background jobs use exponential retry and eventually enter dead-letter", () => {
  const now = new Date("2026-08-31T12:00:00.000Z");

  assert.deepEqual(backgroundJobFailureDisposition(1, 3, now), {
    status: "RETRY",
    delayMs: 5_000,
    availableAt: "2026-08-31T12:00:05.000Z"
  });
  assert.equal(backgroundJobFailureDisposition(2, 3, now).delayMs, 10_000);
  assert.deepEqual(backgroundJobFailureDisposition(3, 3, now), {
    status: "DEAD",
    delayMs: 0,
    availableAt: now.toISOString()
  });
});

test("background job backoff is capped", () => {
  const result = backgroundJobFailureDisposition(19, 20, new Date("2026-08-31T12:00:00.000Z"));
  assert.equal(result.status, "RETRY");
  assert.equal(result.delayMs, 30 * 60_000);
});
