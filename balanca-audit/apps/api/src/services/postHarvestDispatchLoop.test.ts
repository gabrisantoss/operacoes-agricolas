import assert from "node:assert/strict";
import test from "node:test";
import { dispatchClaimedItemsOneAtATime, normalizeDispatchLimit } from "./postHarvestDispatchLoop.js";

test("claims each outbox item immediately before dispatching it", async () => {
  const pending = ["first", "second", "third"];
  const actions: string[] = [];

  const results = await dispatchClaimedItemsOneAtATime({
    limit: 3,
    claimOne() {
      const item = pending.shift() ?? null;
      actions.push(`claim:${item ?? "none"}`);
      return item;
    },
    async dispatchOne(item) {
      actions.push(`dispatch:${item}`);
      return item.toUpperCase();
    }
  });

  assert.deepEqual(results, ["FIRST", "SECOND", "THIRD"]);
  assert.deepEqual(actions, [
    "claim:first",
    "dispatch:first",
    "claim:second",
    "dispatch:second",
    "claim:third",
    "dispatch:third"
  ]);
});

test("stops when no item is claimable and bounds the requested batch", async () => {
  let claims = 0;
  const results = await dispatchClaimedItemsOneAtATime({
    limit: 50,
    claimOne() {
      claims += 1;
      return null;
    },
    dispatchOne() {
      throw new Error("dispatch should not run");
    }
  });

  assert.deepEqual(results, []);
  assert.equal(claims, 1);
  assert.equal(normalizeDispatchLimit(Number.NaN), 50);
  assert.equal(normalizeDispatchLimit(-10), 1);
  assert.equal(normalizeDispatchLimit(5_000), 500);
});
