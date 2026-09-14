import assert from "node:assert/strict";
import test from "node:test";
import {
  defaultApiHost,
  isLoopbackAddress,
  localAccessIsAllowed,
  localAccessIsConfiguredForDevelopment,
  resolveApiHost
} from "./runtimeSecurity.js";

test("API host defaults to loopback", () => {
  assert.equal(resolveApiHost(undefined), defaultApiHost);
  assert.equal(resolveApiHost("  "), defaultApiHost);
  assert.equal(resolveApiHost(" 0.0.0.0 "), "0.0.0.0");
});

test("local access requires both loopback bind and loopback client", () => {
  assert.equal(localAccessIsAllowed({ configured: true, apiHost: "127.0.0.1", remoteAddress: "127.0.0.1" }), true);
  assert.equal(localAccessIsAllowed({ configured: true, apiHost: "localhost", remoteAddress: "::1" }), true);
  assert.equal(localAccessIsAllowed({ configured: true, apiHost: "127.0.0.1", remoteAddress: "::ffff:127.0.0.1" }), true);
  assert.equal(localAccessIsAllowed({ configured: true, apiHost: "0.0.0.0", remoteAddress: "127.0.0.1" }), false);
  assert.equal(localAccessIsAllowed({ configured: true, apiHost: "127.0.0.1", remoteAddress: "192.0.2.10" }), false);
  assert.equal(localAccessIsAllowed({ configured: false, apiHost: "127.0.0.1", remoteAddress: "127.0.0.1" }), false);
  assert.equal(isLoopbackAddress("127.25.1.8"), true);
});

test("local access configuration is ignored outside an explicit development runtime", () => {
  assert.equal(localAccessIsConfiguredForDevelopment({ requested: true, nodeEnv: "development" }), true);
  assert.equal(localAccessIsConfiguredForDevelopment({ requested: true, npmLifecycleEvent: "dev" }), true);
  assert.equal(localAccessIsConfiguredForDevelopment({ requested: true, nodeEnv: "production", npmLifecycleEvent: "start" }), false);
  assert.equal(localAccessIsConfiguredForDevelopment({ requested: true }), false);
  assert.equal(localAccessIsConfiguredForDevelopment({ requested: false, nodeEnv: "development" }), false);
});
