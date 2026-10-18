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
  // Null when the area harvested inside the period cannot be determined (see partialPeriodFieldCount).
  areaHa: number | null;
  tch: number | null;
  areaCoveragePercentage: number;
  fieldsWithoutArea: number;
  partialPeriodFieldCount: number;
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
  areaHa: number | null;
  tch: number | null;
  partialPeriodFieldCount: number;
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
  tchUnavailableReason: TchUnavailableReason | null;
  deliveryDays: number;
  firstDate: string | null;
  lastDate: string | null;
  harvestFirstDate: string | null;
  harvestLastDate: string | null;
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
  // Explanations printed identically by the preview and the PDF.
  notes: string[];
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

// NO_AREA: field without registered area. PARTIAL_PERIOD: the field also has deliveries outside the selected
// period, so the area harvested inside it cannot be determined from the stored data.
export type TchUnavailableReason = "NO_AREA" | "PARTIAL_PERIOD";

type FieldAccumulator = Omit<
  CaneReportFieldRow,
  "averageNetWeightPerEntry" | "tch" | "tchUnavailableReason" | "deliveryDays"
> & {
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
      harvestFirstDate: row.fieldHarvestFirstDate,
      harvestLastDate: row.fieldHarvestLastDate,
      dates: new Set<string>()
    };

    field.harvestFirstDate = earliest(field.harvestFirstDate, row.fieldHarvestFirstDate);
    field.harvestLastDate = latest(field.harvestLastDate, row.fieldHarvestLastDate);
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
  const farms = new Map<string, CaneReportFarmRow & { knownAreaHa: number }>();

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
      areaHa: null,
      knownAreaHa: 0,
      tch: null,
      partialPeriodFieldCount: 0,
      firstDate: null,
      lastDate: null
    };
    const areaStatus = fieldAreaStatus(field, filters);

    farm.fieldCount += 1;
    farm.entryCount += field.entryCount;
    farm.divergentCount += field.divergentCount;
    farm.totalNetWeight += field.totalNetWeight;
    farm.knownAreaHa += areaStatus === null ? field.areaHa! : 0;
    farm.partialPeriodFieldCount += areaStatus === "PARTIAL_PERIOD" ? 1 : 0;
    farm.firstDate = earliest(farm.firstDate, field.firstDate);
    farm.lastDate = latest(farm.lastDate, field.lastDate);
    farms.set(field.farmKey, farm);
  }

  // Same TCH as the harvest dashboard (cane ÷ registered area of fields with area), unless part of the
  // aggregate was harvested outside the period: then neither the area nor the TCH can be determined.
  const farmRows: CaneReportFarmRow[] = [...farms.values()].map(({ knownAreaHa, ...farm }) => {
    const areaHa = farm.partialPeriodFieldCount > 0 ? null : knownAreaHa;
    return {
      ...farm,
      shareOfTotal: totalNetWeight > 0 ? (farm.totalNetWeight / totalNetWeight) * 100 : 0,
      areaHa,
      tch: areaHa === null ? null : tonsPerHectare(farm.totalNetWeight, areaHa)
    };
  });
  const coverage = calculateHarvestAreaCoverage(fieldRows.map(toProductionRow));
  const entryCount = sum(fieldRows, (field) => field.entryCount);
  const partialPeriodFieldCount = sum(farmRows, (farm) => farm.partialPeriodFieldCount);
  const areaHa = partialPeriodFieldCount > 0 ? null : sum(farmRows, (farm) => farm.areaHa ?? 0);
  const dayRows = [...days.values()]
    .sort((left, right) => left.date.localeCompare(right.date))
    .map(({ fieldKeys, ...day }) => ({ ...day, fieldCount: fieldKeys.size }));
  const type = filters.type ?? "GENERAL";
  const notes = entryCount === 0 ? [] : reportNotes({
    firstDate: dayRows[0]?.date ?? null,
    lastDate: dayRows.at(-1)?.date ?? null,
    partialPeriodFieldCount,
    fieldsWithoutArea: coverage.fieldsWithoutArea,
    areaCoveragePercentage: coverage.areaCoveragePercentage
  });

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
    notes,
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
      tch: areaHa === null ? null : tonsPerHectare(totalNetWeight, areaHa),
      areaCoveragePercentage: coverage.areaCoveragePercentage,
      fieldsWithoutArea: coverage.fieldsWithoutArea,
      partialPeriodFieldCount
    },
    farms: farmRows,
    fields: type === "DETAILED" ? fieldRows.map((field) => toFieldRow(field, filters)) : [],
    days: type === "GENERAL" ? dayRows : []
  };
}

function reportNotes(input: {
  firstDate: string | null;
  lastDate: string | null;
  partialPeriodFieldCount: number;
  fieldsWithoutArea: number;
  areaCoveragePercentage: number;
}) {
  const notes = [
    `Entregas registradas de ${formatReportDate(input.firstDate)} a ${formatReportDate(input.lastDate)}. ` +
      "Data de referência: data da entrada (sem data, início do período do lote). " +
      "TCH = cana entregue ÷ área cadastrada dos talhões com área, como no painel Safra."
  ];

  if (input.partialPeriodFieldCount > 0) {
    notes.push(
      `N/D: ${input.partialPeriodFieldCount} talhão(ões) também têm entregas fora do período selecionado. ` +
        "A área colhida dentro do período não pode ser determinada, por isso a área colhida e o TCH desses talhões " +
        "e dos totais que os incluem não são apresentados. Cana entregue e cargas continuam válidas."
    );
  }

  if (input.fieldsWithoutArea > 0) {
    notes.push(
      `${input.fieldsWithoutArea} talhão(ões) sem área cadastrada: TCH N/D no talhão. ` +
        `${formatPercent(input.areaCoveragePercentage)}% da cana vem de talhões com área.`
    );
  }

  return notes;
}

function formatPercent(value: number) {
  return new Intl.NumberFormat("pt-BR", { minimumFractionDigits: 1, maximumFractionDigits: 1 }).format(value);
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

export function fieldAreaStatus(
  field: Pick<FieldAccumulator, "areaHa" | "areaAlq" | "firstDate" | "lastDate" | "harvestFirstDate" | "harvestLastDate">,
  filters: Pick<CaneReportFilterInput, "from" | "to">
): TchUnavailableReason | null {
  if (!hasCompleteHarvestArea(field)) return "NO_AREA";

  const harvestFirst = field.harvestFirstDate ?? field.firstDate;
  const harvestLast = field.harvestLastDate ?? field.lastDate;
  if ((filters.from && (!harvestFirst || harvestFirst < filters.from)) || (filters.to && (!harvestLast || harvestLast > filters.to))) {
    return "PARTIAL_PERIOD";
  }

  return null;
}

function toFieldRow(field: FieldAccumulator, filters: CaneReportFilterInput): CaneReportFieldRow {
  const hasArea = hasCompleteHarvestArea(field);
  const tchUnavailableReason = fieldAreaStatus(field, filters);

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
    tch: tchUnavailableReason === null ? tonsPerHectare(field.totalNetWeight, field.areaHa!) : null,
    tchUnavailableReason,
    deliveryDays: field.dates.size,
    firstDate: field.firstDate,
    lastDate: field.lastDate,
    harvestFirstDate: field.harvestFirstDate,
    harvestLastDate: field.harvestLastDate
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
