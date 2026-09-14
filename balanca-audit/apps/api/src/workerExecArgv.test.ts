import assert from "node:assert/strict";
import test from "node:test";
import { getWorkerExecArgv } from "./workerExecArgv.js";

test("passes only TypeScript loader flags to workers", () => {
  assert.deepEqual(
    getWorkerExecArgv([
      "--use-largepages=off",
      "--require",
      "C:/tsx/preflight.cjs",
      "--import=file:///C:/tsx/loader.mjs",
      "--input-type=module",
      "--stack-trace-limit=10"
    ]),
    ["--require", "C:/tsx/preflight.cjs", "--import=file:///C:/tsx/loader.mjs"]
  );
});
