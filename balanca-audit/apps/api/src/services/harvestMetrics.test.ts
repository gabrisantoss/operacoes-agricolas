import assert from "node:assert/strict";
import test from "node:test";
import { dashboardFilterSchema } from "@balanca/shared";
import type { FieldProductionRow } from "../db.js";
import {
  calculateHarvestAreaCoverage,
  classifyHarvestFarmOwnership,
  consolidateFieldProductionRows,
  harvestFarmIdentity,
  harvestYearRange,
  rankHarvestPeriods,
  summarizeUniqueHarvestAreaByDate,
  tonsPerHectare
} from "./harvestMetrics.js";

test("daily harvested area counts each field once on its first observed day", () => {
  const result = summarizeUniqueHarvestAreaByDate([
    observation("2026-08-01", "field-1", 10, false),
    observation("2026-08-01", "field-1", 10, false),
    observation("2026-08-02", "field-1", 10, true),
    observation("2026-08-02", "field-2", 25, false)
  ]);

  assert.equal(result.length, 2);
  assert.deepEqual(
    result.map(({ date, fieldCount, areaHa, divergentFieldCount, cumulativeAreaHa }) => ({
      date,
      fieldCount,
      areaHa,
      divergentFieldCount,
      cumulativeAreaHa
    })),
    [
      { date: "2026-08-01", fieldCount: 1, areaHa: 10, divergentFieldCount: 1, cumulativeAreaHa: 10 },
      { date: "2026-08-02", fieldCount: 1, areaHa: 25, divergentFieldCount: 0, cumulativeAreaHa: 35 }
    ]
  );
  assert.ok(Math.abs(result[1]!.cumulativeAreaAlq - 35 / 2.42) < 1e-9);
});

test("duplicate SQL groups for one field do not multiply area or depress TCH", () => {
  const rows = consolidateFieldProductionRows([
    productionRow(303.84, 10, "FAZENDA A"),
    productionRow(538.38, 10, "Fazenda A")
  ]);

  assert.equal(rows.length, 1);
  assert.equal(rows[0]!.totalNetWeight, 842.22);
  assert.equal(rows[0]!.areaHa, 10);
  assert.ok(Math.abs(tonsPerHectare(rows[0]!.totalNetWeight, rows[0]!.areaHa!)! - 84.222) < 1e-9);
});

test("raw farm code classifies suppliers and keeps one identity across name and punctuation variants", () => {
  const first = productionRow(40, 0, "FORNECEDOR UM", {
    farmId: null,
    farmCode: "220-026",
    fieldId: null,
    fieldCode: "07",
    areaAlq: null
  });
  const second = productionRow(60, 0, "Fornecedor 1", {
    farmId: null,
    farmCode: "220 026",
    fieldId: null,
    fieldCode: "07",
    areaAlq: null
  });

  assert.equal(classifyHarvestFarmOwnership(first.farmCode), "SUPPLIER");
  assert.equal(harvestFarmIdentity(first), harvestFarmIdentity(second));

  const consolidated = consolidateFieldProductionRows([first, second]);
  assert.equal(consolidated.length, 1);
  assert.equal(consolidated[0]!.totalNetWeight, 100);
});

test("area coverage reports missing links without removing received weight from TCH", () => {
  const linked = productionRow(100, 10, "FAZENDA A", { entryCount: 2 });
  const missing = productionRow(40, 0, "FAZENDA B", {
    farmId: null,
    farmCode: "220-001",
    farmName: "FAZENDA B",
    fieldId: null,
    fieldCode: "03",
    areaAlq: null,
    entryCount: 3
  });
  const partial = productionRow(10, 2, "FAZENDA C", {
    farmId: null,
    farmCode: "220-002",
    farmName: "FAZENDA C",
    fieldId: null,
    fieldCode: "04",
    areaAlq: null,
    entryCount: 1
  });

  const coverage = calculateHarvestAreaCoverage([linked, missing, partial]);
  assert.deepEqual(coverage, {
    netWeightWithArea: 100,
    netWeightWithoutArea: 50,
    areaCoveragePercentage: (100 / 150) * 100,
    entriesWithoutArea: 4,
    fieldsWithoutArea: 2
  });
  assert.equal(tonsPerHectare(150, 10), 15);
});

test("harvest year filter accepts the selected year and builds its inclusive range", () => {
  const filters = dashboardFilterSchema.parse({ year: "2026" });
  assert.equal(filters.year, 2026);
  assert.deepEqual(harvestYearRange(filters.year), { start: "2026-01-01", end: "2026-12-31" });
  assert.equal(dashboardFilterSchema.safeParse({ year: "2026.5" }).success, false);
});

test("period ranking keeps batches that span more than one day", () => {
  const ranked = rankHarvestPeriods([
    { periodStart: "2026-05-02", periodEnd: "2026-05-02", totalNetWeight: 25 },
    { periodStart: "2026-04-28", periodEnd: "2026-05-01", totalNetWeight: 80 }
  ]);

  assert.equal(ranked.length, 2);
  assert.deepEqual(ranked[0], {
    periodStart: "2026-04-28",
    periodEnd: "2026-05-01",
    totalNetWeight: 80
  });
});

function observation(date: string, fieldId: string, areaHa: number, hasDivergence: boolean) {
  return { date, fieldId, areaHa, areaAlq: areaHa / 2.42, hasDivergence };
}

function productionRow(
  totalNetWeight: number,
  areaHa: number,
  farmName: string,
  patch: Partial<FieldProductionRow> = {}
): FieldProductionRow {
  return {
    farmId: "farm-1",
    farmCode: "100-001",
    farmName,
    fieldId: "field-1",
    fieldCode: "01",
    fieldName: null,
    areaHa,
    areaAlq: areaHa / 2.42,
    entryCount: 1,
    okCount: 1,
    divergentCount: 0,
    totalNetWeight,
    okNetWeight: totalNetWeight,
    divergentNetWeight: 0,
    firstReportDate: "2026-08-01",
    lastReportDate: "2026-08-02",
    lastImportedAt: "2026-08-02T12:00:00.000Z",
    ...patch
  };
}
