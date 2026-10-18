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
    orderId: null,
    orderNumber: null,
    closedOrderEndDate: null,
    closedOrderEntryCount: null,
    entryCount: 0,
    okCount: 0,
    divergentCount: 0,
    totalNetWeight: 0,
    divergentNetWeight: 0,
    ...partial
  };
}

// a1: closed order 9001 with 5 stored entries for the field; b1: active order 9002; a2: no area, no order.
const closedA1 = { orderId: "os-1", orderNumber: "9001", closedOrderEndDate: "2026-09-03", closedOrderEntryCount: 5 };
const fixture: CaneReportSourceRow[] = [
  row({ fieldId: "a1", fieldCode: "1", areaHa: 10, areaAlq: 4.132, referenceDate: "2026-09-01", entryCount: 3, okCount: 3, totalNetWeight: 90, ...closedA1 }),
  row({ fieldId: "a1", fieldCode: "1", areaHa: 10, areaAlq: 4.132, referenceDate: "2026-09-02", entryCount: 2, okCount: 1, divergentCount: 1, totalNetWeight: 60, divergentNetWeight: 30, ...closedA1 }),
  row({ fieldId: "a2", fieldCode: "2", referenceDate: "2026-09-01", entryCount: 1, okCount: 1, totalNetWeight: 25 }),
  row({
    farmId: "farm-b", farmCode: "200-100", farmName: "FAZENDA DEMO B", fieldId: "b1", fieldCode: "1",
    areaHa: 5, areaAlq: 2.066, referenceDate: "2026-09-02", entryCount: 4, okCount: 4, totalNetWeight: 120,
    orderId: "os-2", orderNumber: "9002"
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
  close(report.totals.averageNetWeightPerEntry, 29.5);
  close(report.farms.reduce((total, farm) => total + farm.totalNetWeight, 0), report.totals.totalNetWeight);
  close(report.days.reduce((total, day) => total + day.totalNetWeight, 0), report.totals.totalNetWeight);
  assert.deepEqual(report.days.map((day) => [day.date, day.entryCount, day.fieldCount, day.totalNetWeight, day.divergentNetWeight]), [
    ["2026-09-01", 4, 2, 115, 0],
    ["2026-09-02", 6, 2, 180, 30]
  ]);
  assert.deepEqual(report.fields, []);
});

test("registered area is not harvested area and effective TCH uses only proven fields", () => {
  const report = buildCaneReport(fixture, { type: "GENERAL" });
  const [farmA, farmB] = report.farms;

  close(report.totals.registeredAreaHa, 15);
  close(report.totals.provenAreaHa, 10);
  assert.equal(report.totals.provenFieldCount, 1);
  close(report.totals.provenNetWeight, 150);
  close(report.totals.effectiveTch, 15);
  assert.deepEqual(report.totals.evidenceCounts, { CLOSED_COMPLETE: 1, CLOSED_CLIPPED: 0, OPEN: 1, MIXED: 0, NO_AREA: 1 });

  close(farmA!.registeredAreaHa, 10);
  close(farmA!.effectiveTch, 15);
  close(farmB!.registeredAreaHa, 5);
  assert.equal(farmB!.provenAreaHa, 0);
  assert.equal(farmB!.effectiveTch, null);
  assert.ok(report.notes.some((note) => note.startsWith("TCH efetivo parcial: calculado só com 1 de 3 talhões (150,000 t de 295,000 t).")));
  assert.ok(report.notes.some((note) => note.includes("1 sem OS encerrada; 1 sem área cadastrada")));
});

test("detailed report shows the harvest evidence of every field", () => {
  const report = buildCaneReport(fixture, { type: "DETAILED" });
  const [a1, a2, b1] = report.fields;

  assert.equal(a1!.evidence, "CLOSED_COMPLETE");
  assert.equal(a1!.evidenceLabel, "OS 9001 encerrada");
  close(a1!.effectiveTch, 15);
  close(a1!.registeredAreaHa, 10);
  assert.equal(a1!.deliveryDays, 2);
  assert.equal(a2!.evidence, "NO_AREA");
  assert.equal(a2!.registeredAreaHa, null);
  assert.equal(a2!.effectiveTch, null);
  assert.equal(b1!.evidence, "OPEN");
  assert.equal(b1!.evidenceLabel, "Sem OS encerrada");
  assert.equal(b1!.effectiveTch, null);
  close(b1!.registeredAreaHa, 5);
});

test("deliveries all inside the period do not prove a finished harvest", () => {
  const onlyB1 = fixture.filter((item) => item.fieldId === "b1");
  const report = buildCaneReport(onlyB1, { type: "DETAILED", from: "2026-09-01", to: "2026-09-30" });

  assert.equal(report.fields[0]!.evidence, "OPEN");
  assert.equal(report.totals.effectiveTch, null);
  assert.equal(report.totals.provenAreaHa, 0);
  close(report.totals.registeredAreaHa, 5);
  assert.ok(report.notes.some((note) => note.startsWith("TCH efetivo N/D: nenhum dos 1 talhão(ões) tem colheita comprovada no recorte (1 sem OS encerrada).")));
});

test("a closed order with entries outside the report is not proven", () => {
  const clipped = fixture.filter((item) => item.fieldId === "a1" && item.referenceDate === "2026-09-02");
  const report = buildCaneReport(clipped, { type: "DETAILED", from: "2026-09-02" });

  assert.equal(report.fields[0]!.evidence, "CLOSED_CLIPPED");
  assert.equal(report.fields[0]!.evidenceLabel, "OS 9001 encerrada fora do recorte");
  assert.equal(report.fields[0]!.effectiveTch, null);
  assert.equal(report.totals.effectiveTch, null);
});

test("entries from more than one order are not proven", () => {
  const mixed = [
    ...fixture.filter((item) => item.fieldId === "a1"),
    row({ fieldId: "a1", fieldCode: "1", areaHa: 10, areaAlq: 4.132, referenceDate: "2026-09-04", entryCount: 1, okCount: 1, totalNetWeight: 20 })
  ];
  const report = buildCaneReport(mixed, { type: "DETAILED" });

  assert.equal(report.fields[0]!.evidence, "MIXED");
  assert.equal(report.fields[0]!.evidenceLabel, "Parte das entregas sem OS");
  assert.equal(report.totals.effectiveTch, null);

  const twoOrders = [
    ...fixture.filter((item) => item.fieldId === "a1"),
    row({ fieldId: "a1", fieldCode: "1", areaHa: 10, areaAlq: 4.132, referenceDate: "2026-09-04", entryCount: 1, okCount: 1, totalNetWeight: 20, orderId: "os-3", orderNumber: "9003" })
  ];
  assert.equal(buildCaneReport(twoOrders, { type: "DETAILED" }).fields[0]!.evidenceLabel, "Mais de uma OS");
});

test("effective TCH is not marked partial when every field is proven", () => {
  const report = buildCaneReport(fixture.filter((item) => item.fieldId === "a1"), { type: "GENERAL" });

  close(report.totals.effectiveTch, 15);
  assert.equal(report.totals.provenFieldCount, report.totals.fieldCount);
  assert.ok(!report.notes.some((note) => note.startsWith("TCH efetivo parcial") || note.startsWith("TCH efetivo N/D")));
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
  assert.equal(report.totals.averageNetWeightPerEntry, null);
  assert.equal(report.totals.effectiveTch, null);
  assert.equal(report.totals.firstDate, null);
  assert.deepEqual(report.farms, []);
  assert.deepEqual(report.notes, []);
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
