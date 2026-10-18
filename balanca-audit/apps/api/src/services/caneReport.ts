import type { CaneReportFilterInput, CaneReportType } from "@balanca/shared";
import type { CaneReportSourceRow, FieldProductionRow } from "../db.js";
import {
  calculateHarvestAreaCoverage,
  harvestFarmIdentity,
  harvestFieldIdentity,
  hasCompleteHarvestArea,
  tonsPerHectare
} from "./harvestMetrics.js";

export type CaneReportTotals = {
  farmCount: number;
  fieldCount: number;
  entryCount: number;
  okCount: number;
  divergentCount: number;
  totalNetWeight: number;
  divergentNetWeight: number;
  averageNetWeightPerEntry: number | null;
  deliveryDays: number;
  firstDate: string | null;
  lastDate: string | null;
  areaHa: number;
  tch: number | null;
  areaCoveragePercentage: number;
  fieldsWithoutArea: number;
};

export type CaneReportFarmRow = {
  key: string;
  farmCode: string | null;
  farmName: string;
  fieldCount: number;
  entryCount: number;
  divergentCount: number;
  totalNetWeight: number;
  shareOfTotal: number;
  areaHa: number;
  tch: number | null;
  firstDate: string | null;
  lastDate: string | null;
};

export type CaneReportFieldRow = {
  key: string;
  farmKey: string;
  farmCode: string | null;
  farmName: string;
  fieldCode: string;
  fieldName: string | null;
  areaHa: number | null;
  entryCount: number;
  divergentCount: number;
  totalNetWeight: number;
  averageNetWeightPerEntry: number | null;
  tch: number | null;
  deliveryDays: number;
  firstDate: string | null;
  lastDate: string | null;
};

export type CaneReportDayRow = {
  date: string;
  entryCount: number;
  fieldCount: number;
  totalNetWeight: number;
  divergentNetWeight: number;
};

export type CaneReport = {
  type: CaneReportType;
  title: string;
  filters: Pick<CaneReportFilterInput, "farmId" | "fieldId" | "from" | "to">;
  filterLabels: { farm: string; field: string; period: string };
  generatedAt: string;
  isEmpty: boolean;
  totals: CaneReportTotals;
  farms: CaneReportFarmRow[];
  fields: CaneReportFieldRow[];
  days: CaneReportDayRow[];
};

export type CaneReportContext = {
  farmLabel?: string;
  fieldLabel?: string;
  generatedAt?: Date;
};

export const caneReportTitles: Record<CaneReportType, string> = {
  GENERAL: "Relatório geral de safra",
  DETAILED: "Relatório detalhado de safra por talhão"
};

type FieldAccumulator = Omit<CaneReportFieldRow, "averageNetWeightPerEntry" | "tch" | "deliveryDays"> & {
  areaAlq: number | null;
  okCount: number;
  divergentNetWeight: number;
  dates: Set<string>;
};

export function buildCaneReport(
  rows: CaneReportSourceRow[],
  filters: CaneReportFilterInput,
  context: CaneReportContext = {}
): CaneReport {
  const fields = new Map<string, FieldAccumulator>();
  const days = new Map<string, CaneReportDayRow & { fieldKeys: Set<string> }>();

  for (const row of rows) {
    const fieldKey = harvestFieldIdentity(row);
    const field = fields.get(fieldKey) ?? {
      key: fieldKey,
      farmKey: harvestFarmIdentity(row),
      farmCode: row.farmCode,
      farmName: row.farmName,
      fieldCode: row.fieldCode,
      fieldName: row.fieldName,
      areaHa: row.areaHa,
      areaAlq: row.areaAlq,
      entryCount: 0,
      okCount: 0,
      divergentCount: 0,
      totalNetWeight: 0,
      divergentNetWeight: 0,
      firstDate: null,
      lastDate: null,
      dates: new Set<string>()
    };

    field.entryCount += row.entryCount;
    field.okCount += row.okCount;
    field.divergentCount += row.divergentCount;
    field.totalNetWeight += row.totalNetWeight;
    field.divergentNetWeight += row.divergentNetWeight;
    field.areaHa ??= row.areaHa;
    field.areaAlq ??= row.areaAlq;

    if (row.referenceDate) {
      field.dates.add(row.referenceDate);
      field.firstDate = earliest(field.firstDate, row.referenceDate);
      field.lastDate = latest(field.lastDate, row.referenceDate);

      const day = days.get(row.referenceDate) ?? {
        date: row.referenceDate,
        entryCount: 0,
        fieldCount: 0,
        totalNetWeight: 0,
        divergentNetWeight: 0,
        fieldKeys: new Set<string>()
      };
      day.entryCount += row.entryCount;
      day.totalNetWeight += row.totalNetWeight;
      day.divergentNetWeight += row.divergentNetWeight;
      day.fieldKeys.add(fieldKey);
      days.set(row.referenceDate, day);
    }

    fields.set(fieldKey, field);
  }

  const fieldRows = [...fields.values()].sort(
    (left, right) =>
      left.farmName.localeCompare(right.farmName, "pt-BR", { numeric: true }) ||
      left.fieldCode.localeCompare(right.fieldCode, "pt-BR", { numeric: true })
  );
  const totalNetWeight = sum(fieldRows, (field) => field.totalNetWeight);
  const farms = new Map<string, CaneReportFarmRow>();

  for (const field of fieldRows) {
    const farm = farms.get(field.farmKey) ?? {
      key: field.farmKey,
      farmCode: field.farmCode,
      farmName: field.farmName,
      fieldCount: 0,
      entryCount: 0,
      divergentCount: 0,
      totalNetWeight: 0,
      shareOfTotal: 0,
      areaHa: 0,
      tch: null,
      firstDate: null,
      lastDate: null
    };

    farm.fieldCount += 1;
    farm.entryCount += field.entryCount;
    farm.divergentCount += field.divergentCount;
    farm.totalNetWeight += field.totalNetWeight;
    farm.areaHa += hasCompleteHarvestArea(field) ? field.areaHa! : 0;
    farm.firstDate = earliest(farm.firstDate, field.firstDate);
    farm.lastDate = latest(farm.lastDate, field.lastDate);
    farms.set(field.farmKey, farm);
  }

  const farmRows = [...farms.values()].map((farm) => ({
    ...farm,
    shareOfTotal: totalNetWeight > 0 ? (farm.totalNetWeight / totalNetWeight) * 100 : 0,
    tch: tonsPerHectare(farm.totalNetWeight, farm.areaHa)
  }));
  const coverage = calculateHarvestAreaCoverage(fieldRows.map(toProductionRow));
  const entryCount = sum(fieldRows, (field) => field.entryCount);
  const areaHa = sum(farmRows, (farm) => farm.areaHa);
  const dayRows = [...days.values()]
    .sort((left, right) => left.date.localeCompare(right.date))
    .map(({ fieldKeys, ...day }) => ({ ...day, fieldCount: fieldKeys.size }));
  const type = filters.type ?? "GENERAL";

  return {
    type,
    title: caneReportTitles[type],
    filters: { farmId: filters.farmId, fieldId: filters.fieldId, from: filters.from, to: filters.to },
    filterLabels: {
      farm: filters.farmId ? context.farmLabel ?? filters.farmId : "Todas as fazendas",
      field: filters.fieldId ? context.fieldLabel ?? filters.fieldId : "Todos os talhões",
      period: describePeriod(filters.from, filters.to)
    },
    generatedAt: (context.generatedAt ?? new Date()).toISOString(),
    isEmpty: entryCount === 0,
    totals: {
      farmCount: farmRows.length,
      fieldCount: fieldRows.length,
      entryCount,
      okCount: sum(fieldRows, (field) => field.okCount),
      divergentCount: sum(fieldRows, (field) => field.divergentCount),
      totalNetWeight,
      divergentNetWeight: sum(fieldRows, (field) => field.divergentNetWeight),
      averageNetWeightPerEntry: entryCount > 0 ? totalNetWeight / entryCount : null,
      deliveryDays: dayRows.length,
      firstDate: dayRows[0]?.date ?? null,
      lastDate: dayRows.at(-1)?.date ?? null,
      areaHa,
      tch: tonsPerHectare(totalNetWeight, areaHa),
      areaCoveragePercentage: coverage.areaCoveragePercentage,
      fieldsWithoutArea: coverage.fieldsWithoutArea
    },
    farms: farmRows,
    fields: type === "DETAILED" ? fieldRows.map(toFieldRow) : [],
    days: type === "GENERAL" ? dayRows : []
  };
}

export function describePeriod(from: string | undefined, to: string | undefined) {
  if (from && to) return `${formatReportDate(from)} a ${formatReportDate(to)}`;
  if (from) return `A partir de ${formatReportDate(from)}`;
  if (to) return `Até ${formatReportDate(to)}`;
  return "Todo o período";
}

export function formatReportDate(value: string | null | undefined) {
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(value ?? "");
  return match ? `${match[3]}/${match[2]}/${match[1]}` : "-";
}

function toFieldRow(field: FieldAccumulator): CaneReportFieldRow {
  const hasArea = hasCompleteHarvestArea(field);

  return {
    key: field.key,
    farmKey: field.farmKey,
    farmCode: field.farmCode,
    farmName: field.farmName,
    fieldCode: field.fieldCode,
    fieldName: field.fieldName,
    areaHa: hasArea ? field.areaHa : null,
    entryCount: field.entryCount,
    divergentCount: field.divergentCount,
    totalNetWeight: field.totalNetWeight,
    averageNetWeightPerEntry: field.entryCount > 0 ? field.totalNetWeight / field.entryCount : null,
    tch: hasArea ? tonsPerHectare(field.totalNetWeight, field.areaHa!) : null,
    deliveryDays: field.dates.size,
    firstDate: field.firstDate,
    lastDate: field.lastDate
  };
}

function toProductionRow(field: FieldAccumulator): FieldProductionRow {
  return {
    farmId: null,
    farmCode: field.farmCode,
    farmName: field.farmName,
    fieldId: null,
    fieldCode: field.fieldCode,
    fieldName: field.fieldName,
    areaHa: field.areaHa,
    areaAlq: field.areaAlq,
    entryCount: field.entryCount,
    okCount: field.okCount,
    divergentCount: field.divergentCount,
    totalNetWeight: field.totalNetWeight,
    okNetWeight: field.totalNetWeight - field.divergentNetWeight,
    divergentNetWeight: field.divergentNetWeight,
    firstReportDate: field.firstDate,
    lastReportDate: field.lastDate,
    lastImportedAt: null
  };
}

function sum<T>(items: T[], value: (item: T) => number) {
  return items.reduce((total, item) => total + value(item), 0);
}

function earliest(left: string | null, right: string | null) {
  if (!left) return right;
  if (!right) return left;
  return left <= right ? left : right;
}

function latest(left: string | null, right: string | null) {
  if (!left) return right;
  if (!right) return left;
  return left >= right ? left : right;
}
