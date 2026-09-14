import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { execFile } from "node:child_process";
import { createHash, randomUUID } from "node:crypto";
import { promisify } from "node:util";
import { parse } from "csv-parse/sync";
import { PDFDocument, rgb } from "pdf-lib";
import { readSheet } from "read-excel-file/node";
import type { EntryStatus, ImportMappingInput, ImportOptionsInput } from "@balanca/shared";
import {
  type CaneEntryImportInput,
  type FarmRecord,
  type FieldRecord,
  type HarvestOrderRecord,
  type ImportBatchMetadataInput,
  findActiveOrderForField,
  findImportBatchByFileHash,
  findPdfImportBatchByPeriod,
  findFarmByRaw,
  findFieldByFarmAndCode,
  listFarms,
  listOrders,
  listOrdersWithNumber,
  saveImportResult,
  findOrphanedCaneEntriesByFarm,
  updateCaneEntryReconciliation,
  updateCaneEntryReconciliations,
  recalculateImportBatchCounts,
  claimNextBackgroundJob,
  completeBackgroundJob,
  enqueueBackgroundJob,
  failBackgroundJob,
  db
} from "../db.js";
import { badRequest } from "../errors.js";
import { assertExportRowLimit } from "./exportControl.js";
import {
  extractCanePdfAssistCandidates,
  type GeminiCanePdfExtraction
} from "./canePdfAssist.js";
import { isDuplicateImportFileHashError } from "./importDeduplication.js";
import { summarizeUniqueHarvestAreaByDate } from "./harvestMetrics.js";

const execFileAsync = promisify(execFile);

type RawRow = Record<string, unknown>;

type NormalizedEntry = {
  ticketNumber?: string;
  entryDate?: Date;
  farmCodeRaw?: string;
  farmRaw?: string;
  fieldRaw?: string;
  orderRaw?: string;
  vehiclePlate?: string;
  grossWeight?: number;
  netWeight?: number;
  tripCount?: number;
  fieldId?: string;
  areaHa?: number | null;
  areaAlq?: number | null;
};

type DetectionResult = {
  sourceType: "SPREADSHEET" | "SCS0110P_PDF";
  columns: string[];
  mapping: ImportMappingInput;
  rows: PreviewEntry[];
  summary: ImportPreviewSummary;
  metadata?: ImportBatchMetadata;
  fileHash: string;
};

type CaneSummaryExtractionSource = "local" | "google-vision" | "gemini";

type CaneSummaryReconciliation = {
  status: "MATCH" | "MISMATCH" | "NOT_AVAILABLE";
  expectedNetWeight?: number;
  parsedNetWeight: number;
  netWeightDifference?: number;
  expectedTrips?: number;
  parsedTrips: number;
  tripDifference?: number;
  extractionSource: CaneSummaryExtractionSource;
  assisted: boolean;
};

type ImportBatchMetadata = Omit<ImportBatchMetadataInput, "fileHash"> & {
  fileHash?: string;
  isConsolidatedPeriod?: boolean;
  reconciliation?: CaneSummaryReconciliation;
};

type ParsedRows = {
  sourceType: DetectionResult["sourceType"];
  columns: string[];
  rows: RawRow[];
  mapping?: ImportMappingInput;
  metadata?: ImportBatchMetadata;
};

type PreviewEntry = NormalizedEntry & {
  status: EntryStatus;
  notes?: string;
};

type ClassifiedEntry = {
  status: EntryStatus;
  notes?: string;
  farmId?: string;
  fieldId?: string;
  orderId?: string;
  orderNumber?: string;
  areaHa?: number | null;
  areaAlq?: number | null;
};

type ClassificationContext = {
  farms: FarmRecord[];
  farmsByExactRaw: Map<string, FarmRecord>;
  farmsByRawCode: Map<string, FarmRecord>;
  farmsByExactCode: Map<string, FarmRecord | null>;
  farmsByCanonicalCode: Map<string, FarmRecord | null>;
  fieldsByFarmAndCode: Map<string, FieldRecord>;
  ordersByField: Map<string, HarvestOrderRecord[]>;
};

type PdfBboxWord = {
  text: string;
  xMin: number;
  yMin: number;
  xMax: number;
  yMax: number;
};

type PdfBboxPage = {
  index: number;
  width: number;
  height: number;
  words: PdfBboxWord[];
};

type PdfHighlightRow = {
  pageIndex: number;
  pageWidth: number;
  yMin: number;
  yMax: number;
  row: NormalizedEntry;
};

type ImportPreviewSummary = {
  rowCount: number;
  okCount: number;
  errorCount: number;
  byStatus: Array<{ status: EntryStatus; count: number }>;
  areaHa: number;
  areaAlq: number;
  areaByDate: Array<{
    date: string;
    fieldCount: number;
    areaHa: number;
    areaAlq: number;
  }>;
  reconciliation?: CaneSummaryReconciliation;
};

const columnAliases: Record<keyof ImportMappingInput, string[]> = {
  ticketNumber: ["nota", "ticket", "romaneio", "numero", "número", "nf", "nfe"],
  entryDate: ["data", "entrada", "data entrada", "dt entrada"],
  farm: ["fazenda", "propriedade", "fornecedor", "origem"],
  field: ["talhao", "talhão", "quadra", "gleba"],
  order: ["os", "o.s", "ordem", "ordem servico", "ordem serviço", "ordem de servico", "ordem de serviço", "colheita"],
  vehiclePlate: ["placa", "caminhao", "caminhão", "veiculo", "veículo"],
  grossWeight: ["peso bruto", "bruto", "pb"],
  netWeight: ["peso liquido", "peso líquido", "liquido", "líquido", "pl"]
};

const previewRowsLimit = 200;

export async function previewImport(filePath: string, fileName: string, options: ImportOptionsInput = {}): Promise<DetectionResult> {
  const [parsed, fileHash] = await Promise.all([readRows(filePath, fileName, options), calculateFileHash(filePath)]);
  ensurePdfPeriodWasNotImported(parsed);
  const detectedMapping = parsed.mapping ?? detectMapping(parsed.columns, options.mapping);
  const classificationContext = createClassificationContext(parsed.sourceType);
  const classifiedRows = parsed.rows
    .map((row) => normalizeRow(row, detectedMapping))
    .flatMap(unrollNormalizedRow)
    .map((row) => classifyNormalizedRow(row, parsed.sourceType, classificationContext));

  return {
    sourceType: parsed.sourceType,
    columns: parsed.columns,
    mapping: detectedMapping,
    rows: prioritizePreviewRows(classifiedRows).slice(0, previewRowsLimit),
    summary: summarizePreview(classifiedRows, parsed.metadata?.reconciliation),
    metadata: parsed.metadata,
    fileHash
  };
}

export async function commitImport(
  filePath: string,
  fileName: string,
  importedById?: string,
  options: ImportOptionsInput & { expectedFileHash?: string } = {}
) {
  const fileHash = await calculateFileHash(filePath);
  const extension = path.extname(fileName).toLowerCase();
  const isAiAssistable = [".pdf", ".png", ".jpg", ".jpeg"].includes(extension);

  if (isAiAssistable && (!options.expectedFileHash || options.expectedFileHash !== fileHash)) {
    throw badRequest("Compare este mesmo arquivo antes de inserir os dados.");
  }
  const existingBatch = findImportBatchByFileHash(fileHash);

  if (existingBatch) {
    throw badRequest(
      `Este arquivo ja foi lancado no historico em ${formatStoredDateTime(existingBatch.importedAt)} como "${existingBatch.fileName}".`
    );
  }

  const parsed = await readRows(filePath, fileName, options);
  assertCaneSummaryReconciled(parsed);
  ensurePdfPeriodWasNotImported(parsed);
  const detectedMapping = parsed.mapping ?? detectMapping(parsed.columns, options.mapping);
  const classificationContext = createClassificationContext(parsed.sourceType);
  const entries: CaneEntryImportInput[] = parsed.rows
    .map((rawRow) => normalizeRow(rawRow, detectedMapping))
    .flatMap(unrollNormalizedRow)
    .map((row) => {
      const classified = classifyRow(row, parsed.sourceType, classificationContext);
      const notes = buildEntryNotes(classified.notes, row.tripCount);

      return {
        ticketNumber: row.ticketNumber,
        entryDate: row.entryDate,
        farmId: classified.farmId,
        farmNameRaw: row.farmRaw,
        farmCodeRaw: row.farmCodeRaw,
        fieldId: classified.fieldId,
        fieldCodeRaw: row.fieldRaw,
        orderId: classified.orderId,
        orderNumberRaw: row.orderRaw ?? classified.orderNumber,
        vehiclePlate: row.vehiclePlate,
        grossWeight: row.grossWeight,
        netWeight: row.netWeight,
        status: classified.status,
        notes
      };
    });

  let updatedBatch: ReturnType<typeof saveImportResult>;
  try {
    updatedBatch = saveImportResult({
      fileName,
      importedById,
      entries,
      metadata: {
        ...parsed.metadata,
        fileHash,
        sourceType: parsed.sourceType
      }
    });
  } catch (error) {
    if (!isDuplicateImportFileHashError(error)) {
      throw error;
    }

    // A verificacao anterior melhora a mensagem comum; o indice resolve a corrida entre duas requisicoes.
    const concurrentBatch = findImportBatchByFileHash(fileHash);
    if (concurrentBatch) {
      throw badRequest(
        `Este arquivo ja foi lancado no historico em ${formatStoredDateTime(concurrentBatch.importedAt)} como "${concurrentBatch.fileName}".`
      );
    }
    throw badRequest("Este arquivo ja foi lancado no historico por outra importacao concorrente.");
  }

  return {
    batch: updatedBatch,
    sourceType: parsed.sourceType,
    mapping: detectedMapping
  };
}

function ensurePdfPeriodWasNotImported(parsed: ParsedRows) {
  if (parsed.sourceType !== "SCS0110P_PDF") {
    return;
  }

  const periodStart = parsed.metadata?.periodStart;
  const periodEnd = parsed.metadata?.periodEnd ?? periodStart;

  if (!periodStart || !periodEnd) {
    throw badRequest("Nao foi possivel identificar o PERIODO do PDF. Confira o arquivo antes de inserir os dados.");
  }

  const existingBatch = findPdfImportBatchByPeriod(periodStart, periodEnd);

  if (!existingBatch) {
    return;
  }

  const existingPeriod = formatStoredPeriod(existingBatch.periodStart ?? existingBatch.reportDate, existingBatch.periodEnd);

  throw badRequest(
    `Ja existe PDF inserido para o periodo ${existingPeriod}: "${existingBatch.fileName}", importado em ${formatStoredDateTime(existingBatch.importedAt)}. Exclua o grupo existente antes de inserir outro PDF desse periodo.`
  );
}

export async function highlightCaneSummaryPdfDivergences(filePath: string, fileName: string) {
  if (path.extname(fileName).toLowerCase() !== ".pdf") {
    throw badRequest("Envie um PDF SCS0110P para marcar as divergencias.");
  }

  const [sourceBytes, text, bboxText] = await Promise.all([
    fs.readFile(filePath),
    extractPdfText(filePath),
    extractPdfBboxText(filePath)
  ]);
  const metadata = extractCaneSummaryMetadata(text);
  const rows = parseCaneSummaryPdfBboxRows(bboxText, metadata.periodStart ?? metadata.reportDate);
  assertExportRowLimit(rows.length);
  const classificationContext = createClassificationContext("SCS0110P_PDF");
  const divergentRows = rows.filter((item) => classifyCaneSummaryRow(item.row, classificationContext).status !== "OK");
  const pdf = await PDFDocument.load(sourceBytes);

  for (const item of divergentRows) {
    const page = pdf.getPage(item.pageIndex);
    const pageHeight = page.getHeight();
    const pageWidth = page.getWidth();
    const rowHeight = Math.max(9, item.yMax - item.yMin + 5);

    page.drawRectangle({
      x: 14,
      y: pageHeight - item.yMax - 2,
      width: Math.max(1, pageWidth - 28),
      height: rowHeight,
      color: rgb(1, 0.94, 0.18),
      opacity: 0.38,
      borderColor: rgb(0.95, 0.65, 0.05),
      borderOpacity: 0.5,
      borderWidth: 0.25
    });
  }

  return {
    pdf: Buffer.from(await pdf.save()),
    parsedRows: rows.length,
    highlightedRows: divergentRows.length
  };
}

async function readRows(
  filePath: string,
  fileName: string,
  options: ImportOptionsInput
): Promise<ParsedRows> {
  const extension = path.extname(fileName).toLowerCase();

  if ([".pdf", ".png", ".jpg", ".jpeg"].includes(extension)) {
    return readCaneSummaryPdfRows(filePath, options);
  }

  const table = extension === ".csv" ? await readCsvTable(filePath) : await readExcelTable(filePath, extension);
  const header = table[0] ?? [];
  const columns = header.map((value, index) => String(value || `Coluna ${index + 1}`).trim());

  if (columns.length === 0) {
    return { sourceType: "SPREADSHEET", columns: [], rows: [] };
  }

  const rows = table.slice(1).map((cells) =>
    Object.fromEntries(columns.map((column, index) => [column, cells[index] ?? ""]))
  );

  return { sourceType: "SPREADSHEET", columns, rows };
}

async function readExcelTable(filePath: string, extension: string) {
  if (extension !== ".xlsx") {
    throw badRequest("Formato de arquivo nao suportado. Envie .xlsx, .csv ou .pdf.");
  }

  const rows = await readSheet(filePath);
  return rows.map((row) => [...row]) as unknown[][];
}

async function readCsvTable(filePath: string) {
  const content = await fs.readFile(filePath, "utf8");
  return parse(content, {
    bom: true,
    relaxColumnCount: true,
    skip_empty_lines: true
  }) as unknown[][];
}

async function readCaneSummaryPdfRows(filePath: string, options: ImportOptionsInput) {
  const [textVariants, bboxText] = await Promise.all([
    extractPdfTextVariants(filePath).catch(() => []),
    extractPdfBboxText(filePath).catch(() => "")
  ]);
  const parsed = await parseCaneSummaryPdfWithFallback(filePath, textVariants, bboxText);

  return {
    sourceType: "SCS0110P_PDF" as const,
    columns: ["Data", "Codigo Fazenda", "Fazenda", "Talhao", "Cana Entregue", "Viagens", "OS encontrada"],
    mapping: {
      ticketNumber: "ticketNumber",
      entryDate: "entryDate",
      farm: "farmRaw",
      field: "fieldRaw",
      netWeight: "netWeight"
    },
    rows: parsed.rows,
    metadata: parsed.metadata
  };
}

async function parseCaneSummaryPdfWithFallback(filePath: string, textVariants: string[], bboxText: string) {
  const hasPositionedText = /<word\s/.test(bboxText);
  if (!hasPositionedText && textVariants.some(isCaneSummaryPdfText)) {
    throwCaneSummaryColumnError("Nao foi possivel localizar as colunas do PDF digital. Confira a extracao por posicao antes de importar.");
  }

  let localResult: ReturnType<typeof parseCaneSummaryPdfTexts> | undefined;
  let localError: unknown;

  try {
    localResult = parseCaneSummaryPdfTexts(textVariants, hasPositionedText ? bboxText : "", "local");
  } catch (error) {
    if (error instanceof Error && error.name === "CaneSummaryColumnError") {
      throw error;
    }
    localError = error;
  }

  if (hasPositionedText) {
    if (localResult) return localResult;
    throw localError ?? badRequest("Nao foi possivel ler as colunas do PDF digital.");
  }

  if (localResult?.metadata.reconciliation?.status === "MATCH") {
    return localResult;
  }

  if (!localResult && shouldTryCaneSummaryOcr(textVariants)) {
    const ocrText = await extractCaneSummaryPdfOcrText(filePath);

    if (ocrText.trim()) {
      try {
        localResult = parseCaneSummaryPdfTexts([...textVariants, ocrText], "", "local");
      } catch (error) {
        localError = error;
      }
    }
  }

  const assisted = await extractCanePdfAssistCandidates(filePath);
  const candidates: Array<ReturnType<typeof parseCaneSummaryPdfTexts>> = [];

  if (assisted.googleVisionText?.trim()) {
    try {
      candidates.push(
        applyAuthoritativeCaneSummaryTotals(
          parseCaneSummaryPdfTexts([assisted.googleVisionText], "", "google-vision"),
          localResult?.metadata
        )
      );
    } catch {
      // An external OCR candidate is only advisory.
    }
  }

  if (assisted.geminiExtraction) {
    const geminiCandidate = parseGeminiCaneSummaryExtraction(assisted.geminiExtraction, localResult?.metadata);

    if (geminiCandidate) {
      candidates.push(geminiCandidate);
    }
  }

  const reconciledAssist = candidates.find((candidate) => candidate.metadata.reconciliation?.status === "MATCH");
  const bestResult = reconciledAssist ?? localResult ?? candidates[0];

  if (bestResult) {
    return bestResult;
  }

  throw localError ?? badRequest("Nao foi possivel ler o PDF SCS0110P.");
}

async function extractPdfText(filePath: string) {
  const variants = await extractPdfTextVariants(filePath);
  return variants[0] ?? "";
}

async function extractPdfTextVariants(filePath: string) {
  const variants = await Promise.all([
    execPdfText(filePath, ["-layout", filePath, "-"]),
    execPdfText(filePath, ["-raw", filePath, "-"]),
    execPdfText(filePath, [filePath, "-"])
  ]);
  const uniqueVariants = uniqueTextVariants(variants.map(normalizePdfTextForParsing).filter((text) => text.trim().length > 0));

  if (uniqueVariants.length === 0) {
    throw badRequest("Nao foi possivel ler o PDF. Instale o pacote poppler-utils para habilitar pdftotext.");
  }

  return uniqueVariants;
}

async function execPdfText(filePath: string, args: string[]) {
  try {
    const { stdout } = await execFileAsync("pdftotext", args, {
      maxBuffer: 10 * 1024 * 1024
    });
    return stdout;
  } catch {
    return "";
  }
}

export function parseCaneSummaryPdfText(text: string) {
  return parseCaneSummaryPdfTexts([text]);
}

export function parseCaneSummaryPdfTextVariants(texts: string[]) {
  return parseCaneSummaryPdfTexts(texts);
}

function parseCaneSummaryPdfTexts(
  texts: string[],
  bboxText = "",
  extractionSource: CaneSummaryExtractionSource = "local"
) {
  const textVariants = uniqueTextVariants(texts.map(normalizePdfTextForParsing).filter((text) => text.trim().length > 0));
  const combinedText = textVariants.join("\n");

  if (!isCaneSummaryPdfText(combinedText)) {
    throw badRequest("PDF nao reconhecido. Envie o relatorio SCS0110P - Resumo de Cana Entregue - Talhao.");
  }

  const metadata = extractCaneSummaryMetadata(combinedText);
  const entryDate = metadata.periodStart ?? metadata.reportDate;
  // A positioned PDF row is authoritative. Merging text variants can assign a
  // number from a farm name/area to Talhao while preserving the same grand total.
  const rows = bboxText.trim()
    ? parseCaneSummaryPdfBboxRowsOrEmpty(bboxText, entryDate).map((item) => item.row)
    : uniqueCaneSummaryRows(textVariants.flatMap((text) =>
      buildCaneSummaryLineCandidates(text)
        .map((line) => parseCaneSummaryPdfLine(line, entryDate))
        .filter((row): row is NormalizedEntry => Boolean(row))
    ));

  if (rows.length === 0) {
    throw badRequest("PDF sem linhas de talhao validas para importacao.");
  }

  metadata.reconciliation = reconcileCaneSummaryRows(rows, metadata, extractionSource);
  return { rows, metadata };
}

function parseGeminiCaneSummaryExtraction(extraction: GeminiCanePdfExtraction, authoritative?: ImportBatchMetadata) {
  const periodStart = authoritative?.periodStart ?? parseImportDate(extraction.periodStart);
  const periodEnd = authoritative?.periodEnd ?? parseImportDate(extraction.periodEnd);
  const reportDate = authoritative?.reportDate ?? parseImportDate(extraction.reportDate);
  const entryDate = periodStart ?? reportDate;
  const rows = uniqueCaneSummaryRows(
    extraction.rows.map((row) => ({
      ticketNumber: `${entryDate?.toISOString().slice(0, 10) ?? "sem-data"}-${row.field}`,
      entryDate,
      farmCodeRaw: `${row.originCode}-${row.supplierCode.padStart(3, "0")}`,
      farmRaw: row.farm,
      fieldRaw: row.field,
      netWeight: row.netWeight,
      tripCount: row.tripCount
    }))
  );
  const metadata: ImportBatchMetadata = {
    sourceType: "SCS0110P_PDF",
    reportDate,
    periodStart,
    periodEnd,
    totalNetWeight: authoritative?.totalNetWeight ?? extraction.totalNetWeight,
    totalTrips: authoritative?.totalTrips ?? extraction.totalTrips,
    isConsolidatedPeriod: Boolean(periodStart && periodEnd && !isSameDate(periodStart, periodEnd))
  };
  metadata.reconciliation = reconcileCaneSummaryRows(rows, metadata, "gemini");
  return rows.length > 0 ? { rows, metadata } : null;
}

function applyAuthoritativeCaneSummaryTotals(
  candidate: ReturnType<typeof parseCaneSummaryPdfTexts>,
  authoritative?: ImportBatchMetadata
) {
  if (authoritative?.totalNetWeight === undefined || authoritative.totalTrips === undefined) {
    return candidate;
  }

  candidate.metadata.reportDate = authoritative.reportDate ?? candidate.metadata.reportDate;
  candidate.metadata.periodStart = authoritative.periodStart ?? candidate.metadata.periodStart;
  candidate.metadata.periodEnd = authoritative.periodEnd ?? candidate.metadata.periodEnd;
  candidate.metadata.totalNetWeight = authoritative.totalNetWeight;
  candidate.metadata.totalTrips = authoritative.totalTrips;
  candidate.metadata.reconciliation = reconcileCaneSummaryRows(candidate.rows, candidate.metadata, "google-vision");
  return candidate;
}

function extractCaneSummaryMetadata(text: string): ImportBatchMetadata {
  const normalizedText = normalizePdfTextForParsing(text);

  if (!isCaneSummaryPdfText(normalizedText)) {
    throw badRequest("PDF nao reconhecido. Envie o relatorio SCS0110P - Resumo de Cana Entregue - Talhao.");
  }

  const reportDateMatch = /Data\s*:\s*(\d{1,2})\s*\/\s*(\d{1,2})\s*\/\s*(\d{2,4})/i.exec(normalizedText);
  const periodMatch = /PER[IÍ]ODO\s+(\d{1,2}\s*\/\s*\d{1,2}\s*\/\s*\d{2,4})\s+A\s+(\d{1,2}\s*\/\s*\d{1,2}\s*\/\s*\d{2,4})/i.exec(normalizedText);
  const totalMatch = /TOTAL\s+GERAL\s+(?:[\d.]+,\d+\s+)*?(?<weight>\d{1,3}(?:\.\d{3})*,\d{3}|\d+,\d{3})\s*(?<trips>\d+)(?:\s|$)/im.exec(normalizedText);
  const reportDate = parseImportDate(
    reportDateMatch ? `${reportDateMatch[1]}/${reportDateMatch[2]}/${reportDateMatch[3]}` : undefined
  );
  const periodStart = parseImportDate(periodMatch?.[1]?.replace(/\s/g, ""));
  const periodEnd = parseImportDate(periodMatch?.[2]?.replace(/\s/g, ""));

  return {
    sourceType: "SCS0110P_PDF",
    reportDate,
    periodStart,
    periodEnd,
    totalNetWeight: totalMatch?.groups?.weight ? parseDecimalNumber(totalMatch.groups.weight) : undefined,
    totalTrips: totalMatch?.groups?.trips ? Number(totalMatch.groups.trips) : undefined,
    isConsolidatedPeriod: Boolean(periodStart && periodEnd && !isSameDate(periodStart, periodEnd))
  };
}

function isCaneSummaryPdfText(text: string) {
  const normalized = normalizeText(repairCommonPdfMojibake(text));
  return normalized.includes("resumo de cana entregue") && normalized.includes("talh") && normalized.includes("scs0110p");
}

function normalizePdfTextForParsing(text: string) {
  return repairCommonPdfMojibake(text)
    .replace(/\u00a0/g, " ")
    .replace(/\t/g, "    ")
    .replace(/[\u2010-\u2015]/g, "-")
    .replace(/[“”]/g, '"')
    .replace(/[‘’]/g, "'")
    .replace(/\r\n/g, "\n")
    .replace(/\r/g, "\n");
}

function normalizePdfLineForParsing(line: string) {
  return normalizePdfTextForParsing(line).replace(/\s+$/g, "");
}

function repairCommonPdfMojibake(text: string) {
  return text
    .replace(/Ã¡/g, "á")
    .replace(/Ã /g, "à")
    .replace(/Ã¢/g, "â")
    .replace(/Ã£/g, "ã")
    .replace(/Ã©/g, "é")
    .replace(/Ãª/g, "ê")
    .replace(/Ã­/g, "í")
    .replace(/Ã³/g, "ó")
    .replace(/Ã´/g, "ô")
    .replace(/Ãµ/g, "õ")
    .replace(/Ãº/g, "ú")
    .replace(/Ã§/g, "ç")
    .replace(/Ã�/g, "Í")
    .replace(/Ã‰/g, "É")
    .replace(/Ã‡/g, "Ç");
}

function buildCaneSummaryLineCandidates(text: string) {
  const lines = text.split(/\n/).map(normalizePdfLineForParsing).filter((line) => line.trim().length > 0);
  const candidates = new Set<string>();

  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index];
    candidates.add(line);

    if (looksLikeCaneSummaryRowStart(line)) {
      const nextLine = lines[index + 1];

      if (nextLine && !looksLikeCaneSummaryRowStart(nextLine)) {
        candidates.add(`${line} ${nextLine.trim()}`);
      }
    }
  }

  return Array.from(candidates);
}

function looksLikeCaneSummaryRowStart(line: string) {
  return /^\s*(?:\d+\s+\d+|\d{5,7})\s+/.test(line);
}

function uniqueCaneSummaryRows(rows: NormalizedEntry[]) {
  const byKey = new Map<string, NormalizedEntry>();

  for (const row of rows) {
    const key = [
      row.entryDate?.toISOString().slice(0, 10) ?? "",
      normalizeText(row.farmCodeRaw ?? ""),
      normalizeText(row.fieldRaw ?? ""),
      row.netWeight?.toFixed(3) ?? "",
      row.tripCount ?? ""
    ].join("|");
    const current = byKey.get(key);

    if (!current || scoreCaneSummaryRow(row) > scoreCaneSummaryRow(current)) {
      byKey.set(key, row);
    }
  }

  return Array.from(byKey.values());
}

function scoreCaneSummaryRow(row: NormalizedEntry) {
  const farm = row.farmRaw?.trim() ?? "";
  const normalizedFarm = normalizeText(farm);
  const agriculturalMarker = /\b(faz|fazenda|sitio|chacara|estancia)\b/.test(normalizedFarm) ? 1000 : 0;
  const usefulLength = Math.min(farm.length, 200);
  return agriculturalMarker + usefulLength;
}

function reconcileCaneSummaryRows(
  rows: NormalizedEntry[],
  metadata: Pick<ImportBatchMetadata, "totalNetWeight" | "totalTrips">,
  extractionSource: CaneSummaryExtractionSource
): CaneSummaryReconciliation {
  const parsedNetWeight = roundCaneWeight(rows.reduce((total, row) => total + (row.netWeight ?? 0), 0));
  const parsedTrips = rows.reduce((total, row) => total + (row.tripCount ?? 0), 0);
  const expectedNetWeight = metadata.totalNetWeight;
  const expectedTrips = metadata.totalTrips;
  const netWeightDifference = expectedNetWeight === undefined ? undefined : roundCaneWeight(parsedNetWeight - expectedNetWeight);
  const tripDifference = expectedTrips === undefined ? undefined : parsedTrips - expectedTrips;
  const hasExpectedTotals = expectedNetWeight !== undefined && expectedTrips !== undefined;
  const status = !hasExpectedTotals
    ? "NOT_AVAILABLE"
    : Math.abs(netWeightDifference ?? Number.POSITIVE_INFINITY) <= 0.005 && tripDifference === 0
      ? "MATCH"
      : "MISMATCH";

  return {
    status,
    expectedNetWeight,
    parsedNetWeight,
    netWeightDifference,
    expectedTrips,
    parsedTrips,
    tripDifference,
    extractionSource,
    assisted: extractionSource !== "local"
  };
}

function roundCaneWeight(value: number) {
  return Math.round((value + Number.EPSILON) * 1000) / 1000;
}

function uniqueTextVariants(texts: string[]) {
  const byCompactText = new Map<string, string>();

  for (const text of texts) {
    const compact = text.replace(/\s+/g, " ").trim();

    if (compact && !byCompactText.has(compact)) {
      byCompactText.set(compact, text);
    }
  }

  return Array.from(byCompactText.values());
}

function shouldTryCaneSummaryOcr(textVariants: string[]) {
  const compactLength = textVariants.join("\n").replace(/\s/g, "").length;
  return compactLength < 300;
}

async function extractCaneSummaryPdfOcrText(filePath: string) {
  const tempDir = path.join(os.tmpdir(), `agricola-scs0110p-${randomUUID()}`);

  try {
    await fs.mkdir(tempDir, { recursive: true });
    const prefix = path.join(tempDir, "page");

    try {
      await execFileAsync("pdftoppm", ["-png", "-r", "220", filePath, prefix], {
        timeout: 180_000,
        maxBuffer: 8 * 1024 * 1024
      });
    } catch {
      return "";
    }

    const imageFiles = (await fs.readdir(tempDir))
      .filter((fileName) => /^page-\d+\.png$/i.test(fileName) || /^page\.png$/i.test(fileName))
      .sort((left, right) => compareRenderedPageNames(left, right));
    const chunks: string[] = [];

    for (const imageFile of imageFiles) {
      const imagePath = path.join(tempDir, imageFile);
      const text = await readImageOcrText(imagePath);

      if (text.trim()) {
        chunks.push(text);
      }
    }

    return chunks.join("\n");
  } finally {
    await fs.rm(tempDir, { recursive: true, force: true }).catch(() => undefined);
  }
}

async function readImageOcrText(imagePath: string) {
  for (const args of [
    [imagePath, "stdout", "-l", "por+eng", "--psm", "6"],
    [imagePath, "stdout", "-l", "eng", "--psm", "6"],
    [imagePath, "stdout", "-l", "por+eng", "--psm", "11"]
  ]) {
    try {
      const { stdout } = await execFileAsync("tesseract", args, {
        timeout: 120_000,
        maxBuffer: 8 * 1024 * 1024
      });

      if (stdout.trim()) {
        return stdout;
      }
    } catch {
      // Try the next OCR mode/language.
    }
  }

  return "";
}

function compareRenderedPageNames(left: string, right: string) {
  return extractRenderedPageNumber(left) - extractRenderedPageNumber(right) || left.localeCompare(right);
}

function extractRenderedPageNumber(fileName: string) {
  return Number(/page-(\d+)\.png$/i.exec(fileName)?.[1] ?? "1");
}

async function extractPdfBboxText(filePath: string) {
  try {
    const { stdout } = await execFileAsync("pdftotext", ["-bbox-layout", filePath, "-"], {
      maxBuffer: 10 * 1024 * 1024
    });
    return stdout;
  } catch {
    throw badRequest("Nao foi possivel ler as posicoes do PDF. Instale o pacote poppler-utils para habilitar pdftotext.");
  }
}

function parseCaneSummaryPdfBboxRows(text: string, entryDate: Date | undefined): PdfHighlightRow[] {
  const pages = parsePdfBboxPages(text);
  const rows = pages.flatMap((page) => parseCaneSummaryPdfPageRows(page, entryDate));

  if (rows.length === 0) {
    throw badRequest("PDF sem linhas de talhao validas para marcar.");
  }

  return rows;
}

function parseCaneSummaryPdfBboxRowsOrEmpty(text: string, entryDate: Date | undefined): PdfHighlightRow[] {
  if (!text.trim()) {
    return [];
  }

  const pages = parsePdfBboxPages(text);
  return pages.flatMap((page) => parseCaneSummaryPdfPageRows(page, entryDate));
}

function parsePdfBboxPages(text: string): PdfBboxPage[] {
  const pages: PdfBboxPage[] = [];
  const pageRegex = /<page\s+width="([\d.]+)"\s+height="([\d.]+)">([\s\S]*?)<\/page>/g;
  let pageMatch: RegExpExecArray | null;

  while ((pageMatch = pageRegex.exec(text))) {
    const words: PdfBboxWord[] = [];
    const wordRegex = /<word\s+xMin="([\d.]+)"\s+yMin="([\d.]+)"\s+xMax="([\d.]+)"\s+yMax="([\d.]+)">([\s\S]*?)<\/word>/g;
    let wordMatch: RegExpExecArray | null;

    while ((wordMatch = wordRegex.exec(pageMatch[3]))) {
      const word = decodeXmlText(wordMatch[5]).trim();

      if (!word) {
        continue;
      }

      words.push({
        text: word,
        xMin: Number(wordMatch[1]),
        yMin: Number(wordMatch[2]),
        xMax: Number(wordMatch[3]),
        yMax: Number(wordMatch[4])
      });
    }

    pages.push({
      index: pages.length,
      width: Number(pageMatch[1]),
      height: Number(pageMatch[2]),
      words
    });
  }

  return pages;
}

function parseCaneSummaryPdfPageRows(page: PdfBboxPage, entryDate: Date | undefined): PdfHighlightRow[] {
  const groups: Array<{ yMid: number; words: PdfBboxWord[] }> = [];
  const sortedWords = [...page.words].sort((left, right) => {
    const yDiff = getWordYMid(left) - getWordYMid(right);
    return Math.abs(yDiff) > 0.5 ? yDiff : left.xMin - right.xMin;
  });

  for (const word of sortedWords) {
    const yMid = getWordYMid(word);
    let group = groups.find((item) => Math.abs(item.yMid - yMid) <= 2);

    if (!group) {
      group = { yMid, words: [] };
      groups.push(group);
    }

    group.words.push(word);
    group.yMid = (group.yMid * (group.words.length - 1) + yMid) / group.words.length;
  }

  const bounds = findCaneSummaryColumnBounds(groups, page.index);

  return groups
    .map((group) => {
      const words = [...group.words].sort((left, right) => left.xMin - right.xMin);
      const codeWords = words.filter((word) => word.xMin >= bounds[0] && word.xMin < bounds[1]);
      const code = codeWords.map((word) => word.text).join(" ");

      if (!/^\d/.test(code)) {
        return null;
      }

      const cell = (index: number) => words
        .filter((word) => word.xMin >= bounds[index] && word.xMax <= bounds[index + 1])
        .map((word) => word.text).join(" ").trim();
      const fieldWords = words.filter((word) => word.xMin >= bounds[3] && word.xMax <= bounds[4] && /^\d+[A-Za-z0-9./-]*$/.test(word.text));
      const fieldRaw = fieldWords.length === 1 ? fieldWords[0].text : "";
      // Fields are right-aligned at x=407.798 in the reference form. A farm-name
      // digit entering the left side of an otherwise empty field is ambiguous.
      const fieldScale = (bounds[4] - bounds[3]) / 32.25;
      const fieldRight = bounds[4] - 3.802 * fieldScale;
      const cane = cell(6);
      const trips = cell(7);
      const codeMatch = /^(\d{3})\s+(\d{1,4})$/.exec(code) ?? /^(\d{3})(\d{2,4})$/.exec(code);
      const netWeight = /^(?:\d{1,3}(?:\.\d{3})*|\d+),\d{3}$/.test(cane) ? parseDecimalNumber(cane) : undefined;
      const tripCount = /^\d+$/.test(trips) ? Number(trips) : NaN;
      const farmWords = words.filter((word) => word.xMin >= bounds[2] && word.xMin < (fieldWords[0]?.xMin ?? bounds[3]));
      const farmRaw = farmWords.map((word) => word.text).join(" ").trim();

      // Area is intentionally opaque. An empty/malformed area cannot shift any
      // other cell. A field joined to overflowing name text needs review.
      if (!codeMatch || !/^\d+[A-Za-z0-9./-]*$/.test(fieldRaw) || !farmRaw ||
          Math.abs(fieldWords[0].xMax - fieldRight) > fieldScale ||
          farmWords.some((word) => word.xMax > fieldWords[0].xMin) ||
          words.some((word) => word !== fieldWords[0] && word.xMin >= bounds[3] && word.xMin < bounds[4] && word.xMax > fieldWords[0].xMin) ||
          netWeight === undefined || !Number.isSafeInteger(Math.round(netWeight * 1000)) ||
          !Number.isSafeInteger(tripCount) || tripCount <= 0) {
        throwCaneSummaryColumnError(`Pagina ${page.index + 1}, linha em y=${group.yMid.toFixed(1)}: codigo, Talhao, nome ou peso/viagens fora das colunas. Confira a linha no PDF; a leitura nao foi completada por outros numeros.`);
      }

      const row: NormalizedEntry = {
        ticketNumber: `${entryDate?.toISOString().slice(0, 10) ?? "sem-data"}-${fieldRaw}`,
        entryDate,
        farmCodeRaw: `${codeMatch[1]}-${codeMatch[2].padStart(3, "0")}`,
        farmRaw,
        fieldRaw,
        netWeight,
        tripCount
      };

      if (!row) {
        return null;
      }

      return {
        pageIndex: page.index,
        pageWidth: page.width,
        yMin: Math.min(...words.map((word) => word.yMin)),
        yMax: Math.max(...words.map((word) => word.yMax)),
        row
      };
    })
    .filter((row): row is PdfHighlightRow => Boolean(row));
}

function throwCaneSummaryColumnError(message: string): never {
  const error = badRequest(message);
  error.name = "CaneSummaryColumnError";
  throw error;
}

function findCaneSummaryColumnBounds(groups: Array<{ words: PdfBboxWord[] }>, pageIndex: number): number[] {
  const labels = ["codigo", "fornecedor", "fundo agricola", "talhao", "km", "area", "cana entregue", "viagens"];
  const referenceAnchors = [26.1, 122.85, 273.6, 382.35, 415.35, 443.85, 478.35, 541.35];
  // SCS0110P column borders measured from the fixed report grid, in PDF points.
  const referenceBounds = [12, 62.1, 220.35, 379.35, 411.6, 433.35, 474.6, 536.1, 577.35];

  for (const group of groups) {
    const words = [...group.words].sort((a, b) => a.xMin - b.xMin);
    const anchors = labels.map((label) => {
      const parts = label.split(" ");
      const matches = words.filter((_word, index) => parts.every((part, offset) => normalizeText(words[index + offset]?.text ?? "") === part));
      return matches.length === 1 ? matches[0].xMin : NaN;
    });
    if (anchors.some((value) => !Number.isFinite(value))) continue;
    const scale = (anchors[7] - anchors[0]) / (referenceAnchors[7] - referenceAnchors[0]);
    const translation = anchors[0] - referenceAnchors[0] * scale;
    if (scale < 0.9 || scale > 1.1 || anchors.some((value, index) => Math.abs(value - (referenceAnchors[index] * scale + translation)) > 2)) break;
    return referenceBounds.map((value) => value * scale + translation);
  }

  return throwCaneSummaryColumnError(`Pagina ${pageIndex + 1}: as oito colunas do SCS0110P nao foram reconhecidas com seguranca.`);
}

function buildBboxLineText(words: PdfBboxWord[]) {
  let line = "";
  let lastX = 0;

  for (const word of words) {
    if (line) {
      const gap = Math.max(0, word.xMin - lastX);
      const spaces = Math.max(1, Math.min(60, Math.round(gap / 3)));
      line += " ".repeat(spaces);
    }

    line += word.text;
    lastX = word.xMax;
  }

  return line;
}

function getWordYMid(word: PdfBboxWord) {
  return (word.yMin + word.yMax) / 2;
}

function decodeXmlText(value: string) {
  return value
    .replace(/&amp;/g, "&")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/&#(\d+);/g, (_match, code) => String.fromCodePoint(Number(code)))
    .replace(/&#x([\da-f]+);/gi, (_match, code) => String.fromCodePoint(Number.parseInt(code, 16)));
}

function parseCaneSummaryPdfLine(line: string, entryDate: Date | undefined): NormalizedEntry | null {
  const normalizedLine = normalizePdfLineForParsing(line);
  const lineLabel = normalizeText(normalizedLine);

  if (
    !normalizedLine.trim() ||
    lineLabel.includes("total") ||
    lineLabel.includes("codigo") ||
    lineLabel.includes("periodo")
  ) {
    return null;
  }

  const rightMatch = matchCaneSummaryRightPart(normalizedLine);

  if (!rightMatch?.groups || rightMatch.index === undefined) {
    return null;
  }

  const left = normalizedLine.slice(0, rightMatch.index).trim();
  const leftMatch = parseCaneSummaryLeftPart(left);

  if (!leftMatch) {
    return null;
  }

  const description = leftMatch.description.trim();
  const parts = description.split(/\s{2,}/).map((part) => part.trim()).filter(Boolean);
  const farmRaw = parts.length > 1 ? parts[parts.length - 1] : extractFarmFallback(description) ?? description;

  if (!farmRaw) {
    return null;
  }

  const fieldRaw = rightMatch.groups.field;
  const farmCodeRaw = `${leftMatch.originCode}-${leftMatch.supplierCode.padStart(3, "0")}`;
  const netWeight = parseDecimalNumber(rightMatch.groups.cane);
  const tripCount = Number(rightMatch.groups.trips);
  const ticketDate = entryDate ? entryDate.toISOString().slice(0, 10) : "sem-data";

  if (netWeight === undefined || !Number.isFinite(tripCount)) {
    return null;
  }

  return {
    ticketNumber: `${ticketDate}-${fieldRaw}`,
    entryDate,
    farmCodeRaw,
    farmRaw,
    fieldRaw,
    netWeight,
    tripCount
  };
}

function matchCaneSummaryRightPart(line: string) {
  const flexibleMatch = /(?<field>\d+[A-Za-z0-9./-]*)\s+(?:(?<km>\d+(?:[,.]\d+)?)\s+)?(?:(?<area>\d+(?:[,.]\d+)?|,\d+)\s+)?(?<cane>\d{1,3}(?:\.\d{3})*,\d{3}|\d+,\d{3})\s*(?<trips>\d+)\s*$/.exec(line);

  if (!flexibleMatch?.groups || flexibleMatch.index === undefined) {
    return null;
  }

  const whitespaceBefore = line.slice(0, flexibleMatch.index).match(/\s*$/)?.[0] ?? "";

  if (whitespaceBefore.length !== 1 || !/^\d$/.test(flexibleMatch.groups.field)) {
    return flexibleMatch;
  }

  // A numeric farm suffix can consume the optional KM/area slots. Prefer the next
  // complete, column-aligned suffix while retaining glued-field rows as-is.
  const remainingLine = line.slice(flexibleMatch.index + flexibleMatch.groups.field.length);
  const alignedMatch = /^(?<boundary>\s{2,})(?<field>\d+[A-Za-z0-9./-]*)\s+(?:(?<km>\d+(?:[,.]\d+)?)\s+)?(?:(?<area>\d+(?:[,.]\d+)?|,\d+)\s+)?(?<cane>\d{1,3}(?:\.\d{3})*,\d{3}|\d+,\d{3})\s*(?<trips>\d+)\s*$/.exec(remainingLine);

  if (!alignedMatch?.groups) {
    return flexibleMatch;
  }

  return {
    groups: alignedMatch.groups,
    index: flexibleMatch.index + flexibleMatch.groups.field.length + alignedMatch.groups.boundary.length
  };
}

function parseCaneSummaryLeftPart(left: string) {
  const spaced = /^(\d+)\s+(\d+)\s+(.+)$/.exec(left);

  if (spaced) {
    return {
      originCode: spaced[1],
      supplierCode: spaced[2],
      description: spaced[3]
    };
  }

  const compact = /^(\d{3})(\d{2,4})\s+(.+)$/.exec(left);

  if (!compact) {
    return null;
  }

  return {
    originCode: compact[1],
    supplierCode: compact[2],
    description: compact[3]
  };
}

function extractFarmFallback(description: string) {
  const normalizedDescription = normalizeText(description);
  const markerIndexes = ["fazenda ", "faz ", "sitio ", "chacara ", "estancia "]
    .map((marker) => normalizedDescription.lastIndexOf(marker))
    .filter((index) => index >= 0);
  const farmIndex = markerIndexes.length > 0 ? Math.max(...markerIndexes) : -1;

  if (farmIndex >= 0) {
    return description.slice(farmIndex).trim();
  }

  return undefined;
}

function buildEntryNotes(classificationNote: string | undefined, tripCount: number | undefined) {
  const tripNote = tripCount === undefined ? undefined : `Viagens: ${tripCount}.`;

  return [classificationNote, tripNote].filter(Boolean).join(" ") || undefined;
}

async function calculateFileHash(filePath: string) {
  const bytes = await fs.readFile(filePath);
  return createHash("sha256").update(bytes).digest("hex");
}

function formatStoredDateTime(value: string) {
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString("pt-BR");
}

function formatStoredPeriod(start: string | null | undefined, end: string | null | undefined) {
  if (!start) {
    return "sem data";
  }

  const formattedStart = formatStoredDateOnly(start);
  const formattedEnd = formatStoredDateOnly(end ?? start);

  return formattedStart === formattedEnd ? formattedStart : `${formattedStart} a ${formattedEnd}`;
}

function formatStoredDateOnly(value: string) {
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(value);

  if (!match) {
    return value;
  }

  return `${match[3]}/${match[2]}/${match[1]}`;
}

function detectMapping(columns: string[], customMapping?: ImportMappingInput): ImportMappingInput {
  const mapping: ImportMappingInput = {};

  for (const key of Object.keys(columnAliases) as Array<keyof ImportMappingInput>) {
    mapping[key] = customMapping?.[key] || findColumn(columns, columnAliases[key]);
  }

  return mapping;
}

function findColumn(columns: string[], aliases: string[]) {
  const normalizedAliases = aliases.map(normalizeText);

  return columns.find((column) => {
    const normalizedColumn = normalizeText(column);
    return normalizedAliases.some((alias) => normalizedColumn.includes(alias));
  });
}

export function normalizeRow(row: RawRow, mapping: ImportMappingInput): NormalizedEntry {
  const farmRaw = readString(row, mapping.farm);
  let normalizedFarmRaw = farmRaw;

  if (farmRaw) {
    const match = farmRaw.match(/\d{3}-\d{4}/);
    if (match) {
      normalizedFarmRaw = match[0];
    }
  }

  return {
    ticketNumber: readString(row, mapping.ticketNumber),
    entryDate: readDate(row, mapping.entryDate),
    farmCodeRaw: readString(row, "farmCodeRaw"),
    farmRaw: normalizedFarmRaw,
    fieldRaw: readString(row, mapping.field),
    orderRaw: readString(row, mapping.order),
    vehiclePlate: readString(row, mapping.vehiclePlate),
    grossWeight: readNumber(row, mapping.grossWeight),
    netWeight: readNumber(row, mapping.netWeight),
    tripCount: readDirectNumber(row.tripCount)
  };
}

export function unrollNormalizedRow(row: NormalizedEntry): NormalizedEntry[] {
  const tripCount = row.tripCount ?? 1;
  if (tripCount <= 1 || row.netWeight === undefined) {
    return [row];
  }

  const baseWeight = Math.floor((row.netWeight / tripCount) * 1000) / 1000;
  const remainder = row.netWeight - (baseWeight * (tripCount - 1));
  const baseGross = row.grossWeight !== undefined ? Math.floor((row.grossWeight / tripCount) * 1000) / 1000 : undefined;

  return Array.from({ length: tripCount }).map((_, i) => {
    const isLast = i === tripCount - 1;
    const weightForTrip = isLast ? remainder : baseWeight;

    return {
      ...row,
      ticketNumber: row.ticketNumber ? `${row.ticketNumber}-${i + 1}` : undefined,
      netWeight: Math.round(weightForTrip * 1000) / 1000,
      grossWeight: baseGross,
      tripCount: 1 // row now represents 1 trip
    };
  });
}

function createClassificationContext(sourceType: DetectionResult["sourceType"]): ClassificationContext | undefined {
  if (sourceType !== "SCS0110P_PDF") {
    return undefined;
  }

  const farms = listFarms();
  const farmsByExactRaw = new Map<string, FarmRecord>();
  const farmsByRawCode = new Map<string, FarmRecord>();
  const farmsByExactCode = new Map<string, FarmRecord | null>();
  const farmsByCanonicalCode = new Map<string, FarmRecord | null>();
  const fieldsByFarmAndCode = new Map<string, FieldRecord>();
  const ordersByField = new Map<string, HarvestOrderRecord[]>();

  for (const farm of farms) {
    addFarmLookup(farmsByExactRaw, normalizeLookupText(farm.name), farm);
    addFarmLookup(farmsByExactRaw, normalizeLookupText(farm.code ?? ""), farm);
    addFarmLookup(farmsByRawCode, normalizeFarmLookupCode(farm.name), farm);
    addFarmLookup(farmsByRawCode, normalizeFarmLookupCode(farm.code ?? ""), farm);
    addUniqueFarmCodeLookup(farmsByExactCode, normalizeFarmLookupCode(farm.code ?? ""), farm);
    addUniqueFarmCodeLookup(farmsByCanonicalCode, normalizeExplicitFarmCode(farm.code ?? ""), farm);

    for (const field of farm.fields) {
      fieldsByFarmAndCode.set(buildFieldLookupKey(farm.id, field.code), field);
    }
  }

  for (const order of listOrders()) {
    for (const orderField of order.fields) {
      const key = buildOrderFieldKey(orderField.field.farmId, orderField.fieldId);

      const orders = ordersByField.get(key) ?? [];
      orders.push(order);
      ordersByField.set(key, orders);
    }
  }

  return {
    farms,
    farmsByExactRaw,
    farmsByRawCode,
    farmsByExactCode,
    farmsByCanonicalCode,
    fieldsByFarmAndCode,
    ordersByField
  };
}

function addFarmLookup(map: Map<string, FarmRecord>, key: string, farm: FarmRecord) {
  if (key && !map.has(key)) {
    map.set(key, farm);
  }
}

function addUniqueFarmCodeLookup(map: Map<string, FarmRecord | null>, key: string, farm: FarmRecord) {
  if (!key) {
    return;
  }

  const existing = map.get(key);
  if (existing && existing.id !== farm.id) {
    map.set(key, null);
  } else if (!map.has(key)) {
    map.set(key, farm);
  }
}

function buildOrderFieldKey(farmId: string, fieldId: string) {
  return `${farmId}::${fieldId}`;
}

function buildFieldLookupKey(farmId: string, code: string) {
  return `${farmId}::${normalizeFieldLookupCode(code)}`;
}

function findFarmInContext(context: ClassificationContext | undefined, raw: string, code?: string) {
  if (!context) {
    return findFarmByRaw(raw, code);
  }

  const normalizedRaw = normalizeLookupText(raw);
  const normalizedRawCode = normalizeFarmLookupCode(raw);
  const explicitCode = code?.trim();

  if (explicitCode) {
    const codeMatch =
      context.farmsByExactCode.get(normalizeFarmLookupCode(explicitCode)) ??
      context.farmsByCanonicalCode.get(normalizeExplicitFarmCode(explicitCode));

    // A code supplied by the source is authoritative. Falling back to a similar
    // name here silently merged distinct suppliers such as 200-2472 into 200-2471.
    return codeMatch ?? null;
  }

  const exactMatch = context.farmsByExactRaw.get(normalizedRaw) ?? context.farmsByRawCode.get(normalizedRawCode);

  if (exactMatch) {
    return exactMatch;
  }

  const prefixMatches = context.farms.filter((farm) => {
    const normalizedNameCode = normalizeFarmLookupCode(farm.name);

    return (
      normalizedRawCode.length >= 12 &&
      normalizedNameCode.length >= 12 &&
      (normalizedRawCode.startsWith(normalizedNameCode) || normalizedNameCode.startsWith(normalizedRawCode))
    );
  });

  return prefixMatches.length === 1 ? prefixMatches[0] : null;
}

function findFieldInContext(context: ClassificationContext | undefined, farmId: string, code: string) {
  if (!context) {
    return findFieldByFarmAndCode(farmId, code);
  }

  return context.fieldsByFarmAndCode.get(buildFieldLookupKey(farmId, code)) ?? null;
}

function findOrderForFieldInContext(
  context: ClassificationContext | undefined,
  farmId: string,
  fieldId: string,
  entryDate?: Date | string | null
) {
  const key = buildOrderFieldKey(farmId, fieldId);
  const orders = context?.ordersByField.get(key) ?? listOrders();
  return findOrderForFieldByEntryDate(orders, farmId, fieldId, entryDate);
}

export function findOrderForFieldByEntryDate(
  orders: HarvestOrderRecord[],
  farmId: string,
  fieldId: string,
  entryDate?: Date | string | null
) {
  const candidates = orders.filter((order) =>
    order.fields.some((orderField) => orderField.fieldId === fieldId && orderField.field.farmId === farmId)
  );
  const entryDay = normalizeEntryDay(entryDate);

  if (!entryDay) {
    const active = candidates.filter((order) => order.status === "ACTIVE");
    return active.length === 1 ? active[0] : null;
  }

  const matches = candidates.filter((order) => orderContainsEntryDay(order, entryDay));
  if (matches.length === 1) {
    return matches[0];
  }

  const activeMatches = matches.filter((order) => order.status === "ACTIVE");
  return activeMatches.length === 1 ? activeMatches[0] : null;
}

function normalizeEntryDay(value?: Date | string | null) {
  if (!value) {
    return null;
  }
  if (value instanceof Date) {
    return Number.isNaN(value.getTime()) ? null : value.toISOString().slice(0, 10);
  }
  const match = /^\d{4}-\d{2}-\d{2}/.exec(value.trim());
  return match?.[0] ?? null;
}

function orderContainsEntryDay(order: HarvestOrderRecord, entryDay: string) {
  const start = normalizeEntryDay(order.startDate);
  const end = normalizeEntryDay(order.endDate);

  if (!start && !end) {
    return order.status === "ACTIVE";
  }
  return (!start || entryDay >= start) && (!end || entryDay <= end);
}

function normalizeLookupText(value: string) {
  return value
    .normalize("NFD")
    .replace(/\p{Diacritic}/gu, "")
    .toLowerCase()
    .trim();
}

function normalizeFarmLookupCode(value: string) {
  return normalizeLookupText(value).replace(/[^a-z0-9]/g, "");
}

function normalizeExplicitFarmCode(value: string) {
  const match = /^\s*(\d{3})\D*(\d+)\s*$/.exec(value);

  if (!match) {
    return "";
  }

  const origin = match[1].replace(/^0+(?=\d)/, "");
  const supplier = match[2].replace(/^0+(?=\d)/, "");
  return `${origin}:${supplier}`;
}

function normalizeFieldLookupCode(value: string) {
  const normalized = normalizeFarmLookupCode(value);

  if (/^\d+$/.test(normalized)) {
    return normalized.replace(/^0+(?=\d)/, "");
  }

  return normalized;
}

function classifyNormalizedRow(
  row: NormalizedEntry,
  sourceType: DetectionResult["sourceType"],
  context?: ClassificationContext
): PreviewEntry {
  const classified = classifyRow(row, sourceType, context);

  return {
    ...row,
    orderRaw: row.orderRaw ?? classified.orderNumber,
    fieldId: classified.fieldId,
    areaHa: classified.areaHa,
    areaAlq: classified.areaAlq,
    status: classified.status,
    notes: classified.notes
  };
}

function summarizePreview(rows: PreviewEntry[], reconciliation?: CaneSummaryReconciliation): ImportPreviewSummary {
  const counts = new Map<EntryStatus, number>();

  for (const row of rows) {
    counts.set(row.status, (counts.get(row.status) ?? 0) + 1);
  }

  const areaByDate = summarizePreviewAreaByDate(rows);

  return {
    rowCount: rows.length,
    okCount: rows.filter((row) => row.status === "OK").length,
    errorCount: rows.filter((row) => row.status !== "OK").length,
    byStatus: [...counts.entries()].map(([status, count]) => ({ status, count })),
    areaHa: areaByDate.reduce((total, item) => total + item.areaHa, 0),
    areaAlq: areaByDate.reduce((total, item) => total + item.areaAlq, 0),
    areaByDate,
    reconciliation
  };
}

function assertCaneSummaryReconciled(parsed: ParsedRows) {
  if (parsed.sourceType !== "SCS0110P_PDF") {
    return;
  }

  const reconciliation = parsed.metadata?.reconciliation;

  if (reconciliation?.status === "MATCH") {
    return;
  }

  if (reconciliation?.status === "MISMATCH") {
    throw badRequest(
      `A leitura do PDF nao fecha com o TOTAL GERAL: ${formatCaneWeight(reconciliation.parsedNetWeight)} t e ${reconciliation.parsedTrips} viagens lidas; ` +
        `${formatCaneWeight(reconciliation.expectedNetWeight ?? 0)} t e ${reconciliation.expectedTrips ?? 0} viagens esperadas. Os dados nao foram inseridos.`
    );
  }

  throw badRequest("Nao foi possivel conferir o peso e as viagens com o TOTAL GERAL do PDF. Os dados nao foram inseridos.");
}

function formatCaneWeight(value: number) {
  return value.toLocaleString("pt-BR", { minimumFractionDigits: 3, maximumFractionDigits: 3 });
}

function summarizePreviewAreaByDate(rows: PreviewEntry[]) {
  return summarizeUniqueHarvestAreaByDate(
    rows.flatMap((row) =>
      row.entryDate && row.fieldId
        ? [{
            date: row.entryDate.toISOString().slice(0, 10),
            fieldId: row.fieldId,
            areaHa: row.areaHa,
            areaAlq: row.areaAlq,
            hasDivergence: row.status !== "OK"
          }]
        : []
    )
  ).map(({ date, fieldCount, areaHa, areaAlq }) => ({ date, fieldCount, areaHa, areaAlq }));
}

function prioritizePreviewRows(rows: PreviewEntry[]) {
  return [...rows.filter((row) => row.status !== "OK"), ...rows.filter((row) => row.status === "OK")];
}

function classifyRow(
  row: NormalizedEntry,
  sourceType: DetectionResult["sourceType"],
  context?: ClassificationContext
): ClassifiedEntry {
  if (sourceType === "SCS0110P_PDF") {
    return classifyCaneSummaryRow(row, context);
  }

  return classifySpreadsheetRow(row);
}

function classifySpreadsheetRow(row: NormalizedEntry): ClassifiedEntry {
  if (!row.farmRaw || !row.fieldRaw) {
    return {
      status: "MISSING_DATA",
      notes: "Linha sem fazenda ou talhao."
    };
  }

  const farm = findFarmByRaw(row.farmRaw, row.farmCodeRaw);

  if (!farm) {
    return {
      status: "FARM_NOT_FOUND",
      notes: `Fazenda ${row.farmRaw} nao cadastrada.`
    };
  }

  const field = findFieldByFarmAndCode(farm.id, row.fieldRaw);

  if (!field) {
    return {
      status: "FIELD_NOT_FOUND",
      farmId: farm.id,
      notes: `Talhao ${row.fieldRaw} nao cadastrado para ${farm.name}.`
    };
  }

  if (row.orderRaw) {
    const ordersWithSameNumber = listOrdersWithNumber(row.orderRaw);

    if (ordersWithSameNumber.length > 0) {
      const preferredOrders = ordersWithSameNumber.some((order) => order.status === "ACTIVE")
        ? ordersWithSameNumber.filter((order) => order.status === "ACTIVE")
        : ordersWithSameNumber;
      const farmOrders = preferredOrders.filter((order) => order.farmIds.includes(farm.id));
      const releasedOrder = preferredOrders.find((order) => order.fields.some((orderField) => orderField.fieldId === field.id));

      if (releasedOrder) {
      return {
        status: "OK",
        farmId: farm.id,
        fieldId: field.id,
        areaHa: field.areaHa,
        areaAlq: field.areaAlq,
        orderId: releasedOrder.id
      };
      }

      if (farmOrders.length === 0) {
        const order = preferredOrders[0];
        return {
          status: "FARM_MISMATCH",
          farmId: farm.id,
          fieldId: field.id,
          orderId: order.id,
          areaHa: field.areaHa,
          areaAlq: field.areaAlq,
          notes: `OS ${order.number} nao inclui ${farm.name}.`
        };
      }

      const order = farmOrders[0];
      return {
        status: "FIELD_NOT_RELEASED",
        farmId: farm.id,
        fieldId: field.id,
        orderId: order.id,
        areaHa: field.areaHa,
        areaAlq: field.areaAlq,
        notes: `Talhao ${field.code} nao esta na OS ${order.number}.`
      };
    }
  }

  const activeOrder = findOrderForFieldByEntryDate(listOrders(), farm.id, field.id, row.entryDate);

  if (!activeOrder) {
    const orderNote = row.orderRaw ? `OS ${row.orderRaw} nao cadastrada. ` : "";

    return {
      status: "FIELD_NOT_RELEASED",
      farmId: farm.id,
      fieldId: field.id,
      areaHa: field.areaHa,
      areaAlq: field.areaAlq,
      notes: `${orderNote}Talhao ${field.code} nao esta na lista de talhoes em colheita.`
    };
  }

  return {
    status: "OK",
    farmId: farm.id,
    fieldId: field.id,
    orderId: activeOrder.id,
    orderNumber: activeOrder.number,
    areaHa: field.areaHa,
    areaAlq: field.areaAlq
  };
}

function classifyCaneSummaryRow(row: NormalizedEntry, context?: ClassificationContext): ClassifiedEntry {
  if (!row.farmRaw || !row.fieldRaw) {
    return {
      status: "MISSING_DATA",
      notes: "Linha sem fazenda ou talhao."
    };
  }

  const farm = findFarmInContext(context, row.farmRaw, row.farmCodeRaw);

  if (!farm) {
    return {
      status: "FARM_NOT_FOUND",
      notes: `Fazenda ${row.farmRaw} nao cadastrada.`
    };
  }

  const field = findFieldInContext(context, farm.id, row.fieldRaw);

  if (!field) {
    return {
      status: "FIELD_NOT_FOUND",
      farmId: farm.id,
      notes: `Talhao ${row.fieldRaw} nao cadastrado para ${farm.name}.`
    };
  }

  const order = findOrderForFieldInContext(context, farm.id, field.id, row.entryDate);

  if (!order) {
    return {
      status: "FIELD_NOT_RELEASED",
      farmId: farm.id,
      fieldId: field.id,
      areaHa: field.areaHa,
      areaAlq: field.areaAlq,
      notes: `Talhao ${field.code} nao esta na lista de talhoes em colheita.`
    };
  }

  return {
    status: "OK",
    farmId: farm.id,
    fieldId: field.id,
    orderId: order.id,
    orderNumber: order.number,
    areaHa: field.areaHa,
    areaAlq: field.areaAlq
  };
}

function readString(row: RawRow, column?: string) {
  if (!column) {
    return undefined;
  }

  const value = row[column];

  if (value === undefined || value === null) {
    return undefined;
  }

  const text = String(value).trim();
  return text || undefined;
}

function readDate(row: RawRow, column?: string) {
  const value = column ? row[column] : undefined;

  return parseImportDate(value);
}

export function readNumber(row: RawRow, column?: string) {
  const value = column ? row[column] : undefined;

  if (value === undefined || value === null || value === "") {
    return undefined;
  }

  if (typeof value === "number") {
    return value;
  }

  const text = String(value).replace(/\s/g, "").trim();
  const normalized = text.includes(",") ? text.replace(/\./g, "").replace(",", ".") : text;

  const parsed = Number(normalized);
  return Number.isNaN(parsed) ? undefined : parsed;
}

function readDirectNumber(value: unknown) {
  if (typeof value === "number") {
    return value;
  }

  if (value === undefined || value === null || value === "") {
    return undefined;
  }

  const parsed = Number(String(value).trim());
  return Number.isNaN(parsed) ? undefined : parsed;
}

function parseDecimalNumber(value: string) {
  const normalized = value.replace(/\./g, "").replace(",", ".");
  const parsed = Number(normalized);
  return Number.isNaN(parsed) ? undefined : parsed;
}

export function parseImportDate(value: unknown) {
  if (value === undefined || value === null || value === "") {
    return undefined;
  }

  if (value instanceof Date) {
    return Number.isNaN(value.getTime()) ? undefined : value;
  }

  if (typeof value === "number") {
    const excelEpoch = Date.UTC(1899, 11, 30);
    const parsed = new Date(excelEpoch + value * 24 * 60 * 60 * 1000);
    return Number.isNaN(parsed.getTime()) ? undefined : parsed;
  }

  const text = String(value).trim();
  const brDate = /^(\d{1,2})[/. -](\d{1,2})[/. -](\d{2,4})(?:\s+(\d{1,2}):(\d{2})(?::(\d{2}))?)?$/.exec(text);

  if (brDate) {
    const [, day, month, rawYear, hour = "0", minute = "0", second = "0"] = brDate;
    const year = rawYear.length === 2 ? Number(rawYear) + (Number(rawYear) >= 70 ? 1900 : 2000) : Number(rawYear);
    return buildUtcDate(year, Number(month), Number(day), Number(hour), Number(minute), Number(second));
  }

  const isoDate = /^(\d{4})-(\d{1,2})-(\d{1,2})(?:[ T](\d{1,2}):(\d{2})(?::(\d{2}))?)?/.exec(text);

  if (isoDate) {
    const [, year, month, day, hour = "0", minute = "0", second = "0"] = isoDate;
    return buildUtcDate(Number(year), Number(month), Number(day), Number(hour), Number(minute), Number(second));
  }

  const parsed = new Date(text);
  return Number.isNaN(parsed.getTime()) ? undefined : parsed;
}

function buildUtcDate(year: number, month: number, day: number, hour: number, minute: number, second: number) {
  const parsed = new Date(Date.UTC(year, month - 1, day, hour, minute, second));

  if (
    parsed.getUTCFullYear() !== year ||
    parsed.getUTCMonth() !== month - 1 ||
    parsed.getUTCDate() !== day ||
    parsed.getUTCHours() !== hour ||
    parsed.getUTCMinutes() !== minute ||
    parsed.getUTCSeconds() !== second
  ) {
    return undefined;
  }

  return parsed;
}

function isSameDate(left: Date, right: Date) {
  return left.toISOString().slice(0, 10) === right.toISOString().slice(0, 10);
}

function normalizeText(value: string) {
  return value
    .normalize("NFD")
    .replace(/\p{Diacritic}/gu, "")
    .toLowerCase()
    .trim();
}

export async function reconcileRetroactiveEntriesForOrder(farmId: string) {
  // Yield immediately to prevent blocking the caller
  await new Promise(resolve => setTimeout(resolve, 0));

  const orphanedEntries = findOrphanedCaneEntriesByFarm(farmId);
  if (orphanedEntries.length === 0) return;

  const affectedBatchIds = new Set<string>();
  const updatesToPerform: { id: string, fieldId: string, activeOrderId: string, batchId: string }[] = [];

  const allFarms = listFarms();
  const farm = allFarms.find(f => f.id === farmId);
  if (!farm) return;

  const allOrders = listOrders();
  const orderForFieldCache = new Map<string, HarvestOrderRecord | null>();

  function normalizeFieldCodeLocal(value: string) {
    return value.replace(/^0+/, "").trim();
  }

  function getOrderForFieldLocal(fieldId: string, entryDate: string | null) {
    const cacheKey = `${fieldId}::${entryDate ?? "sem-data"}`;
    if (orderForFieldCache.has(cacheKey)) return orderForFieldCache.get(cacheKey);

    const order = findOrderForFieldByEntryDate(allOrders, farmId, fieldId, entryDate);
    orderForFieldCache.set(cacheKey, order);
    return order;
  }

  for (let i = 0; i < orphanedEntries.length; i++) {
    const entry = orphanedEntries[i];
    if (i % 50 === 0) {
      await new Promise(resolve => setTimeout(resolve, 0));
    }

    if (!entry.field_code_raw) continue;

    const normalizedCode = normalizeFieldCodeLocal(entry.field_code_raw);
    const field = farm.fields.find((f) => normalizeFieldCodeLocal(f.code) === normalizedCode);
    if (!field) continue;

    const activeOrder = getOrderForFieldLocal(field.id, entry.entry_date);
    if (activeOrder) {
      updatesToPerform.push({
        id: entry.id,
        fieldId: field.id,
        activeOrderId: activeOrder.id,
        batchId: entry.batch_id
      });
    }
  }

  if (updatesToPerform.length > 0) {
    const performReconciliation = db.transaction(() => {
      const updatesParam = updatesToPerform.map(u => ({
        id: u.id,
        status: 'OK',
        notes: null,
        fieldId: u.fieldId,
        orderId: u.activeOrderId
      }));
      updateCaneEntryReconciliations(updatesParam);
      for (const update of updatesToPerform) {
        affectedBatchIds.add(update.batchId);
      }
    });
    performReconciliation();

    for (const batchId of affectedBatchIds) {
      await new Promise(resolve => setTimeout(resolve, 0));
      recalculateImportBatchCounts(batchId);
    }
  }
}

type ReconciliationJobPayload = { requestedAt: string };
const reconciliationWorkerId = `reconcile-orphans:${process.pid}:${randomUUID()}`;
let globalReconciliationWorkerActive = false;
let globalReconciliationRetryTimer: NodeJS.Timeout | null = null;

export function reconcileGlobalOrphansAsync() {
  const job = enqueueBackgroundJob<ReconciliationJobPayload>({
    kind: "RECONCILE_ORPHANS",
    dedupeKey: "global",
    payload: { requestedAt: new Date().toISOString() },
    maxAttempts: 6
  });
  startGlobalReconciliationWorker();
  return Promise.resolve(job);
}

async function runGlobalReconciliationQueue() {
  try {
    while (true) {
      const job = claimNextBackgroundJob<ReconciliationJobPayload>({
        kind: "RECONCILE_ORPHANS",
        workerId: reconciliationWorkerId,
        leaseMs: 15 * 60_000
      });

      if (!job) {
        break;
      }

    await new Promise((resolve) => setTimeout(resolve, 0));
    try {
      await performGlobalReconciliationPass();
      completeBackgroundJob(job.id, reconciliationWorkerId);
    } catch (err) {
      const failed = failBackgroundJob(job, reconciliationWorkerId, err);
      console.error("Erro na reconciliacao global de orfaos:", err);
      scheduleGlobalReconciliationRetry(failed?.availableAt);
    }
    }
  } finally {
    globalReconciliationWorkerActive = false;
    if (!globalReconciliationRetryTimer) {
      scheduleGlobalReconciliationRetry();
    }
  }
}

async function performGlobalReconciliationPass() {
      // 1. Resolve FARM_NOT_FOUND
      const orphans = db.prepare(`
        SELECT id, farm_name_raw, farm_code_raw
        FROM cane_entries
        WHERE status = 'FARM_NOT_FOUND'
      `).all() as { id: string, farm_name_raw: string | null, farm_code_raw: string | null }[];

      const farmIdsToReconcile = new Set<string>();

      // Localiza atualizacoes antes da transacao para reduzir o tempo do bloqueio de escrita.
      const updatesToPerform: { orphanId: string, farmId: string }[] = [];
      for (let i = 0; i < orphans.length; i++) {
        const orphan = orphans[i];
        if (orphan.farm_name_raw) {
          const farm = findFarmByRaw(orphan.farm_name_raw, orphan.farm_code_raw ?? undefined);
          if (farm) {
            updatesToPerform.push({ orphanId: orphan.id, farmId: farm.id });
          }
        }

        // Yield to event loop every 100 iterations to avoid blocking Node.js
        if (i % 100 === 0) {
          await new Promise(resolve => setTimeout(resolve, 0));
        }
      }

      const performFarmUpdate = db.transaction(() => {
        const stmt = db.prepare(`
          UPDATE cane_entries
          SET farm_id = ?, status = 'FIELD_NOT_RELEASED'
          WHERE id = ?
        `);
        const paramsList = updatesToPerform.map(update => [update.farmId, update.orphanId]);
        if (paramsList.length > 0) stmt.runMany(paramsList);
        for (const update of updatesToPerform) {
          farmIdsToReconcile.add(update.farmId);
        }
      });

      performFarmUpdate();

      // 2. Also ensure all newly modified farms get their FIELD_NOT_FOUND and FIELD_NOT_RELEASED checked
      // But actually, we should just run reconcileRetroactiveEntriesForOrder for ALL closed/active farms that might have orphans?
      // Since a new Field could have been added, we should query all farms that currently have 'FIELD_NOT_RELEASED' or 'FIELD_NOT_FOUND'.
      const orphanFarms = db.prepare(`
        SELECT DISTINCT farm_id
        FROM cane_entries
        WHERE status IN ('FIELD_NOT_RELEASED', 'FIELD_NOT_FOUND') AND farm_id IS NOT NULL
      `).all() as { farm_id: string }[];

      for (const row of orphanFarms) {
        farmIdsToReconcile.add(row.farm_id);
      }

      for (const farmId of farmIdsToReconcile) {
        await reconcileRetroactiveEntriesForOrder(farmId);
      }
}

function startGlobalReconciliationWorker() {
  if (globalReconciliationWorkerActive) {
    return;
  }
  if (globalReconciliationRetryTimer) {
    clearTimeout(globalReconciliationRetryTimer);
    globalReconciliationRetryTimer = null;
  }
  globalReconciliationWorkerActive = true;
  void runGlobalReconciliationQueue();
}

function scheduleGlobalReconciliationRetry(availableAt?: string) {
  const delayMs = availableAt
    ? Math.max(1_000, Math.min(60_000, Date.parse(availableAt) - Date.now()))
    : 60_000;
  if (globalReconciliationRetryTimer) {
    clearTimeout(globalReconciliationRetryTimer);
  }
  globalReconciliationRetryTimer = setTimeout(startGlobalReconciliationWorker, delayMs);
  globalReconciliationRetryTimer.unref();
}

setTimeout(startGlobalReconciliationWorker, 0).unref();
