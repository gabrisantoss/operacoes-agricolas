import assert from "node:assert/strict";
import test from "node:test";
import { buildPostHarvestEventId } from "./postHarvestEvent.js";

test("post-harvest event id is explicitly versioned and deterministic", () => {
  assert.equal(
    buildPostHarvestEventId("OS 12/2026", "100-0001", "01 A"),
    "POSCOLHEITA-V1-OS122026-1000001-01A"
  );
});
