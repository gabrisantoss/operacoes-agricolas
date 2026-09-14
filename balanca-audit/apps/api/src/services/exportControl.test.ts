import assert from "node:assert/strict";
import test from "node:test";
import { assertExportRowLimit, ExportAdmissionGate, ExportController, exportCacheKey, isGeneratedExportPath } from "./exportControl.js";

test("export controller caches completed exports and keeps keys stable", async () => {
  const controller = new ExportController({
    maxConcurrent: 1, maxRequestsPerWindow: 5, rateWindowMs: 60_000,
    cacheTtlMs: 30_000, maxCacheEntries: 2, now: () => 1_000
  });
  let executions = 0;
  const input = { requestKey: "u:ip", cacheKey: exportCacheKey("pdf", { b: 2, a: 1 }, "u"), producer: () => ++executions };
  const first = await controller.run(input);
  const second = await controller.run(input);
  assert.deepEqual(first, { value: 1, cache: "MISS" });
  assert.deepEqual(second, { value: 1, cache: "HIT" });
  assert.equal(executions, 1);
  assert.equal(exportCacheKey("pdf", { a: 1, b: 2 }, "u"), input.cacheKey);
});

test("export controller rejects excess concurrency and request rate", async () => {
  let release!: () => void;
  const blocker = new Promise<void>((resolve) => { release = resolve; });
  const controller = new ExportController({
    maxConcurrent: 1, maxRequestsPerWindow: 2, rateWindowMs: 60_000,
    cacheTtlMs: 1, maxCacheEntries: 1, now: () => 2_000
  });
  const first = controller.run({ requestKey: "first", cacheKey: "a", producer: () => blocker });
  await assert.rejects(
    controller.run({ requestKey: "second", cacheKey: "b", producer: () => "b" }),
    (error: unknown) => error instanceof Error && /processamento/i.test(error.message)
  );
  release();
  await first;
  await controller.run({ requestKey: "rate", cacheKey: "c", producer: () => "c" });
  await controller.run({ requestKey: "rate", cacheKey: "c", producer: () => "c" });
  await assert.rejects(
    controller.run({ requestKey: "rate", cacheKey: "c", producer: () => "c" }),
    (error: unknown) => error instanceof Error && /limite temporario/i.test(error.message)
  );
});

test("row limit rejects an oversized export", () => {
  assert.doesNotThrow(() => assertExportRowLimit(20_000));
  assert.throws(() => assertExportRowLimit(20_001), /reduza o periodo/i);
});

test("global export admission covers generated routes and releases exactly once", () => {
  const gate = new ExportAdmissionGate({ maxConcurrent: 1, maxRequestsPerWindow: 2, rateWindowMs: 60_000, now: () => 10 });
  const release = gate.enter("user");
  assert.throws(() => gate.enter("other"), /processamento/i);
  release();
  release();
  assert.doesNotThrow(() => gate.enter("other")());
  assert.equal(isGeneratedExportPath("/dashboard/harvest-report.pdf?year=2026"), true);
  assert.equal(isGeneratedExportPath("/apportionment/export/all/excel"), true);
  assert.equal(isGeneratedExportPath("/fleet-reports/pdf", "POST"), true);
  assert.equal(isGeneratedExportPath("/fleet-reports/base/pdf"), true);
  assert.equal(isGeneratedExportPath("/imports/highlight-divergences", "POST"), true);
  assert.equal(isGeneratedExportPath("/imports/batches/batch-1/highlighted-file"), true);
  assert.equal(isGeneratedExportPath("/post-harvest-integrations/export-summary"), true);
  assert.equal(isGeneratedExportPath("/orders"), false);
});
