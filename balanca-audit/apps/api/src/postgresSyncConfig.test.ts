import assert from "node:assert/strict";
import test from "node:test";
import { readBoundedPositiveInteger } from "./postgresSync.js";

test("uses the fallback for invalid or out-of-range PostgreSQL worker settings", () => {
  const name = "BALANCA_TEST_BOUNDED_INTEGER";
  const original = process.env[name];

  try {
    process.env[name] = "not-a-number";
    assert.equal(readBoundedPositiveInteger(name, 3, 1, 8), 3);

    process.env[name] = "0";
    assert.equal(readBoundedPositiveInteger(name, 3, 1, 8), 3);

    process.env[name] = "9";
    assert.equal(readBoundedPositiveInteger(name, 3, 1, 8), 3);

    process.env[name] = "4";
    assert.equal(readBoundedPositiveInteger(name, 3, 1, 8), 4);
  } finally {
    if (original === undefined) {
      delete process.env[name];
    } else {
      process.env[name] = original;
    }
  }
});
