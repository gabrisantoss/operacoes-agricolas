import assert from "node:assert/strict";
import test from "node:test";
import { assertDemoDatabaseTarget } from "./demoSafety.js";

test("accepts only the dedicated local demonstration cluster", () => {
  assert.doesNotThrow(() => assertDemoDatabaseTarget("postgresql://oa_demo@127.0.0.1:55439/oa_demo_tests"));
  for (const url of [
    "postgresql://oa_demo@127.0.0.1:5432/oa_demo_tests",
    "postgresql://oa_demo@192.0.2.10:55439/oa_demo_tests",
    "postgresql://oa_demo@127.0.0.1:55439/production",
    "https://127.0.0.1:55439/oa_demo_tests"
  ]) assert.throws(() => assertDemoDatabaseTarget(url), /Demonstracao isolada/);
});
