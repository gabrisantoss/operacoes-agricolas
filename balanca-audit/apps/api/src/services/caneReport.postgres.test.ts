import assert from "node:assert/strict";
import test, { after, before } from "node:test";
import { extractPdfText } from "../testSupport/pdfText.js";
import { createPostgresTestDatabase } from "../testSupport/postgresTestDatabase.js";

process.env.NODE_ENV = "test";
const testDatabaseUrl = process.env.BALANCA_TEST_DATABASE_URL?.trim();

if (!testDatabaseUrl) {
  test.skip("Cane report integration tests require BALANCA_TEST_DATABASE_URL", () => {});
} else {
  const testDatabase = await createPostgresTestDatabase();
  const {
    closeOrder,
    createCaneEntries,
    createFarm,
    createImportBatch,
    createOrder,
    db,
    getHarvestExecutiveDashboard,
    listCaneReportRows,
    listFarms
  } = await import("../db.js");
  const { loadCaneReport } = await import("../routes/reports.js");
  const { formatTons, renderCaneReportPdf } = await import("./caneReportPdf.js");

  const ids = { farmA: "", farmB: "", fieldA1: "", fieldA2: "", fieldB1: "" };

  // A1 harvested under closed order OS-A; A2 without order; B1 under active order OS-B; one supplier entry unlinked.
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

    const orderA = createOrder({ number: "OS-REL-A", frontNumbers: [41], farmId: ids.farmA, fieldIds: [ids.fieldA1], startDate: "2026-09-01" });
    const orderB = createOrder({ number: "OS-REL-B", frontNumbers: [42], farmId: ids.farmB, fieldIds: [ids.fieldB1], startDate: "2026-09-01" });
    assert.ok(orderA && orderB, "OS ficticias nao foram criadas");

    const batch = createImportBatch({ fileName: "relatorio-ficticio.csv", rowCount: 7, metadata: { sourceType: "CSV" } });
    assert.ok(batch, "lote ficticio nao foi criado");
    const entry = (
      day: string,
      farmId: string | undefined,
      fieldId: string | undefined,
      orderId: string | undefined,
      netWeight: number,
      status: "OK" | "FIELD_NOT_RELEASED" | "FARM_NOT_FOUND" = "OK"
    ) => ({
      batchId: batch.id,
      ticketNumber: `T-${day}-${netWeight}`,
      entryDate: new Date(`${day}T00:00:00.000Z`),
      farmId,
      fieldId,
      orderId,
      farmCodeRaw: farmId ? undefined : "300-999",
      farmNameRaw: farmId ? undefined : "FORNECEDOR SEM CADASTRO",
      fieldCodeRaw: fieldId ? undefined : "9",
      grossWeight: netWeight + 12,
      netWeight,
      status
    });

    createCaneEntries([
      entry("2026-09-01", ids.farmA, ids.fieldA1, orderA.id, 31.5),
      entry("2026-09-02", ids.farmA, ids.fieldA1, orderA.id, 30.25),
      entry("2026-09-02", ids.farmA, ids.fieldA2, undefined, 28, "FIELD_NOT_RELEASED"),
      entry("2026-09-02", ids.farmB, ids.fieldB1, orderB.id, 33.75),
      entry("2026-09-03", ids.farmB, ids.fieldB1, orderB.id, 32),
      entry("2026-09-05", ids.farmB, ids.fieldB1, orderB.id, 29.5),
      entry("2026-09-03", undefined, undefined, undefined, 27, "FARM_NOT_FOUND")
    ]);
    assert.equal(closeOrder(orderA.id)?.status, "CLOSED");
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
  });

  test("only the field of the closed order has proven harvested area", () => {
    const report = loadCaneReport({ type: "DETAILED" });
    const byField = new Map(report.fields.map((field) => [`${field.farmName}/${field.fieldCode}`, field]));
    const a1 = byField.get("FAZENDA RELATORIO AURORA/1")!;

    assert.equal(a1.evidence, "CLOSED_COMPLETE");
    assert.equal(a1.evidenceLabel, "OS OS-REL-A encerrada");
    assert.ok(Math.abs(a1.effectiveTch! - 61.75 / 4.84) < 1e-9);
    assert.equal(byField.get("FAZENDA RELATORIO AURORA/2")!.evidence, "NO_AREA");
    assert.equal(byField.get("FAZENDA RELATORIO CEDRO/1")!.evidence, "OPEN");
    assert.equal(byField.get("FORNECEDOR SEM CADASTRO/9")!.evidence, "NO_AREA");

    assert.ok(Math.abs(report.totals.registeredAreaHa - (4.84 + 2.42)) < 1e-9);
    assert.ok(Math.abs(report.totals.provenAreaHa - 4.84) < 1e-9);
    assert.ok(Math.abs(report.totals.effectiveTch! - 61.75 / 4.84) < 1e-9);
    assert.equal(report.totals.provenFieldCount, 1);
  });

  test("a period that cuts the closed order leaves its TCH unproven", () => {
    const clipped = loadCaneReport({ type: "DETAILED", farmId: ids.farmA, from: "2026-09-02", to: "2026-09-03" });
    const a1 = clipped.fields.find((field) => field.fieldCode === "1")!;

    assert.equal(a1.evidence, "CLOSED_CLIPPED");
    assert.equal(a1.effectiveTch, null);
    assert.equal(clipped.totals.effectiveTch, null);

    const whole = loadCaneReport({ type: "DETAILED", fieldId: ids.fieldA1, farmId: ids.farmA, from: "2026-09-01", to: "2026-09-02" });
    assert.equal(whole.fields[0]!.evidence, "CLOSED_COMPLETE");
  });

  test("an active order stays unproven even with every delivery inside the period", () => {
    const report = loadCaneReport({ type: "DETAILED", farmId: ids.farmB, from: "2026-09-01", to: "2026-09-30" });

    assert.equal(report.totals.entryCount, 3);
    assert.equal(report.fields[0]!.evidence, "OPEN");
    assert.equal(report.totals.effectiveTch, null);
    assert.ok(Math.abs(report.totals.registeredAreaHa - 2.42) < 1e-9);
  });

  test("filters narrow the same query and match the harvest dashboard volumes", () => {
    const period = loadCaneReport({ type: "GENERAL", from: "2026-09-02", to: "2026-09-03" });
    assert.deepEqual(period.days.map((day) => day.date), ["2026-09-02", "2026-09-03"]);
    assert.equal(period.totals.entryCount, 5);
    assert.deepEqual(listCaneReportRows({ from: "2026-09-05", to: "2026-09-05" }).map((row) => [row.referenceDate, row.entryCount]), [["2026-09-05", 1]]);

    const report = loadCaneReport({ type: "GENERAL" });
    const dashboard = getHarvestExecutiveDashboard({});
    const round = (value: number) => Math.round(value * 1000) / 1000;
    assert.equal(report.totals.entryCount, dashboard.totals.entries);
    assert.equal(report.totals.fieldCount, dashboard.totals.fields);
    assert.equal(round(report.totals.totalNetWeight), dashboard.totals.totalNetWeight);
    // Same registered area as the dashboard; the dashboard TCH divides all cane by it, the report does not.
    assert.equal(round(report.totals.registeredAreaHa), dashboard.totals.areaHa);
  });

  test("a period without deliveries returns an empty report", () => {
    const report = loadCaneReport({ type: "GENERAL", farmId: ids.farmA, from: "2026-10-01", to: "2026-10-31" });

    assert.equal(report.isEmpty, true);
    assert.equal(report.totals.effectiveTch, null);
    assert.deepEqual(report.farms, []);
  });

  test("a field from another farm is rejected", () => {
    assert.throws(() => loadCaneReport({ type: "DETAILED", farmId: ids.farmA, fieldId: ids.fieldB1 }), /Talhao nao encontrado/);
    assert.throws(() => loadCaneReport({ type: "DETAILED", farmId: "nao-existe" }), /Fazenda nao encontrada/);
  });

  test("PDF printed from the stored data shows the preview totals", async () => {
    const printed = { ...loadCaneReport({ type: "DETAILED", farmId: ids.farmA }), generatedAt: "2026-10-18T12:00:00.000Z" };
    const { text } = extractPdfText(await renderCaneReportPdf(printed));

    assert.equal(formatTons(printed.totals.totalNetWeight), "89,750");
    assert.ok(text.includes("89,750"));
    assert.match(text, /OS OS-REL-A encerrada/);
  });
}
