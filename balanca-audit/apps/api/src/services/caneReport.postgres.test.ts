import assert from "node:assert/strict";
import { createRequire } from "node:module";
import test, { after, before } from "node:test";
import { createPostgresTestDatabase } from "../testSupport/postgresTestDatabase.js";

process.env.NODE_ENV = "test";
const testDatabaseUrl = process.env.BALANCA_TEST_DATABASE_URL?.trim();

if (!testDatabaseUrl) {
  test.skip("Cane report integration tests require BALANCA_TEST_DATABASE_URL", () => {});
} else {
  const testDatabase = await createPostgresTestDatabase();
  const { createCaneEntries, createFarm, createImportBatch, db, listCaneReportRows, listFarms } = await import("../db.js");
  const { loadCaneReport } = await import("../routes/reports.js");
  const { formatTons, renderCaneReportPdf } = await import("./caneReportPdf.js");
  const require = createRequire(import.meta.url);
  const pdfParse = require("pdf-parse") as (data: Buffer) => Promise<{ text: string }>;

  const ids = { farmA: "", farmB: "", fieldA1: "", fieldA2: "", fieldB1: "" };

  before(() => {
    createFarm({ code: "100-951", name: "FAZENDA RELATORIO AURORA", fields: [{ code: "1", areaAlq: 2 }, { code: "2" }] });
    createFarm({ code: "100-952", name: "FAZENDA RELATORIO CEDRO", fields: [{ code: "1", areaAlq: 1 }] });
    const farms = listFarms();
    const farmA = farms.find((farm) => farm.code === "100-951")!;
    const farmB = farms.find((farm) => farm.code === "100-952")!;
    ids.farmA = farmA.id;
    ids.farmB = farmB.id;
    ids.fieldA1 = farmA.fields.find((field) => field.code === "1")!.id;
    ids.fieldA2 = farmA.fields.find((field) => field.code === "2")!.id;
    ids.fieldB1 = farmB.fields[0]!.id;

    const batch = createImportBatch({ fileName: "relatorio-ficticio.csv", rowCount: 7, metadata: { sourceType: "CSV" } });
    assert.ok(batch, "lote ficticio nao foi criado");
    const entry = (day: string, farmId: string | undefined, fieldId: string | undefined, netWeight: number, status: "OK" | "FIELD_NOT_RELEASED" | "FARM_NOT_FOUND" = "OK") => ({
      batchId: batch.id,
      ticketNumber: `T-${day}-${netWeight}`,
      entryDate: new Date(`${day}T00:00:00.000Z`),
      farmId,
      fieldId,
      farmCodeRaw: farmId ? undefined : "300-999",
      farmNameRaw: farmId ? undefined : "FORNECEDOR SEM CADASTRO",
      fieldCodeRaw: fieldId ? undefined : "9",
      grossWeight: netWeight + 12,
      netWeight,
      status
    });

    createCaneEntries([
      entry("2026-09-01", ids.farmA, ids.fieldA1, 31.5),
      entry("2026-09-01", ids.farmA, ids.fieldA1, 30.25),
      entry("2026-09-02", ids.farmA, ids.fieldA2, 28, "FIELD_NOT_RELEASED"),
      entry("2026-09-02", ids.farmB, ids.fieldB1, 33.75),
      entry("2026-09-03", ids.farmB, ids.fieldB1, 32),
      entry("2026-09-05", ids.farmB, ids.fieldB1, 29.5),
      entry("2026-09-03", undefined, undefined, 27, "FARM_NOT_FOUND")
    ]);
  });

  after(async () => {
    await Promise.resolve(db.close?.());
    await testDatabase.cleanup();
  });

  test("unfiltered report reconciles with raw database totals", () => {
    const raw = db.prepare("SELECT COUNT(*) AS count, COALESCE(SUM(net_weight), 0) AS total FROM cane_entries").get() as {
      count: number | string;
      total: number | string;
    };
    const report = loadCaneReport({ type: "GENERAL" });

    assert.equal(report.totals.entryCount, Number(raw.count));
    assert.ok(Math.abs(report.totals.totalNetWeight - Number(raw.total)) < 1e-9);
    assert.equal(report.totals.entryCount, 7);
    assert.ok(Math.abs(report.totals.totalNetWeight - 212) < 1e-9);
    assert.equal(report.totals.farmCount, 3);
    assert.equal(report.totals.divergentCount, 2);
    assert.ok(report.farms.some((farm) => farm.farmName === "FORNECEDOR SEM CADASTRO"));
  });

  test("farm, field and period filters narrow the same query", () => {
    const farm = loadCaneReport({ type: "DETAILED", farmId: ids.farmB });
    assert.equal(farm.totals.entryCount, 3);
    assert.ok(Math.abs(farm.totals.totalNetWeight - 95.25) < 1e-9);
    assert.equal(farm.filterLabels.farm, "100-952 - FAZENDA RELATORIO CEDRO");

    const field = loadCaneReport({ type: "DETAILED", farmId: ids.farmA, fieldId: ids.fieldA1 });
    assert.equal(field.totals.entryCount, 2);
    assert.equal(field.fields.length, 1);
    assert.ok(Math.abs(field.fields[0]!.areaHa! - 4.84) < 1e-9);
    assert.ok(Math.abs(field.fields[0]!.tch! - 61.75 / 4.84) < 1e-9);

    const period = loadCaneReport({ type: "GENERAL", from: "2026-09-02", to: "2026-09-03" });
    assert.deepEqual(period.days.map((day) => day.date), ["2026-09-02", "2026-09-03"]);
    assert.equal(period.totals.entryCount, 4);

    const sameDay = listCaneReportRows({ from: "2026-09-05", to: "2026-09-05" });
    assert.deepEqual(sameDay.map((row) => [row.referenceDate, row.entryCount]), [["2026-09-05", 1]]);
  });

  test("a period without deliveries returns an empty report", () => {
    const report = loadCaneReport({ type: "GENERAL", farmId: ids.farmA, from: "2026-10-01", to: "2026-10-31" });

    assert.equal(report.isEmpty, true);
    assert.equal(report.totals.tch, null);
    assert.deepEqual(report.farms, []);
  });

  test("a field from another farm is rejected", () => {
    assert.throws(() => loadCaneReport({ type: "DETAILED", farmId: ids.farmA, fieldId: ids.fieldB1 }), /Talhao nao encontrado/);
    assert.throws(() => loadCaneReport({ type: "DETAILED", farmId: "nao-existe" }), /Fazenda nao encontrada/);
  });

  test("PDF printed from the stored data shows the preview totals", async () => {
    const preview = loadCaneReport({ type: "DETAILED", farmId: ids.farmA });
    const { text } = await pdfParse(await renderCaneReportPdf(loadCaneReport({ type: "DETAILED", farmId: ids.farmA })));

    assert.equal(formatTons(preview.totals.totalNetWeight), "89,750");
    assert.ok(text.includes("89,750"));
    assert.match(text, /FAZENDA RELATORIO AURORA/);
  });
}
