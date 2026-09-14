import type { FieldProductionRow } from "../db.js";

type HarvestFarmIdentitySource = Pick<FieldProductionRow, "farmId" | "farmCode" | "farmName">;
type HarvestFieldIdentitySource = HarvestFarmIdentitySource & Pick<FieldProductionRow, "fieldId" | "fieldCode">;

export type HarvestAreaCoverage = {
  netWeightWithArea: number;
  netWeightWithoutArea: number;
  areaCoveragePercentage: number;
  entriesWithoutArea: number;
  fieldsWithoutArea: number;
};

export type HarvestAreaObservation = {
  date: string;
  fieldId: string;
  areaHa: number | null | undefined;
  areaAlq: number | null | undefined;
  hasDivergence?: boolean;
};

export function summarizeUniqueHarvestAreaByDate(observations: HarvestAreaObservation[]) {
  const firstObservationByField = new Map<
    string,
    { date: string; areaHa: number; areaAlq: number; hasDivergence: boolean }
  >();

  for (const observation of observations) {
    if (!observation.date || !observation.fieldId) continue;
    const candidate = {
      date: observation.date,
      areaHa: positiveMetric(observation.areaHa),
      areaAlq: positiveMetric(observation.areaAlq),
      hasDivergence: Boolean(observation.hasDivergence)
    };
    const current = firstObservationByField.get(observation.fieldId);

    if (!current) {
      firstObservationByField.set(observation.fieldId, candidate);
      continue;
    }

    current.hasDivergence ||= candidate.hasDivergence;
    if (candidate.date < current.date) {
      current.date = candidate.date;
      current.areaHa = candidate.areaHa;
      current.areaAlq = candidate.areaAlq;
    }
  }

  const byDate = new Map<
    string,
    {
      date: string;
      fieldCount: number;
      areaHa: number;
      areaAlq: number;
      divergentFieldCount: number;
      divergentAreaHa: number;
      divergentAreaAlq: number;
    }
  >();

  for (const field of firstObservationByField.values()) {
    const group = byDate.get(field.date) ?? {
      date: field.date,
      fieldCount: 0,
      areaHa: 0,
      areaAlq: 0,
      divergentFieldCount: 0,
      divergentAreaHa: 0,
      divergentAreaAlq: 0
    };
    group.fieldCount += 1;
    group.areaHa += field.areaHa;
    group.areaAlq += field.areaAlq;
    if (field.hasDivergence) {
      group.divergentFieldCount += 1;
      group.divergentAreaHa += field.areaHa;
      group.divergentAreaAlq += field.areaAlq;
    }
    byDate.set(field.date, group);
  }

  let cumulativeAreaHa = 0;
  let cumulativeAreaAlq = 0;
  return [...byDate.values()]
    .sort((left, right) => left.date.localeCompare(right.date))
    .map((row) => {
      cumulativeAreaHa += row.areaHa;
      cumulativeAreaAlq += row.areaAlq;
      return { ...row, cumulativeAreaHa, cumulativeAreaAlq };
    });
}

export function consolidateFieldProductionRows(rows: FieldProductionRow[]): FieldProductionRow[] {
  const consolidated = new Map<string, FieldProductionRow>();

  for (const row of rows) {
    const key = harvestFieldIdentity(row);
    const current = consolidated.get(key);
    if (!current) {
      consolidated.set(key, { ...row });
      continue;
    }

    current.entryCount += row.entryCount;
    current.okCount += row.okCount;
    current.divergentCount += row.divergentCount;
    current.totalNetWeight += row.totalNetWeight;
    current.okNetWeight += row.okNetWeight;
    current.divergentNetWeight += row.divergentNetWeight;
    current.areaHa ??= row.areaHa;
    current.areaAlq ??= row.areaAlq;
    current.firstReportDate = earliest(current.firstReportDate, row.firstReportDate);
    current.lastReportDate = latest(current.lastReportDate, row.lastReportDate);
    current.lastImportedAt = latest(current.lastImportedAt, row.lastImportedAt);
  }

  return [...consolidated.values()].sort(
    (left, right) =>
      left.farmName.localeCompare(right.farmName, "pt-BR", { numeric: true }) ||
      left.fieldCode.localeCompare(right.fieldCode, "pt-BR", { numeric: true })
  );
}

export function tonsPerHectare(totalNetWeightTons: number, uniqueAreaHa: number) {
  return uniqueAreaHa > 0 ? totalNetWeightTons / uniqueAreaHa : null;
}

export function classifyHarvestFarmOwnership(farmCode: string | null | undefined) {
  const normalizedCode = normalizeIdentityPart(farmCode);

  if (normalizedCode.startsWith("1")) return "OWN" as const;
  if (normalizedCode.startsWith("2")) return "SUPPLIER" as const;
  return "UNKNOWN" as const;
}

export function harvestFarmIdentity(source: HarvestFarmIdentitySource) {
  const farmId = source.farmId?.trim();
  if (farmId) return `id:${farmId}`;

  const farmCode = normalizeIdentityPart(source.farmCode);
  if (farmCode) return `code:${farmCode}`;

  return `name:${normalizeIdentityPart(source.farmName) || "unknown"}`;
}

export function harvestFieldIdentity(source: HarvestFieldIdentitySource) {
  const fieldId = source.fieldId?.trim();
  if (fieldId) return `id:${fieldId}`;

  return `raw:${harvestFarmIdentity(source)}:${normalizeIdentityPart(source.fieldCode) || "unknown"}`;
}

export function hasCompleteHarvestArea(
  source: Pick<FieldProductionRow, "areaHa" | "areaAlq">
) {
  return positiveMetric(source.areaHa) > 0 && positiveMetric(source.areaAlq) > 0;
}

export function calculateHarvestAreaCoverage(rows: FieldProductionRow[]): HarvestAreaCoverage {
  let netWeightWithArea = 0;
  let netWeightWithoutArea = 0;
  let entriesWithoutArea = 0;
  let fieldsWithoutArea = 0;

  for (const row of rows) {
    const netWeight = finiteMetric(row.totalNetWeight);
    if (hasCompleteHarvestArea(row)) {
      netWeightWithArea += netWeight;
      continue;
    }

    netWeightWithoutArea += netWeight;
    entriesWithoutArea += finiteMetric(row.entryCount);
    fieldsWithoutArea += 1;
  }

  const totalNetWeight = netWeightWithArea + netWeightWithoutArea;
  return {
    netWeightWithArea,
    netWeightWithoutArea,
    areaCoveragePercentage: totalNetWeight > 0 ? (netWeightWithArea / totalNetWeight) * 100 : 0,
    entriesWithoutArea,
    fieldsWithoutArea
  };
}

export function rankHarvestPeriods<
  T extends { totalNetWeight: number; periodStart: string | null }
>(periods: readonly T[], limit = 10) {
  const safeLimit = Math.max(0, Math.trunc(limit));
  return [...periods]
    .sort(
      (left, right) =>
        right.totalNetWeight - left.totalNetWeight ||
        (left.periodStart ?? "").localeCompare(right.periodStart ?? "", "pt-BR", { numeric: true })
    )
    .slice(0, safeLimit);
}

export function harvestYearRange(year: number | undefined) {
  if (year === undefined || !Number.isInteger(year) || year < 1000 || year > 9999) {
    return null;
  }

  return {
    start: `${year}-01-01`,
    end: `${year}-12-31`
  };
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

function positiveMetric(value: number | null | undefined) {
  const parsed = Number(value ?? 0);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : 0;
}

function finiteMetric(value: number | null | undefined) {
  const parsed = Number(value ?? 0);
  return Number.isFinite(parsed) ? parsed : 0;
}

function normalizeIdentityPart(value: string | null | undefined) {
  return String(value ?? "")
    .normalize("NFD")
    .replace(/\p{Diacritic}/gu, "")
    .toLowerCase()
    .replace(/[^a-z0-9]/g, "");
}
