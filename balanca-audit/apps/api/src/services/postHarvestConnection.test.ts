import assert from "node:assert/strict";
import test from "node:test";
import { hasRequiredPostHarvestDeliveryConfig } from "./postHarvestConnection.js";

test("post-harvest delivery requires both destination URL and bearer token", () => {
  assert.equal(hasRequiredPostHarvestDeliveryConfig({ url: "https://receiver.example/events", token: "secret" }), true);
  assert.equal(hasRequiredPostHarvestDeliveryConfig({ url: "https://receiver.example/events", token: "" }), false);
  assert.equal(hasRequiredPostHarvestDeliveryConfig({ url: "", token: "secret" }), false);
  assert.equal(hasRequiredPostHarvestDeliveryConfig({ url: "   ", token: "   " }), false);
});
