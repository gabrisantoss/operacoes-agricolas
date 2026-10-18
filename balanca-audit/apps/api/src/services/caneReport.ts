import type { CaneReportFilterInput, CaneReportType } from "@balanca/shared";
import type { CaneReportSourceRow } from "../db.js";
import { harvestFarmIdentity, harvestFieldIdentity, hasCompleteHarvestArea, tonsPerHectare } from "./harvestMetrics.js";

// What the stored data proves about the harvest of a field inside the report:
// CLOSED_COMPLETE  closed harvest order lists the field and every entry linked to it is in the report;
// CLOSED_CLIPPED   closed order, but part of its entries for the field falls outside the report filters;
// OPEN             no closed order (active order or entries without order);
// MIXED            entries of more than one order, or with and without order;
// NO_AREA          field without registered area.
export type FieldHarvestEvidence = "CLOSED_COMPLETE" | "CLOSED_CLIPPED" | "OPEN" | "MIXED" | "NO_AREA";

export const harvestEvidenceLabels: Record<FieldHarvestEvidence, string> = {
  CLOSED_COMPLETE: "OS encerrada",
  CLOSED_CLIPPED: "OS encerrada fora do recorte",
  OPEN: "Sem OS encerrada",
  MIXED: "Mais de uma OS",
  NO_AREA: "Sem área cadastrada"
};

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
  // Registered area of the fields with deliveries in the report: a cadastre fact, not proof of harvest.
  registeredAreaHa: number;
  // Registered area of CLOSED_COMPLETE fields only.
  provenAreaHa: number;
  provenFieldCount: number;
  provenNetWeight: number;
  // Cane of proven fields ÷ their area. Null when no field is proven.
  effectiveTch: number | null;
  evidenceCounts: Record<FieldHarvestEvidence, number>;
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
  registeredAreaHa: number;
  provenAreaHa: number;
  provenFieldCount: number;
  provenNetWeight: number;
  effectiveTch: number | null;
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
  registeredAreaHa: number | null;
  entryCount: number;
  divergentCount: number;
  totalNetWeight: number;
  averageNetWeightPerEntry: number | null;
  evidence: FieldHarvestEvidence;
  evidenceLabel: string;
  closedOrderNumber: string | null;
  closedOrderEndDate: string | null;
  effectiveTch: number | null;
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

type OrderShare = {
  orderNumber: string | null;
  closedOrderEndDate: string | null;
  closedOrderEntryCount: number | null;
  entryCount: number;
};

type FieldAccumulator = {
  key: string;
  farmKey: string;
  farmCode: string | null;
  farmName: string;
  fieldCode: string;
  fieldName: string | null;
  areaHa: number | null;
  areaAlq: number | null;
  entryCount: number;
  okCount: number;
  divergentCount: number;
  totalNetWeight: number;
  divergentNetWeight: number;
  firstDate: string | null;
  lastDate: string | null;
  dates: Set<string>;
  orders: Map<string, OrderShare>;
};

const noOrder = "__sem_os__";

export function buildCaneReport(
  rows: CaneReportSourceRow[],
  filters: CaneReportFilterInput,
  context: CaneReportContext = {}
): CaneReport {
  const accumulators = new Map<string, FieldAccumulator>();
  const days = new Map<string, CaneReportDayRow & { fieldKeys: Set<string> }>();

  for (const row of rows) {
    const fieldKey = harvestFieldIdentity(row);
    const field = accumulators.get(fieldKey) ?? {
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
      dates: new Set<string>(),
      orders: new Map<string, OrderShare>()
    };

    field.entryCount += row.entryCount;
    field.okCount += row.okCount;
    field.divergentCount += row.divergentCount;
    field.totalNetWeight += row.totalNetWeight;
    field.divergentNetWeight += row.divergentNetWeight;
    field.areaHa ??= row.areaHa;
    field.areaAlq ??= row.areaAlq;

    const orderKey = row.orderId ?? noOrder;
    const share = field.orders.get(orderKey) ?? {
      orderNumber: row.orderNumber,
      closedOrderEndDate: row.closedOrderEndDate,
      closedOrderEntryCount: row.closedOrderEntryCount,
      entryCount: 0
    };
    share.entryCount += row.entryCount;
    field.orders.set(orderKey, share);

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

    accumulators.set(fieldKey, field);
  }

  const fieldRows = [...accumulators.values()]
    .sort(
      (left, right) =>
        left.farmName.localeCompare(right.farmName, "pt-BR", { numeric: true }) ||
        left.fieldCode.localeCompare(right.fieldCode, "pt-BR", { numeric: true })
    )
    .map(toFieldRow);
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
      registeredAreaHa: 0,
      provenAreaHa: 0,
      provenFieldCount: 0,
      provenNetWeight: 0,
      effectiveTch: null,
      firstDate: null,
      lastDate: null
    };
    const proven = field.evidence === "CLOSED_COMPLETE";

    farm.fieldCount += 1;
    farm.entryCount += field.entryCount;
    farm.divergentCount += field.divergentCount;
    farm.totalNetWeight += field.totalNetWeight;
    farm.registeredAreaHa += field.registeredAreaHa ?? 0;
    farm.provenAreaHa += proven ? field.registeredAreaHa! : 0;
    farm.provenFieldCount += proven ? 1 : 0;
    farm.provenNetWeight += proven ? field.totalNetWeight : 0;
    farm.firstDate = earliest(farm.firstDate, field.firstDate);
    farm.lastDate = latest(farm.lastDate, field.lastDate);
    farms.set(field.farmKey, farm);
  }

  const farmRows = [...farms.values()].map((farm) => ({
    ...farm,
    shareOfTotal: totalNetWeight > 0 ? (farm.totalNetWeight / totalNetWeight) * 100 : 0,
    effectiveTch: tonsPerHectare(farm.provenNetWeight, farm.provenAreaHa)
  }));
  const entryCount = sum(fieldRows, (field) => field.entryCount);
  const dayRows = [...days.values()]
    .sort((left, right) => left.date.localeCompare(right.date))
    .map(({ fieldKeys, ...day }) => ({ ...day, fieldCount: fieldKeys.size }));
  const provenAreaHa = sum(farmRows, (farm) => farm.provenAreaHa);
  const provenNetWeight = sum(farmRows, (farm) => farm.provenNetWeight);
  const evidenceCounts: Record<FieldHarvestEvidence, number> = {
    CLOSED_COMPLETE: 0,
    CLOSED_CLIPPED: 0,
    OPEN: 0,
    MIXED: 0,
    NO_AREA: 0
  };
  for (const field of fieldRows) evidenceCounts[field.evidence] += 1;

  const totals: CaneReportTotals = {
    farmCount: farmRows.length,
    fieldCount: fieldRows.length,
    entryCount,
    okCount: sum([...accumulators.values()], (field) => field.okCount),
    divergentCount: sum(fieldRows, (field) => field.divergentCount),
    totalNetWeight,
    divergentNetWeight: sum([...accumulators.values()], (field) => field.divergentNetWeight),
    averageNetWeightPerEntry: entryCount > 0 ? totalNetWeight / entryCount : null,
    deliveryDays: dayRows.length,
    firstDate: dayRows[0]?.date ?? null,
    lastDate: dayRows.at(-1)?.date ?? null,
    registeredAreaHa: sum(farmRows, (farm) => farm.registeredAreaHa),
    provenAreaHa,
    provenFieldCount: evidenceCounts.CLOSED_COMPLETE,
    provenNetWeight,
    effectiveTch: tonsPerHectare(provenNetWeight, provenAreaHa),
    evidenceCounts
  };
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
    notes: entryCount === 0 ? [] : reportNotes(totals),
    totals,
    farms: farmRows,
    fields: type === "DETAILED" ? fieldRows : [],
    days: type === "GENERAL" ? dayRows : []
  };
}

export function fieldHarvestEvidence(field: Pick<FieldAccumulator, "areaHa" | "areaAlq" | "orders">): FieldHarvestEvidence {
  if (!hasCompleteHarvestArea(field)) return "NO_AREA";
  if (field.orders.size !== 1) return "MIXED";

  const [orderKey, share] = [...field.orders.entries()][0]!;
  if (orderKey === noOrder || share.closedOrderEntryCount === null) return "OPEN";
  return share.entryCount === share.closedOrderEntryCount ? "CLOSED_COMPLETE" : "CLOSED_CLIPPED";
}

function toFieldRow(field: FieldAccumulator): CaneReportFieldRow {
  const evidence = fieldHarvestEvidence(field);
  const closedShare = [...field.orders.values()].find((share) => share.closedOrderEntryCount !== null) ?? null;

  return {
    key: field.key,
    farmKey: field.farmKey,
    farmCode: field.farmCode,
    farmName: field.farmName,
    fieldCode: field.fieldCode,
    fieldName: field.fieldName,
    registeredAreaHa: hasCompleteHarvestArea(field) ? field.areaHa : null,
    entryCount: field.entryCount,
    divergentCount: field.divergentCount,
    totalNetWeight: field.totalNetWeight,
    averageNetWeightPerEntry: field.entryCount > 0 ? field.totalNetWeight / field.entryCount : null,
    evidence,
    evidenceLabel: evidenceLabel(field, evidence, closedShare),
    closedOrderNumber: closedShare?.orderNumber ?? null,
    closedOrderEndDate: closedShare?.closedOrderEndDate ?? null,
    effectiveTch: evidence === "CLOSED_COMPLETE" ? tonsPerHectare(field.totalNetWeight, field.areaHa!) : null,
    deliveryDays: field.dates.size,
    firstDate: field.firstDate,
    lastDate: field.lastDate
  };
}

function evidenceLabel(field: FieldAccumulator, evidence: FieldHarvestEvidence, closedShare: OrderShare | null) {
  if (closedShare && (evidence === "CLOSED_COMPLETE" || evidence === "CLOSED_CLIPPED")) {
    return harvestEvidenceLabels[evidence].replace("OS", `OS ${closedShare.orderNumber}`);
  }
  // A closed order mixed with entries that have no order is not the same as two different orders.
  if (evidence === "MIXED" && field.orders.has(noOrder)) {
    return "Parte das entregas sem OS";
  }
  return harvestEvidenceLabels[evidence];
}

function reportNotes(totals: CaneReportTotals) {
  const counts = totals.evidenceCounts;
  const others = [
    [counts.OPEN, "sem OS encerrada"],
    [counts.CLOSED_CLIPPED, "com entregas da OS encerrada fora do recorte"],
    [counts.MIXED, "com entregas de mais de uma OS ou sem OS"],
    [counts.NO_AREA, "sem área cadastrada"]
  ]
    .filter(([count]) => Number(count) > 0)
    .map(([count, label]) => `${count} ${label}`);
  const notes = [
    `Entregas registradas de ${formatReportDate(totals.firstDate)} a ${formatReportDate(totals.lastDate)}. ` +
      "Data de referência: data da entrada (sem data, início do período do lote).",
    "Área cadastrada: área do cadastro dos talhões com entregas no recorte; não comprova colheita. " +
      "Área colhida comprovada: talhões cuja OS está encerrada e cujas entregas vinculadas a ela estão todas no recorte. " +
      "TCH efetivo = cana desses talhões ÷ essa área."
  ];

  if (totals.provenFieldCount === 0) {
    notes.push(
      `TCH efetivo N/D: nenhum dos ${totals.fieldCount} talhão(ões) tem colheita comprovada no recorte` +
        (others.length ? ` (${others.join("; ")}).` : ".")
    );
  } else if (totals.provenFieldCount < totals.fieldCount) {
    notes.push(
      `TCH efetivo parcial: calculado só com ${totals.provenFieldCount} de ${totals.fieldCount} talhões ` +
        `(${formatTonsText(totals.provenNetWeight)} t de ${formatTonsText(totals.totalNetWeight)} t). ` +
        `Não representa a produtividade de todo o recorte. Demais talhões: ${others.join("; ")}.`
    );
  }

  return notes;
}

function formatTonsText(value: number) {
  return new Intl.NumberFormat("pt-BR", { minimumFractionDigits: 3, maximumFractionDigits: 3 }).format(value);
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
