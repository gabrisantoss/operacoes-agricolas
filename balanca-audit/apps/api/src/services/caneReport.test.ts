import assert from "node:assert/strict";
import test from "node:test";
import { caneReportFilterSchema } from "@balanca/shared";
import type { CaneReportSourceRow } from "../db.js";
import { buildCaneReport, describePeriod } from "./caneReport.js";

const close = (actual: number | null | undefined, expected: number) =>
  assert.ok(actual !== null && actual !== undefined && Math.abs(actual - expected) < 1e-9, `${actual} != ${expected}`);

function row(partial: Partial<CaneReportSourceRow> & Pick<CaneReportSourceRow, "fieldId" | "fieldCode">): CaneReportSourceRow {
  return {
    farmId: "farm-a",
    farmCode: "100-901",
    farmName: "FAZENDA DEMO A",
    fieldName: null,
    areaHa: null,
    areaAlq: null,
    referenceDate: "2026-09-01",
    fieldHarvestFirstDate: null,
    fieldHarvestLastDate: null,
    entryCount: 0,
    okCount: 0,
    divergentCount: 0,
    totalNetWeight: 0,
    divergentNetWeight: 0,
    ...partial
  };
}

const fixture: CaneReportSourceRow[] = [
  row({ fieldId: "a1", fieldCode: "1", areaHa: 10, areaAlq: 4.132, referenceDate: "2026-09-01", entryCount: 3, okCount: 3, totalNetWeight: 90 }),
  row({ fieldId: "a1", fieldCode: "1", areaHa: 10, areaAlq: 4.132, referenceDate: "2026-09-02", entryCount: 2, okCount: 1, divergentCount: 1, totalNetWeight: 60, divergentNetWeight: 30 }),
  row({ fieldId: "a2", fieldCode: "2", referenceDate: "2026-09-01", entryCount: 1, okCount: 1, totalNetWeight: 25 }),
  row({
    farmId: "farm-b", farmCode: "200-100", farmName: "FAZENDA DEMO B", fieldId: "b1", fieldCode: "1",
    areaHa: 5, areaAlq: 2.066, referenceDate: "2026-09-02", entryCount: 4, okCount: 4, totalNetWeight: 120
  })
];

test("general report totals come from the same rows as farm and daily breakdowns", () => {
  const report = buildCaneReport(fixture, { type: "GENERAL" });

  assert.equal(report.isEmpty, false);
  assert.equal(report.totals.entryCount, 10);
  close(report.totals.totalNetWeight, 295);
  assert.equal(report.totals.divergentCount, 1);
  close(report.totals.divergentNetWeight, 30);
  assert.equal(report.totals.farmCount, 2);
  assert.equal(report.totals.fieldCount, 3);
  assert.equal(report.totals.deliveryDays, 2);
  assert.equal(report.totals.firstDate, "2026-09-01");
  assert.equal(report.totals.lastDate, "2026-09-02");
  close(report.totals.averageNetWeightPerEntry, 29.5);

  close(report.farms.reduce((total, farm) => total + farm.totalNetWeight, 0), report.totals.totalNetWeight);
  close(report.days.reduce((total, day) => total + day.totalNetWeight, 0), report.totals.totalNetWeight);
  assert.equal(report.days.reduce((total, day) => total + day.entryCount, 0), report.totals.entryCount);
  assert.deepEqual(report.days.map((day) => [day.date, day.entryCount, day.fieldCount, day.totalNetWeight, day.divergentNetWeight]), [
    ["2026-09-01", 4, 2, 115, 0],
    ["2026-09-02", 6, 2, 180, 30]
  ]);
  assert.deepEqual(report.fields, []);
});

test("TCH follows the harvest dashboard definition and reports area coverage", () => {
  const report = buildCaneReport(fixture, { type: "GENERAL" });
  const [farmA, farmB] = report.farms;

  close(report.totals.areaHa, 15);
  close(report.totals.tch, 295 / 15);
  close(report.totals.areaCoveragePercentage, (270 / 295) * 100);
  assert.equal(report.totals.fieldsWithoutArea, 1);

  assert.equal(farmA!.farmName, "FAZENDA DEMO A");
  assert.equal(farmA!.fieldCount, 2);
  close(farmA!.areaHa, 10);
  close(farmA!.tch, 17.5);
  close(farmA!.shareOfTotal, (175 / 295) * 100);
  close(farmB!.tch, 24);
  close(farmA!.shareOfTotal + farmB!.shareOfTotal, 100);
});

test("detailed report lists every field once with its own indicators", () => {
  const report = buildCaneReport(fixture, { type: "DETAILED" });

  assert.equal(report.title, "Relatório detalhado de safra por talhão");
  assert.deepEqual(report.days, []);
  assert.equal(report.fields.length, 3);

  const [a1, a2, b1] = report.fields;
  assert.equal(a1!.entryCount, 5);
  close(a1!.totalNetWeight, 150);
  close(a1!.averageNetWeightPerEntry, 30);
  close(a1!.tch, 15);
  assert.equal(a1!.deliveryDays, 2);
  assert.equal(a1!.firstDate, "2026-09-01");
  assert.equal(a1!.lastDate, "2026-09-02");
  assert.equal(a1!.divergentCount, 1);

  assert.equal(a2!.areaHa, null);
  assert.equal(a2!.tch, null);
  close(b1!.tch, 24);
  assert.equal(b1!.farmKey, report.farms[1]!.key);
  close(report.fields.reduce((total, field) => total + field.totalNetWeight, 0), report.totals.totalNetWeight);
});

test("fields with the same code on different farms stay separate", () => {
  const report = buildCaneReport(fixture, { type: "DETAILED" });

  assert.deepEqual(report.fields.map((field) => `${field.farmName}/${field.fieldCode}`), [
    "FAZENDA DEMO A/1",
    "FAZENDA DEMO A/2",
    "FAZENDA DEMO B/1"
  ]);
});

test("an empty selection produces an explicit empty report instead of invented values", () => {
  const report = buildCaneReport([], { type: "GENERAL", from: "2030-01-01", to: "2030-01-31" });

  assert.equal(report.isEmpty, true);
  assert.equal(report.totals.entryCount, 0);
  assert.equal(report.totals.totalNetWeight, 0);
  assert.equal(report.totals.averageNetWeightPerEntry, null);
  assert.equal(report.totals.tch, null);
  assert.equal(report.totals.firstDate, null);
  assert.deepEqual(report.farms, []);
  assert.deepEqual(report.days, []);
  assert.equal(report.filterLabels.period, "01/01/2030 a 31/01/2030");
});

test("filter labels describe empty filters and the selected farm and field", () => {
  assert.deepEqual(buildCaneReport(fixture, { type: "GENERAL" }).filterLabels, {
    farm: "Todas as fazendas",
    field: "Todos os talhões",
    period: "Todo o período"
  });
  assert.deepEqual(
    buildCaneReport(fixture, { type: "GENERAL", farmId: "farm-a", fieldId: "a1" }, { farmLabel: "100-901 - A", fieldLabel: "1" }).filterLabels,
    { farm: "100-901 - A", field: "1", period: "Todo o período" }
  );
  assert.equal(describePeriod("2026-09-01", undefined), "A partir de 01/09/2026");
  assert.equal(describePeriod(undefined, "2026-09-30"), "Até 30/09/2026");
});

// Same rows as the fixture, but carrying each field's full harvest span as returned by the query.
const withSpans = fixture.map((item) => ({
  ...item,
  fieldHarvestFirstDate: item.fieldId === "a1" ? "2026-09-01" : item.referenceDate,
  fieldHarvestLastDate: item.fieldId === "a1" ? "2026-09-02" : item.referenceDate
}));

test("a partial period shows N/D for area and TCH it cannot determine and keeps valid indicators", () => {
  const rowsInPeriod = withSpans.filter((item) => item.referenceDate! >= "2026-09-02");
  const report = buildCaneReport(rowsInPeriod, { type: "DETAILED", from: "2026-09-02" });
  const [a1, b1] = report.fields;

  assert.equal(a1!.tch, null);
  assert.equal(a1!.tchUnavailableReason, "PARTIAL_PERIOD");
  close(a1!.areaHa, 10);
  close(a1!.totalNetWeight, 60);
  assert.equal(b1!.tchUnavailableReason, null);
  close(b1!.tch, 24);

  assert.equal(report.farms[0]!.areaHa, null);
  assert.equal(report.farms[0]!.tch, null);
  assert.equal(report.farms[0]!.partialPeriodFieldCount, 1);
  close(report.farms[1]!.tch, 24);

  assert.equal(report.totals.areaHa, null);
  assert.equal(report.totals.tch, null);
  assert.equal(report.totals.partialPeriodFieldCount, 1);
  close(report.totals.totalNetWeight, 180);
  assert.equal(report.totals.entryCount, 6);
  assert.ok(report.notes.some((note) => note.startsWith("N/D: 1 talhão(ões) também têm entregas fora do período selecionado.")));
});

test("TCH stays available when every delivery of the field is inside the period", () => {
  const report = buildCaneReport(withSpans, { type: "DETAILED", from: "2026-09-01", to: "2026-09-02" });

  assert.equal(report.totals.partialPeriodFieldCount, 0);
  close(report.totals.areaHa, 15);
  close(report.totals.tch, 295 / 15);
  assert.equal(report.fields[0]!.tchUnavailableReason, null);
  assert.equal(report.fields[1]!.tchUnavailableReason, "NO_AREA");
  assert.ok(report.notes.some((note) => note.startsWith("1 talhão(ões) sem área cadastrada")));
  assert.ok(!report.notes.some((note) => note.startsWith("N/D:")));
});

test("without a period filter the report keeps the dashboard TCH definition", () => {
  const report = buildCaneReport(withSpans, { type: "GENERAL" });

  close(report.totals.tch, 295 / 15);
  assert.equal(report.totals.partialPeriodFieldCount, 0);
});

test("report filter contract normalizes empty values and rejects invalid periods", () => {
  const empty = caneReportFilterSchema.parse({ farmId: "", fieldId: " ", from: "", to: "" });
  assert.equal(empty.type, "GENERAL");
  assert.equal(empty.farmId, undefined);
  assert.equal(empty.fieldId, undefined);
  assert.equal(empty.from, undefined);
  assert.equal(empty.to, undefined);
  assert.equal(caneReportFilterSchema.parse({ type: "DETAILED", from: "2026-09-01", to: "2026-09-01" }).type, "DETAILED");
  assert.equal(caneReportFilterSchema.safeParse({ from: "2026-09-30", to: "2026-09-01" }).success, false);
  assert.equal(caneReportFilterSchema.safeParse({ from: "2026-02-30" }).success, false);
  assert.equal(caneReportFilterSchema.safeParse({ from: "01/09/2026" }).success, false);
  assert.equal(caneReportFilterSchema.safeParse({ type: "OTHER" }).success, false);
});
