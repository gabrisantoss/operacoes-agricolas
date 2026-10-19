import { createHash } from "node:crypto";

// Field totals of one PDF (incoming or already imported), keyed by supplier/farm code and field code.
export type PdfFieldTotal = {
  farmCode: string;
  farmName: string;
  fieldCode: string;
  netWeight: number;
  entryCount: number;
};

export type ImportedPdfBatch = {
  id: string;
  fileName: string;
  importedAt: string;
  periodStart: string;
  periodEnd: string;
  fields: PdfFieldTotal[];
};

export type PdfOverlapKind =
  | "IDENTICAL_FILE"
  | "SAME_PERIOD"
  | "PARTIAL_PERIOD_OVERLAP"
  | "PERIOD_OVERLAP_OTHER_FIELDS"
  | "COINCIDENT_RECORDS";

export type PdfOverlapSeverity = "INFO" | "REVIEW_REQUIRED" | "BLOCKED";

export type PdfOverlapField = {
  farmCode: string;
  farmName: string;
  fieldCode: string;
  existingNetWeight: number;
  existingEntries: number;
  newNetWeight: number;
  newEntries: number;
  sameTotals: boolean;
};

export type PdfOverlapAlert = {
  kind: PdfOverlapKind;
  severity: PdfOverlapSeverity;
  batchId: string;
  fileName: string;
  importedAt: string;
  existingPeriod: { start: string; end: string };
  overlapPeriod: { start: string; end: string } | null;
  fields: PdfOverlapField[];
  message: string;
};

export type PdfOverlapAnalysis = {
  status: "NONE" | PdfOverlapSeverity;
  newPeriod: { start: string; end: string };
  alerts: PdfOverlapAlert[];
  // Required to save when status is REVIEW_REQUIRED; changes if the file or the stored batches change.
  reviewToken: string | null;
};

const severityRank: Record<PdfOverlapAnalysis["status"], number> = { NONE: 0, INFO: 1, REVIEW_REQUIRED: 2, BLOCKED: 3 };
const coincidentMinimumShare = 0.5;
const coincidentMinimumFields = 3;

export function summarizePdfFields(
  rows: Array<{ farmCodeRaw?: string; farmRaw?: string; fieldRaw?: string; netWeight?: number }>
): PdfFieldTotal[] {
  const totals = new Map<string, PdfFieldTotal>();
  for (const row of rows) {
    const farmCode = row.farmCodeRaw ?? row.farmRaw ?? "";
    const fieldCode = row.fieldRaw ?? "";
    const key = fieldKey(farmCode, fieldCode);
    const total = totals.get(key) ?? { farmCode, farmName: row.farmRaw ?? farmCode, fieldCode, netWeight: 0, entryCount: 0 };
    total.netWeight = roundTons(total.netWeight + (row.netWeight ?? 0));
    total.entryCount += 1;
    totals.set(key, total);
  }
  return [...totals.values()];
}

export function analyzePdfImportOverlap(input: {
  fileHash: string;
  periodStart: string;
  periodEnd: string;
  fields: PdfFieldTotal[];
  identicalFile: { id: string; fileName: string; importedAt: string; periodStart: string; periodEnd: string } | null;
  importedBatches: ImportedPdfBatch[];
}): PdfOverlapAnalysis {
  const newPeriod = { start: input.periodStart, end: input.periodEnd };
  const alerts: PdfOverlapAlert[] = [];
  const incoming = new Map(input.fields.map((field) => [fieldKey(field.farmCode, field.fieldCode), field]));

  if (input.identicalFile) {
    alerts.push({
      kind: "IDENTICAL_FILE",
      severity: "BLOCKED",
      batchId: input.identicalFile.id,
      fileName: input.identicalFile.fileName,
      importedAt: input.identicalFile.importedAt,
      existingPeriod: { start: input.identicalFile.periodStart, end: input.identicalFile.periodEnd },
      overlapPeriod: null,
      fields: [],
      message: `Este mesmo arquivo ja foi importado como "${input.identicalFile.fileName}". Nada sera gravado novamente.`
    });
  }

  for (const batch of input.importedBatches) {
    if (batch.id === input.identicalFile?.id) continue;
    const existingPeriod = { start: batch.periodStart, end: batch.periodEnd };
    const shared = batch.fields
      .map((existing) => {
        const candidate = incoming.get(fieldKey(existing.farmCode, existing.fieldCode));
        return candidate
          ? {
              farmCode: candidate.farmCode,
              farmName: candidate.farmName,
              fieldCode: candidate.fieldCode,
              existingNetWeight: existing.netWeight,
              existingEntries: existing.entryCount,
              newNetWeight: candidate.netWeight,
              newEntries: candidate.entryCount,
              sameTotals: Math.abs(existing.netWeight - candidate.netWeight) < 0.0005 && existing.entryCount === candidate.entryCount
            }
          : null;
      })
      .filter((field): field is PdfOverlapField => Boolean(field))
      .sort((left, right) => left.farmCode.localeCompare(right.farmCode) || left.fieldCode.localeCompare(right.fieldCode, "pt-BR", { numeric: true }));
    const overlap = intersect(newPeriod, existingPeriod);
    const base = { batchId: batch.id, fileName: batch.fileName, importedAt: batch.importedAt, existingPeriod, overlapPeriod: overlap };

    if (overlap && newPeriod.start === existingPeriod.start && newPeriod.end === existingPeriod.end) {
      // Existing rule: one PDF per period; the previous group must be deleted before inserting another.
      alerts.push({
        ...base,
        kind: "SAME_PERIOD",
        severity: "BLOCKED",
        fields: shared,
        message: `Ja existe PDF para o mesmo periodo ${describe(existingPeriod)} ("${batch.fileName}"). Exclua o grupo existente no Historico antes de inserir outro PDF desse periodo.`
      });
    } else if (overlap && shared.length > 0) {
      alerts.push({
        ...base,
        kind: "PARTIAL_PERIOD_OVERLAP",
        severity: "REVIEW_REQUIRED",
        fields: shared,
        message: `O periodo ${describe(newPeriod)} se sobrepoe a ${describe(existingPeriod)} de "${batch.fileName}" em ${describe(overlap)}, com ${shared.length} talhao(oes) em comum. A cana desses dias pode ser contada duas vezes; revise antes de gravar.`
      });
    } else if (overlap) {
      alerts.push({
        ...base,
        kind: "PERIOD_OVERLAP_OTHER_FIELDS",
        severity: "INFO",
        fields: [],
        message: `O periodo se sobrepoe a "${batch.fileName}" (${describe(existingPeriod)}), mas nenhum talhao coincide. Tratado como importacao legitima.`
      });
    } else {
      const identical = shared.filter((field) => field.sameTotals);
      const required = Math.max(Math.min(coincidentMinimumFields, incoming.size), Math.ceil(incoming.size * coincidentMinimumShare));
      if (identical.length > 0 && identical.length >= required) {
        alerts.push({
          ...base,
          kind: "COINCIDENT_RECORDS",
          severity: "REVIEW_REQUIRED",
          fields: identical,
          message: `${identical.length} de ${incoming.size} talhao(oes) tem a mesma cana e as mesmas viagens de "${batch.fileName}" (${describe(existingPeriod)}), embora o periodo seja diferente. Pode ser o mesmo relatorio com outro periodo; revise antes de gravar.`
        });
      }
    }
  }

  const status = alerts.reduce<PdfOverlapAnalysis["status"]>(
    (current, alert) => (severityRank[alert.severity] > severityRank[current] ? alert.severity : current),
    "NONE"
  );

  return {
    status,
    newPeriod,
    alerts,
    reviewToken: status === "REVIEW_REQUIRED" ? reviewTokenFor(input.fileHash, alerts) : null
  };
}

export function reviewTokenFor(fileHash: string, alerts: PdfOverlapAlert[]) {
  const reviewed = alerts
    .filter((alert) => alert.severity === "REVIEW_REQUIRED")
    .map((alert) => `${alert.kind}:${alert.batchId}`)
    .sort();
  return createHash("sha256").update([fileHash, ...reviewed].join("|")).digest("hex");
}

export function fieldKey(farmCode: string, fieldCode: string) {
  const farm = farmCode.replace(/\D/g, "").replace(/^0+(?=\d)/, "") || farmCode.trim().toLowerCase();
  const field = fieldCode.trim().replace(/^0+(?=\d)/, "").toLowerCase();
  return `${farm}::${field}`;
}

function intersect(left: { start: string; end: string }, right: { start: string; end: string }) {
  const start = left.start > right.start ? left.start : right.start;
  const end = left.end < right.end ? left.end : right.end;
  return start <= end ? { start, end } : null;
}

function describe(period: { start: string; end: string }) {
  const format = (value: string) => {
    const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(value);
    return match ? `${match[3]}/${match[2]}/${match[1]}` : value;
  };
  return period.start === period.end ? format(period.start) : `${format(period.start)} a ${format(period.end)}`;
}

function roundTons(value: number) {
  return Math.round((value + Number.EPSILON) * 1000) / 1000;
}
