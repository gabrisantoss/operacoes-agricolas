import path from "node:path";
import ExcelJS from "exceljs";
import PDFDocument from "pdfkit";
import type { FleetEquipmentType, FleetMovementStatus, FleetMovementType } from "@balanca/shared";
import { systemIdentity } from "@balanca/shared";
import { badRequest } from "../errors.js";
import { assertExportRowLimit } from "./exportControl.js";

type FleetStatus = "VERDE" | "VERMELHO" | "AZUL" | "";
type EquipmentType = "COLHEDORA" | "TRANSBORDO" | "CARREGADEIRA" | "VIVENCIA" | "CAMINHAO D'AGUA" | "FURGAO";
type FleetItemSource = "BASE" | "MOVEMENT";

type EquipmentDefinition = {
  type: EquipmentType;
  column: number;
  label: string;
  shortLabel: string;
};

type FleetItem = {
  type: EquipmentType;
  label: string;
  value: string;
  status: FleetStatus;
  source: FleetItemSource;
  movementId?: string;
  note?: string;
  coveredBy?: string;
  loanedToFrontName?: string;
  blankDisplay?: boolean;
};

type FleetRowCell = {
  type: EquipmentType;
  label: string;
  value: string;
  status: FleetStatus;
  source: FleetItemSource;
  movementId?: string;
  note?: string;
  coveredBy?: string;
  loanedToFrontName?: string;
  blankDisplay?: boolean;
};

type FleetFront = {
  name: string;
  rows: FleetRowCell[][];
  items: FleetItem[];
};

type BusRecord = {
  fleet: string;
  reason: string;
};

type ParsedFleetReport = {
  sourceName: string;
  generatedAt: Date;
  fronts: FleetFront[];
  buses: BusRecord[];
  appliedMovements: AppliedFleetMovement[];
  substitutions: FleetSubstitution[];
  movementWarnings: string[];
};

type CountSummary = {
  total: number;
  operating: number;
  moved: number;
  outOfOperation: number;
  efficiency: number;
};

export type FleetReportPreview = {
  fileName: string;
  generatedAt: string;
  frontCount: number;
  busCount: number;
  productive: CountSummary;
  support: CountSummary;
  supportByType: Array<CountSummary & { type: EquipmentType; label: string }>;
  fronts: Array<{
    name: string;
    productive: CountSummary & {
      harvesters: string;
      transbordos: string;
    };
    support: CountSummary;
  }>;
  equipment: Array<{
    code: string;
    type: EquipmentType;
    typeLabel: string;
    frontName: string;
    frontNumber: number | null;
    status: FleetStatus;
    statusLabel: string;
    source: FleetItemSource;
    movementId?: string;
    note?: string;
    coveredBy?: string;
    loanedToFrontName?: string;
  }>;
  substitutions: FleetSubstitution[];
  movementSummary: {
    applied: number;
    warnings: string[];
  };
  observations: string[];
};

export type FleetReportMovement = {
  id: string;
  movementType: FleetMovementType;
  equipmentCode: string;
  equipmentType: FleetEquipmentType;
  frontNumber?: number | null;
  reserveCode?: string | null;
  replacesCode?: string | null;
  reason?: string | null;
  status: FleetMovementStatus;
  occurredAt: string;
  createdAt?: string;
};

type AppliedFleetMovement = {
  id: string;
  label: string;
  equipmentCode: string;
  frontName?: string;
  effect: string;
  replacesCode?: string | null;
  occurredAt: string;
  reason?: string | null;
};

type FleetSubstitution = {
  movementId: string;
  frontName: string;
  frontNumber: number | null;
  replacedCode: string;
  replacementCode: string;
  equipmentType: EquipmentType;
  typeLabel: string;
  sourceFrontName?: string;
  occurredAt: string;
  reason?: string | null;
};

const equipmentDefinitions: EquipmentDefinition[] = [
  { type: "COLHEDORA", column: 1, label: "COLHEDORA", shortLabel: "COLHEDORA" },
  { type: "TRANSBORDO", column: 2, label: "TRANSBORDO", shortLabel: "TRANSBORDO" },
  { type: "CARREGADEIRA", column: 3, label: "CARREGADEIRA", shortLabel: "CARREG." },
  { type: "VIVENCIA", column: 4, label: "VIVÊNCIA", shortLabel: "VIV." },
  { type: "CAMINHAO D'AGUA", column: 5, label: "CAMINHÃO D'ÁGUA", shortLabel: "CAM. ÁGUA" },
  { type: "FURGAO", column: 6, label: "FURGÃO", shortLabel: "FURG." }
];

const productiveTypes = new Set<EquipmentType>(["COLHEDORA", "TRANSBORDO"]);
const supportTypes = new Set<EquipmentType>(["CARREGADEIRA", "VIVENCIA", "CAMINHAO D'AGUA", "FURGAO"]);
const supportDefinitions = equipmentDefinitions.filter((item) => supportTypes.has(item.type));
const officialMissingFleetObservations: Array<{
  code: string;
  type: EquipmentType;
  frontNumber: number;
  expectedStatus: FleetStatus;
}> = [
];
const blankOfficialSlots: Array<{
  code: string;
  type: EquipmentType;
  frontNumber: number;
  note: string;
}> = [];

const colors = {
  darkBlue: "#1F4E78",
  textBlue: "#173A5E",
  muted: "#60748C",
  grid: "#B7CCE1",
  header: "#DDEBF7",
  lightBlue: "#EAF3FA",
  rowAlt: "#F8FBFE",
  green: "#81D41A",
  greenLight: "#E2F0D9",
  red: "#FF0000",
  redLight: "#FCE4E4",
  movement: "#1D55A6",
  movementLight: "#DCEBFF",
  white: "#FFFFFF",
  black: "#102033",
  success: "#2E7D32",
  danger: "#B71C1C",
  blueAccent: "#1D55A6"
};

const page = {
  width: 841.89,
  height: 595.28,
  marginX: 30
};

export async function previewFleetReport(
  filePath: string,
  fileName: string,
  movements: FleetReportMovement[] = []
): Promise<FleetReportPreview> {
  const report = await parseFleetWorkbook(filePath, fileName);
  applyFleetMovements(report, movements);
  applyBlankOfficialSlots(report);
  return toPreview(report);
}

export async function generateFleetReportPdf(filePath: string, fileName: string, movements: FleetReportMovement[] = []) {
  const report = await parseFleetWorkbook(filePath, fileName);
  applyFleetMovements(report, movements);
  applyBlankOfficialSlots(report);
  return renderFleetReportPdf(report);
}

async function parseFleetWorkbook(filePath: string, fileName: string): Promise<ParsedFleetReport> {
  if (path.extname(fileName).toLowerCase() !== ".xlsx") {
    throw badRequest("Envie a planilha de frotas em formato .xlsx.");
  }

  const workbook = new ExcelJS.Workbook();
  await workbook.xlsx.readFile(filePath);

  const worksheet = findFleetWorksheet(workbook);

  if (!worksheet) {
    throw badRequest("Planilha de frotas nao encontrada no arquivo enviado.");
  }
  assertExportRowLimit(worksheet.actualRowCount);

  const fronts: FleetFront[] = [];
  const buses: BusRecord[] = [];
  const seenBuses = new Set<string>();
  let currentFront: FleetFront | null = null;
  let readingBuses = false;

  worksheet.eachRow({ includeEmpty: true }, (row) => {
    const first = cleanCellValue(row.getCell(1).value);
    const firstUpper = first.toUpperCase();

    if (firstUpper.startsWith("ONIBUS DE LINHA") || firstUpper.startsWith("ÔNIBUS DE LINHA")) {
      readingBuses = true;
      currentFront = null;
      return;
    }

    if (readingBuses) {
      if (!first || firstUpper === "FROTA") {
        return;
      }

      const reason = cleanCellValue(row.getCell(2).value);

      if (!reason) {
        return;
      }

      const key = `${first}|${reason}`;

      if (!seenBuses.has(key)) {
        seenBuses.add(key);
        buses.push({ fleet: first, reason });
      }

      return;
    }

    if (firstUpper.startsWith("FRENTE ")) {
      currentFront = { name: firstUpper, rows: [], items: [] };
      fronts.push(currentFront);
      return;
    }

    if (!currentFront || isEquipmentHeaderRow(row)) {
      return;
    }

    const targetFront = currentFront;
    const rowCells = equipmentDefinitions.map((definition) => {
      const valueCell = row.getCell(definition.column);
      const value = cleanCellValue(valueCell.value);
      const status = statusFromCell(valueCell);
      const cell: FleetRowCell = {
        type: definition.type,
        label: definition.label,
        value,
        status,
        source: "BASE"
      };

      if (value) {
        targetFront.items.push(cell);
      }

      return cell;
    });

    if (rowCells.some((cell) => cell.value)) {
      currentFront.rows.push(rowCells);
    }
  });

  fronts.sort((a, b) => frontSortKey(a.name) - frontSortKey(b.name));

  if (fronts.length === 0) {
    throw badRequest("Nao encontrei frentes na planilha enviada.");
  }

  return {
    sourceName: path.basename(fileName),
    generatedAt: new Date(),
    fronts,
    buses,
    appliedMovements: [],
    substitutions: [],
    movementWarnings: []
  };
}

function findFleetWorksheet(workbook: ExcelJS.Workbook) {
  return workbook.worksheets.find((worksheet) => {
    let hasFleetPanel = false;
    let hasFront = false;

    worksheet.eachRow({ includeEmpty: false }, (row) => {
      const first = cleanCellValue(row.getCell(1).value).toUpperCase();

      if (first.includes("PAINEL DE CONTROLE DE FROTAS")) {
        hasFleetPanel = true;
      }

      if (first.startsWith("FRENTE ")) {
        hasFront = true;
      }
    });

    return hasFleetPanel || hasFront;
  });
}

function cleanCellValue(value: ExcelJS.CellValue) {
  if (value === null || value === undefined) {
    return "";
  }

  if (value instanceof Date) {
    return value.toLocaleDateString("pt-BR");
  }

  if (typeof value === "object") {
    if ("text" in value && typeof value.text === "string") {
      return value.text.trim();
    }

    if ("result" in value) {
      return cleanCellValue(value.result as ExcelJS.CellValue);
    }

    if ("richText" in value && Array.isArray(value.richText)) {
      return value.richText.map((part) => part.text).join("").trim();
    }
  }

  return String(value).trim();
}

function statusFromCell(cell: ExcelJS.Cell): FleetStatus {
  const fill = cell.fill;

  if (fill?.type === "pattern") {
    const argb = fill.fgColor?.argb?.toUpperCase();
    const bgArgb = fill.bgColor?.argb?.toUpperCase();
    const color = argb || bgArgb || "";

    if (
      color.endsWith("81D41A") ||
      color.endsWith("92D050") ||
      color.endsWith("00FF00") ||
      color.endsWith("C6E0B4") ||
      color.endsWith("E2F0D9")
    ) {
      return "VERDE";
    }

    if (color.endsWith("FF0000") || color.endsWith("F4CCCC") || color.endsWith("FCE4E4")) {
      return "VERMELHO";
    }
  }

  return "";
}

function isEquipmentHeaderRow(row: ExcelJS.Row) {
  const first = cleanCellValue(row.getCell(1).value).toUpperCase();
  const second = cleanCellValue(row.getCell(2).value).toUpperCase();
  return first === "COLHEDORA" || second === "TRANSBORDO";
}

function frontSortKey(name: string) {
  const match = /(\d+)$/.exec(name);
  return match ? Number(match[1]) : 999;
}

function applyFleetMovements(report: ParsedFleetReport, movements: FleetReportMovement[]) {
  const activeMovements = movements
    .filter((movement) => movement.status === "OPEN")
    .sort((left, right) => movementDateValue(left) - movementDateValue(right));

  for (const movement of activeMovements) {
    applyFleetMovement(report, movement);
  }
}

function applyBlankOfficialSlots(report: ParsedFleetReport) {
  for (const blankSlot of blankOfficialSlots) {
    const match = findFleetItem(report, blankSlot.code);
    const expectedFront = `FRENTE ${blankSlot.frontNumber}`;

    if (!match || match.front.name !== expectedFront || match.item.type !== blankSlot.type || match.item.coveredBy) {
      continue;
    }

    match.item.status = "VERMELHO";
    match.item.note = blankSlot.note;
    match.item.blankDisplay = true;
  }
}

function applyFleetMovement(report: ParsedFleetReport, movement: FleetReportMovement) {
  const targetFront = movement.frontNumber ? findFrontByNumber(report, movement.frontNumber) : null;
  const reportType = movementEquipmentTypeToReport(movement.equipmentType);

  if (movement.frontNumber && !targetFront) {
    report.movementWarnings.push(`Frente ${movement.frontNumber} nao encontrada para a frota ${movement.equipmentCode}.`);
  }

  if (movement.movementType === "RESERVE_ACTIVATED") {
    if (movement.replacesCode) {
      applyFleetCoverage(report, movement, targetFront, reportType);
      return;
    }

    const reserveCode = movement.reserveCode || movement.equipmentCode;
    const applied = setFleetStatus(report, movement, reserveCode, "VERDE", "reserva usado", targetFront, reportType);

    report.appliedMovements.push({
      id: movement.id,
      label: "Reserva usado",
      equipmentCode: reserveCode,
      frontName: applied?.front.name ?? targetFront?.name,
      effect: movement.replacesCode ? `entrou no lugar da frota ${movement.replacesCode}` : "entrou sem substituicao",
      replacesCode: movement.replacesCode,
      occurredAt: movement.occurredAt,
      reason: movement.reason
    });
    return;
  }

  if (movement.movementType === "RESERVE_RELEASED") {
    const reserveCode = movement.reserveCode || movement.equipmentCode;
    const applied = setFleetStatus(report, movement, reserveCode, "VERMELHO", "reserva liberado", targetFront, reportType);

    report.appliedMovements.push({
      id: movement.id,
      label: "Reserva liberado",
      equipmentCode: reserveCode,
      frontName: applied?.front.name ?? targetFront?.name,
      effect: "reserva saiu da operacao",
      occurredAt: movement.occurredAt,
      reason: movement.reason
    });
    return;
  }

  if (movement.movementType === "LEFT_MILL") {
    const applied = setFleetStatus(report, movement, movement.equipmentCode, "VERDE", "saiu da operacao", targetFront, reportType);

    report.appliedMovements.push({
      id: movement.id,
      label: "Saiu da operacao",
      equipmentCode: movement.equipmentCode,
      frontName: applied?.front.name ?? targetFront?.name,
      effect: "ficou verde no relatorio",
      occurredAt: movement.occurredAt,
      reason: movement.reason
    });
    return;
  }

  const applied = setFleetStatus(report, movement, movement.equipmentCode, "VERMELHO", "voltou para operacao", targetFront, reportType);

  report.appliedMovements.push({
    id: movement.id,
    label: "Voltou para operacao",
    equipmentCode: movement.equipmentCode,
    frontName: applied?.front.name ?? targetFront?.name,
    effect: "ficou vermelho no relatorio",
    occurredAt: movement.occurredAt,
    reason: movement.reason
  });
}

function applyFleetCoverage(
  report: ParsedFleetReport,
  movement: FleetReportMovement,
  targetFront: FleetFront | null,
  reportType: EquipmentType | null
) {
  const replacedCode = movement.replacesCode?.trim();
  const replacementCode = (movement.reserveCode || movement.equipmentCode).trim();

  if (!replacedCode) {
    return;
  }

  const replaced = findFleetItem(report, replacedCode);

  if (!replaced) {
    report.movementWarnings.push(`Frota substituida ${replacedCode} nao encontrada na base de frotas.`);
    const applied = setFleetStatus(report, movement, replacementCode, "VERDE", "reserva usado sem vaga oficial", targetFront, reportType);

    report.appliedMovements.push({
      id: movement.id,
      label: "Reserva usado",
      equipmentCode: replacementCode,
      frontName: applied?.front.name ?? targetFront?.name,
      effect: `entrou, mas a frota substituida ${replacedCode} nao foi localizada`,
      replacesCode: replacedCode,
      occurredAt: movement.occurredAt,
      reason: movement.reason
    });
    return;
  }

  if (targetFront && replaced.front.name !== targetFront.name) {
    report.movementWarnings.push(
      `Frota substituida ${replacedCode} esta na ${replaced.front.name}, mas o lancamento informou ${targetFront.name}.`
    );
  }

  const effectiveFront = replaced.front;
  const replacementOriginal = findFleetItem(report, replacementCode);
  const sourceFrontName =
    replacementOriginal && replacementOriginal.front.name !== effectiveFront.name ? replacementOriginal.front.name : undefined;

  replaced.item.status = "VERDE";
  replaced.item.movementId = movement.id;
  replaced.item.note = `coberto por ${replacementCode}`;
  replaced.item.coveredBy = replacementCode;

  if (replacementOriginal && replacementOriginal.item !== replaced.item && replacementOriginal.front.name !== effectiveFront.name) {
    replacementOriginal.item.status = "AZUL";
    replacementOriginal.item.movementId = movement.id;
    replacementOriginal.item.note = `mudança para ${effectiveFront.name}`;
    replacementOriginal.item.loanedToFrontName = effectiveFront.name;
  }

  report.substitutions.push({
    movementId: movement.id,
    frontName: effectiveFront.name,
    frontNumber: frontSortKey(effectiveFront.name) === 999 ? null : frontSortKey(effectiveFront.name),
    replacedCode,
    replacementCode,
    equipmentType: reportType ?? replaced.item.type,
    typeLabel: equipmentDefinitions.find((definition) => definition.type === (reportType ?? replaced.item.type))?.label ?? replaced.item.label,
    sourceFrontName,
    occurredAt: movement.occurredAt,
    reason: movement.reason
  });

  report.appliedMovements.push({
    id: movement.id,
    label: "Reserva usado",
    equipmentCode: replacementCode,
    frontName: effectiveFront.name,
    effect: `cobriu a vaga da frota ${replacedCode}`,
    replacesCode: replacedCode,
    occurredAt: movement.occurredAt,
    reason: movement.reason
  });
}

function setFleetStatus(
  report: ParsedFleetReport,
  movement: FleetReportMovement,
  code: string,
  status: FleetStatus,
  note: string,
  targetFront: FleetFront | null = null,
  fallbackType: EquipmentType | null = null
) {
  const match = findFleetItem(report, code);

  if (match) {
    if (targetFront && match.front.name !== targetFront.name) {
      report.movementWarnings.push(
        `Frota ${code} esta na ${match.front.name}, mas o lancamento informou ${targetFront.name}.`
      );
    }

    match.item.status = status;
    match.item.source = match.item.source === "MOVEMENT" ? "MOVEMENT" : "BASE";
    match.item.movementId = movement.id;
    match.item.note = note;
    return match;
  }

  if (!targetFront || !fallbackType) {
    report.movementWarnings.push(`Frota ${code} nao encontrada na base de frotas.`);
    return null;
  }

  const inserted = addMovementFleetItem(targetFront, fallbackType, code, status, movement.id, note);
  return { front: targetFront, item: inserted };
}

function addMovementFleetItem(
  front: FleetFront,
  type: EquipmentType,
  code: string,
  status: FleetStatus,
  movementId: string,
  note: string
) {
  const columnIndex = equipmentDefinitions.findIndex((definition) => definition.type === type);
  const row = front.rows.find((candidate) => !candidate[columnIndex]?.value) ?? createEmptyFleetRow(front);
  const definition = equipmentDefinitions[columnIndex];
  const item: FleetRowCell = {
    type,
    label: definition.label,
    value: code,
    status,
    source: "MOVEMENT",
    movementId,
    note
  };

  row[columnIndex] = item;
  front.items.push(item);
  return item;
}

function createEmptyFleetRow(front: FleetFront) {
  const row = equipmentDefinitions.map((definition) => ({
    type: definition.type,
    label: definition.label,
    value: "",
    status: "" as FleetStatus,
    source: "MOVEMENT" as FleetItemSource
  }));
  front.rows.push(row);
  return row;
}

function findFleetItem(report: ParsedFleetReport, code: string) {
  const normalizedCode = normalizeFleetCode(code);

  for (const front of report.fronts) {
    const item = front.items.find((candidate) => normalizeFleetCode(candidate.value) === normalizedCode);

    if (item) {
      return { front, item };
    }
  }

  return null;
}

function findFrontByNumber(report: ParsedFleetReport, frontNumber: number) {
  return report.fronts.find((front) => frontSortKey(front.name) === frontNumber) ?? null;
}

function movementEquipmentTypeToReport(type: FleetEquipmentType): EquipmentType | null {
  if (type === "CAMINHAO_DAGUA") {
    return "CAMINHAO D'AGUA";
  }

  if (type === "ONIBUS" || type === "OUTRO") {
    return null;
  }

  return type;
}

function movementDateValue(movement: FleetReportMovement) {
  const date = new Date(movement.occurredAt);
  const parsed = date.getTime();
  return Number.isNaN(parsed) ? 0 : parsed;
}

function normalizeFleetCode(value: string) {
  return value
    .normalize("NFD")
    .replace(/\p{Diacritic}/gu, "")
    .replace(/[^a-zA-Z0-9]/g, "")
    .toUpperCase();
}

function toPreview(report: ParsedFleetReport): FleetReportPreview {
  const productive = countItems(report.fronts, productiveTypes);
  const support = countItems(report.fronts, supportTypes);

  return {
    fileName: report.sourceName,
    generatedAt: formatDateTime(report.generatedAt),
    frontCount: report.fronts.length,
    busCount: report.buses.length,
    productive,
    support,
    supportByType: supportDefinitions.map((definition) => ({
      ...countItems(report.fronts, new Set([definition.type])),
      type: definition.type,
      label: definition.label
    })),
    fronts: report.fronts.map((front) => ({
      name: front.name,
      productive: {
        ...countFrontItems(front, productiveTypes),
        harvesters: fraction(front, "COLHEDORA"),
        transbordos: fraction(front, "TRANSBORDO")
      },
      support: countFrontItems(front, supportTypes)
    })),
    equipment: report.fronts.flatMap((front) =>
      front.items.map((item) => ({
        code: item.value,
        type: item.type,
        typeLabel: item.label,
        frontName: front.name,
        frontNumber: frontSortKey(front.name) === 999 ? null : frontSortKey(front.name),
        status: item.status,
        statusLabel: item.status === "VERDE" ? "Verde" : item.status === "VERMELHO" ? "Vermelho" : item.status === "AZUL" ? "Mudança de frente" : "Sem status",
        source: item.source,
        movementId: item.movementId,
        note: item.note,
        coveredBy: item.coveredBy,
        loanedToFrontName: item.loanedToFrontName
      }))
    ),
    substitutions: report.substitutions,
    movementSummary: {
      applied: report.appliedMovements.length,
      warnings: report.movementWarnings
    },
    observations: buildReportObservations(report)
  };
}

function buildReportObservations(report: ParsedFleetReport) {
  const observations: string[] = [];

  for (const expected of officialMissingFleetObservations) {
    const match = findFleetItem(report, expected.code);
    const expectedFront = `FRENTE ${expected.frontNumber}`;
    const typeLabel = equipmentDefinitions.find((definition) => definition.type === expected.type)?.label ?? expected.type;

    if (!match) {
      observations.push(
        `${expectedFront} - ${typeLabel} ${expected.code}: consta na base demonstrativa como faltando na lavoura, mas nao foi encontrada na base de frotas carregada.`
      );
      continue;
    }

    const mismatches: string[] = [];

    if (match.front.name !== expectedFront) {
      mismatches.push(`no relatorio esta na ${match.front.name}`);
    }

    if (match.item.type !== expected.type) {
      mismatches.push(`tipo no relatorio: ${match.item.label}`);
    }

    if (match.item.status !== expected.expectedStatus) {
      mismatches.push(`status no relatorio: ${statusLabel(match.item.status)}`);
    }

    if (mismatches.length > 0) {
      observations.push(`${expectedFront} - ${typeLabel} ${expected.code}: consta na base demonstrativa como faltando na lavoura; ${mismatches.join(", ")}.`);
    }
  }

  return observations;
}

function countItems(fronts: FleetFront[], types: Set<EquipmentType>): CountSummary {
  return summarize(fronts.flatMap((front) => front.items.filter((item) => types.has(item.type))));
}

function countFrontItems(front: FleetFront, types: Set<EquipmentType>): CountSummary {
  return summarize(front.items.filter((item) => types.has(item.type)));
}

function summarize(items: FleetItem[]): CountSummary {
  const total = items.length;
  const operating = items.filter((item) => item.status === "VERDE").length;
  const moved = items.filter((item) => item.status === "AZUL").length;
  const outOfOperation = items.filter((item) => item.status === "VERMELHO").length;

  return {
    total,
    operating,
    moved,
    outOfOperation,
    efficiency: total > 0 ? (operating / total) * 100 : 0
  };
}

function fraction(front: FleetFront, type: EquipmentType) {
  const items = front.items.filter((item) => item.type === type);
  const operating = items.filter((item) => item.status === "VERDE").length;
  return `${operating}/${items.length}`;
}

function renderFleetReportPdf(report: ParsedFleetReport) {
  const doc = new PDFDocument({
    size: "A4",
    layout: "landscape",
    margin: 0,
    info: {
      Title: "Relatório de Eficiência Operacional por Frente",
      Author: systemIdentity.currentName
    }
  });
  const chunks: Buffer[] = [];
  const done = new Promise<Buffer>((resolve, reject) => {
    doc.on("data", (chunk: Buffer) => chunks.push(Buffer.from(chunk)));
    doc.on("end", () => resolve(Buffer.concat(chunks)));
    doc.on("error", reject);
  });

  drawSummaryPage(doc, report, 1);

  let pageNumber = 2;
  for (let index = 0; index < report.fronts.length; index += 2) {
    doc.addPage();
    drawFrontsPage(doc, report, report.fronts.slice(index, index + 2), pageNumber);
    pageNumber += 1;
  }

  for (let index = 0; index < report.substitutions.length; index += 18) {
    doc.addPage();
    drawSubstitutionPage(doc, report, report.substitutions.slice(index, index + 18), pageNumber);
    pageNumber += 1;
  }

  if (report.buses.length > 0) {
    doc.addPage();
    drawBusPage(doc, report, pageNumber);
  }

  doc.end();
  return done;
}

function drawSummaryPage(doc: PDFKit.PDFDocument, report: ParsedFleetReport, pageNumber: number) {
  const preview = toPreview(report);
  const harvesters = countItems(report.fronts, new Set<EquipmentType>(["COLHEDORA"]));
  const transbordos = countItems(report.fronts, new Set<EquipmentType>(["TRANSBORDO"]));

  drawHeaderFooter(doc, report, pageNumber);
  drawText(doc, 36, 74, "Relatório de Eficiência Operacional por Frente", "Helvetica-Bold", 22, colors.textBlue);
  drawText(
    doc,
    36,
    104,
    `Fonte: ${report.sourceName} | Gerado em ${formatDateTime(report.generatedAt)} | Indicador calculado com a base produtiva da colheita: colhedoras e transbordos.`,
    "Helvetica",
    8,
    colors.muted,
    { width: 760 }
  );

  const gap = 8;
  const cardWidth = (page.width - 2 * page.marginX - 4 * gap) / 5;
  const cardTop = 118;
  drawCard(doc, page.marginX, cardTop, cardWidth, 70, "Base produtiva", String(preview.productive.total), `${harvesters.total} colhedoras + ${transbordos.total} transbordos`);
  drawCard(
    doc,
    page.marginX + cardWidth + gap,
    cardTop,
    cardWidth,
    70,
    "Em operação",
    String(preview.productive.operating),
    `${harvesters.operating} colhedoras + ${transbordos.operating} transbordos`,
    colors.success
  );
  drawCard(
    doc,
    page.marginX + 2 * (cardWidth + gap),
    cardTop,
    cardWidth,
    70,
    "Mudanças",
    String(preview.productive.moved),
    `${harvesters.moved} colhedoras + ${transbordos.moved} transbordos`,
    colors.movement
  );
  drawCard(
    doc,
    page.marginX + 3 * (cardWidth + gap),
    cardTop,
    cardWidth,
    70,
    "Fora de operação",
    String(preview.productive.outOfOperation),
    `${harvesters.outOfOperation} colhedoras + ${transbordos.outOfOperation} transbordos`,
    colors.danger
  );
  drawCard(
    doc,
    page.marginX + 4 * (cardWidth + gap),
    cardTop,
    cardWidth,
    70,
    "Eficiência operacional",
    formatPercent(preview.productive.efficiency),
    "em operação / base produtiva",
    colors.blueAccent
  );

  drawStatusLegend(doc, page.marginX, 200, page.width - 2 * page.marginX);
  drawText(doc, page.marginX, 238, "Eficiência por frente", "Helvetica-Bold", 13, colors.textBlue);
  drawText(doc, page.marginX, 254, "Nas colunas Colhedoras e Transbordos, a leitura é: verde / total da frente.", "Helvetica", 7.8, colors.muted);

  const rows = [
    ["FRENTE", "COLHEDORAS", "TRANSBORDOS", "BASE", "VERDE OK", "AZUL MUDANÇA", "VERMELHO ATENÇÃO", "EFICIÊNCIA"],
    ...preview.fronts.map((front) => [
      front.name,
      front.productive.harvesters,
      front.productive.transbordos,
      String(front.productive.total),
      String(front.productive.operating),
      String(front.productive.moved),
      String(front.productive.outOfOperation),
      formatPercent(front.productive.efficiency)
    ])
  ];
  const fills = rows.map((_, index) =>
    index === 0
      ? []
      : [colors.white, colors.greenLight, colors.greenLight, colors.lightBlue, colors.green, colors.movement, colors.red, colors.lightBlue]
  );
  drawTable(doc, page.marginX, 268, [84, 104, 106, 70, 88, 112, 126, 72], rows, {
    rowHeight: 15.4,
    headerHeight: 24,
    fills,
    align: ["left", "center", "center", "center", "center", "center", "center", "center"],
    boldColumns: new Set([7]),
    fontSize: 6.9
  });

  const movementNote = report.substitutions.length > 0 ? ` Coberturas/substituições: ${report.substitutions.length}.` : "";
  const note = `Total do painel: ${preview.productive.total + preview.support.total} frotas. A eficiência usa apenas colhedoras e transbordos. Verde conta como trabalhando; azul mostra mudança de frente; vermelho é atenção/oficina.${movementNote}`;
  drawWrappedText(doc, page.marginX, 518, note, page.width - 2 * page.marginX, 7.2, colors.muted);

  if (preview.observations.length > 0) {
    drawText(doc, page.marginX, 540, "Observações da base demonstrativa", "Helvetica-Bold", 7.4, colors.textBlue);
    drawWrappedText(doc, page.marginX, 552, preview.observations.map((observation) => `- ${observation}`).join("\n"), page.width - 2 * page.marginX, 6.3, colors.muted);
  }
}

function drawSupportPage(doc: PDFKit.PDFDocument, report: ParsedFleetReport, pageNumber: number) {
  const preview = toPreview(report);

  drawHeaderFooter(doc, report, pageNumber);
  drawText(doc, 36, 74, "Relatório dos Outros Implementos", "Helvetica-Bold", 22, colors.textBlue);
  drawText(
    doc,
    36,
    104,
    `Fonte: ${report.sourceName} | Gerado em ${formatDateTime(report.generatedAt)} | Implementos de apoio fora do cálculo da eficiência produtiva.`,
    "Helvetica",
    8,
    colors.muted,
    { width: 760 }
  );

  const gap = 8;
  const cardWidth = (page.width - 2 * page.marginX - 4 * gap) / 5;
  drawStatusLegend(doc, page.marginX, 122, page.width - 2 * page.marginX);

  const cardTop = 160;
  drawCard(doc, page.marginX, cardTop, cardWidth, 60, "Outros implementos", String(preview.support.total), "carregadeira, vivência, caminhão d'água e furgão");
  drawCard(doc, page.marginX + cardWidth + gap, cardTop, cardWidth, 60, "Em operação", String(preview.support.operating), "na lavoura", colors.success);
  drawCard(
    doc,
    page.marginX + 2 * (cardWidth + gap),
    cardTop,
    cardWidth,
    60,
    "Mudanças",
    String(preview.support.moved),
    "entre frentes",
    colors.movement
  );
  drawCard(
    doc,
    page.marginX + 3 * (cardWidth + gap),
    cardTop,
    cardWidth,
    60,
    "Fora de operação",
    String(preview.support.outOfOperation),
    "oficina, manutenção ou fora da lavoura",
    colors.danger
  );
  drawCard(
    doc,
    page.marginX + 4 * (cardWidth + gap),
    cardTop,
    cardWidth,
    60,
    "Disponibilidade apoio",
    formatPercent(preview.support.efficiency),
    "em operação / outros implementos",
    colors.blueAccent
  );

  drawText(doc, page.marginX, 232, "Resumo por tipo", "Helvetica-Bold", 12, colors.textBlue);
  const typeRows = [
    ["TIPO", "VERDE OK", "AZUL MUDANÇA", "VERMELHO ATENÇÃO", "TOTAL", "DISPONIBILIDADE"],
    ...preview.supportByType.map((item) => [
      item.label,
      String(item.operating),
      String(item.moved),
      String(item.outOfOperation),
      String(item.total),
      formatPercent(item.efficiency)
    ])
  ];
  const typeFills = typeRows.map((_, index) => (index === 0 ? [] : [colors.white, colors.green, colors.movement, colors.red, colors.lightBlue, colors.lightBlue]));
  drawTable(doc, page.marginX, 258, [160, 105, 125, 145, 92, 155], typeRows, {
    rowHeight: 20,
    headerHeight: 20,
    fills: typeFills,
    align: ["left", "center", "center", "center", "center", "center"],
    boldColumns: new Set([5]),
    fontSize: 7.1
  });

  drawText(doc, page.marginX, 370, "Status por frente", "Helvetica-Bold", 12, colors.textBlue);
  drawText(doc, page.marginX + 100, 379, "As células coloridas mostram a frota e a situação de cada implemento.", "Helvetica", 7.3, colors.muted);
  drawSmallSupportTable(doc, report.fronts.slice(0, 7), page.marginX, 402);
  drawSmallSupportTable(doc, report.fronts.slice(7), page.marginX + 402, 402);
}

function drawSmallSupportTable(doc: PDFKit.PDFDocument, fronts: FleetFront[], x: number, y: number) {
  const rows = [["FRENTE", "CARREG.", "VIV.", "CAM. ÁGUA", "FURG.", "VERDE", "AZUL", "VERM."]];
  const fills: string[][] = [[]];
  const splitCells = new Map<string, SplitTableCell>();

  for (const [frontIndex, front] of fronts.entries()) {
    const support = supportByFront(front);
    const supportCells = [support.CARREGADEIRA, support.VIVENCIA, support["CAMINHAO D'AGUA"], support.FURGAO];
    const operating = supportDefinitions.filter((definition) => support[definition.type]?.status === "VERDE").length;
    const moved = supportDefinitions.filter((definition) => support[definition.type]?.status === "AZUL").length;
    const outOfOperation = supportDefinitions.filter((definition) => support[definition.type]?.status === "VERMELHO").length;
    rows.push([
      front.name,
      supportCells[0] ? cellDisplayValue(supportCells[0]) : "",
      supportCells[1] ? cellDisplayValue(supportCells[1]) : "",
      supportCells[2] ? cellDisplayValue(supportCells[2]) : "",
      supportCells[3] ? cellDisplayValue(supportCells[3]) : "",
      String(operating),
      String(moved),
      String(outOfOperation)
    ]);
    fills.push([
      colors.white,
      statusColor(support.CARREGADEIRA?.status),
      statusColor(support.VIVENCIA?.status),
      statusColor(support["CAMINHAO D'AGUA"]?.status),
      statusColor(support.FURGAO?.status),
      colors.green,
      colors.movement,
      colors.red
    ]);

    supportCells.forEach((cell, supportIndex) => {
      if (cell?.coveredBy) {
        splitCells.set(tableCellKey(frontIndex + 1, supportIndex + 1), {
          left: cell.value,
          right: cell.coveredBy,
          leftFill: statusColor(cell.status),
          rightFill: colors.movement
        });
      }
    });
  }

  drawTable(doc, x, y, [54, 58, 50, 72, 50, 32, 32, 36], rows, {
    rowHeight: 17,
    headerHeight: 20,
    fills,
    splitCells,
    align: ["left", "center", "center", "center", "center", "center", "center", "center"],
    boldColumns: new Set([5, 6, 7]),
    fontSize: 7
  });
}

function supportByFront(front: FleetFront) {
  const result: Partial<Record<EquipmentType, FleetItem>> = {};

  for (const item of front.items) {
    if (supportTypes.has(item.type)) {
      result[item.type] = item;
    }
  }

  return result;
}

function drawFrontsPage(doc: PDFKit.PDFDocument, report: ParsedFleetReport, fronts: FleetFront[], pageNumber: number) {
  drawHeaderFooter(doc, report, pageNumber);
  drawText(
    doc,
    page.marginX,
    76,
    "Célula dividida: esquerda = frota oficial | azul = frota que entrou na substituição.",
    "Helvetica-Bold",
    9.2,
    colors.textBlue
  );
  const firstBottom = drawFrontBlock(doc, fronts[0], page.marginX, 100, page.width - 2 * page.marginX);

  if (fronts[1]) {
    drawFrontBlock(doc, fronts[1], page.marginX, firstBottom + 22, page.width - 2 * page.marginX);
  }
}

function drawFrontBlock(doc: PDFKit.PDFDocument, front: FleetFront, x: number, y: number, width: number) {
  const summary = countFrontItems(front, productiveTypes);
  doc.rect(x, y, width, 24).fill(colors.darkBlue);
  drawText(doc, x + 8, y + 7, front.name, "Helvetica-Bold", 11, colors.white);
  drawText(
    doc,
    x + 180,
    y + 8,
    `Base produtiva: ${summary.total} | Verde: ${summary.operating} | Azul: ${summary.moved} | Vermelho: ${summary.outOfOperation} | Eficiência: ${formatPercent(summary.efficiency)}`,
    "Helvetica",
    7.8,
    colors.white,
    { width: width - 188, align: "right" }
  );

  const rows = [equipmentDefinitions.map((definition) => definition.label), ...front.rows.map((row) => row.map((cell) => cellDisplayValue(cell)))];
  const fills = [
    [],
    ...front.rows.map((row) => row.map((cell) => (cell.value ? statusColor(cell.status) : colors.white)))
  ];
  const splitCells = new Map<string, SplitTableCell>();

  front.rows.forEach((row, rowIndex) => {
    row.forEach((cell, columnIndex) => {
      if (cell.coveredBy) {
        splitCells.set(tableCellKey(rowIndex + 1, columnIndex), {
          left: cell.value,
          right: cell.coveredBy,
          leftFill: statusColor(cell.status),
          rightFill: colors.movement
        });
      }
    });
  });

  return drawTable(doc, x, y + 24, Array.from({ length: 6 }, () => width / 6), rows, {
    rowHeight: 20,
    headerHeight: 18,
    fills,
    splitCells,
    align: ["center", "center", "center", "center", "center", "center"],
    fontSize: 8
  });
}

function cellDisplayValue(cell: FleetRowCell | FleetItem) {
  return cell.blankDisplay ? "" : cell.value;
}

function drawSubstitutionPage(
  doc: PDFKit.PDFDocument,
  report: ParsedFleetReport,
  substitutions: FleetSubstitution[],
  pageNumber: number
) {
  drawHeaderFooter(doc, report, pageNumber);
  drawText(doc, 36, 74, "Coberturas e substituições", "Helvetica-Bold", 19, colors.textBlue);
  drawWrappedText(
    doc,
    36,
    103,
    "Como ler na tabela das frentes: a célula dividida mostra a frota oficial à esquerda e a frota que entrou em azul à direita.",
    page.width - 72,
    8,
    colors.muted
  );
  drawStatusLegend(doc, page.marginX, 124, page.width - 2 * page.marginX);

  const rows = [
    ["FRENTE", "TIPO", "NO RELATÓRIO", "FROTA OFICIAL", "ENTROU", "VEIO DA", "OBSERVAÇÃO"],
    ...substitutions.map((substitution) => [
      substitution.frontName,
      substitution.typeLabel,
      `${substitution.replacedCode}/${substitution.replacementCode}`,
      substitution.replacedCode,
      substitution.replacementCode,
      substitution.sourceFrontName ?? "Reserva",
      substitution.reason ?? "Substituição operacional"
    ])
  ];
  const fills = rows.map((_, index) =>
    index === 0 ? [] : [colors.white, colors.lightBlue, colors.greenLight, colors.lightBlue, colors.green, colors.movement, colors.white]
  );

  drawTable(doc, page.marginX, 162, [76, 102, 92, 92, 82, 92, 246], rows, {
    rowHeight: 20,
    headerHeight: 22,
    fills,
    align: ["left", "left", "center", "center", "center", "left", "left"],
    fontSize: 6.8
  });
}

function drawBusPage(doc: PDFKit.PDFDocument, report: ParsedFleetReport, pageNumber: number) {
  drawHeaderFooter(doc, report, pageNumber);
  drawText(doc, 36, 74, "Ônibus de linha", "Helvetica-Bold", 17, colors.textBlue);
  drawWrappedText(
    doc,
    36,
    104,
    "Relação complementar informada com frota e motivo. Estes registros não compõem o indicador de eficiência operacional.",
    page.width - 72,
    8,
    colors.muted
  );

  const rows = [["FROTA", "MOTIVO"], ...report.buses.map((bus) => [bus.fleet, bus.reason])];
  const fills = rows.map((_, index) => (index === 0 ? [] : [colors.lightBlue, colors.white]));
  const tableWidth = 640;
  drawTable(doc, (page.width - tableWidth) / 2, 175, [130, 510], rows, {
    rowHeight: 28,
    headerHeight: 24,
    fills,
    align: ["center", "left"],
    fontSize: 8
  });
}

function drawHeaderFooter(doc: PDFKit.PDFDocument, report: ParsedFleetReport, pageNumber: number) {
  drawText(doc, page.marginX, 21, "Controle Operacional de Frotas", "Helvetica-Bold", 8.5, colors.textBlue);
  drawText(doc, page.width - page.marginX - 120, 21, report.sourceName, "Helvetica", 7.5, colors.muted, {
    width: 120,
    align: "right"
  });
  doc
    .moveTo(page.marginX, page.height - 28)
    .lineTo(page.width - page.marginX, page.height - 28)
    .lineWidth(0.45)
    .strokeColor(colors.grid)
    .stroke();
  drawText(
    doc,
    page.marginX,
    page.height - 19,
    `Gerado em ${formatDateTime(report.generatedAt)} | Verde: em operação/coberto | Azul: mudança de frente | Vermelho: oficina, manutenção ou fora da lavoura`,
    "Helvetica",
    7.2,
    colors.muted,
    { width: 600 }
  );
  drawText(doc, page.width - page.marginX - 90, page.height - 19, `Página ${pageNumber}`, "Helvetica", 7.2, colors.muted, {
    width: 90,
    align: "right"
  });
}

function drawStatusLegend(doc: PDFKit.PDFDocument, x: number, y: number, width: number) {
  const gap = 8;
  const itemWidth = (width - 2 * gap) / 3;
  const items = [
    { color: colors.green, title: "VERDE", description: "OK / trabalhando" },
    { color: colors.movement, title: "AZUL", description: "mudança de frente" },
    { color: colors.red, title: "VERMELHO", description: "atenção / oficina" }
  ];

  items.forEach((item, index) => {
    const itemX = x + index * (itemWidth + gap);
    doc.rect(itemX, y, itemWidth, 26).fillAndStroke(colors.white, colors.grid);
    doc.rect(itemX, y, 68, 26).fill(item.color);
    drawText(doc, itemX, y + 8, item.title, "Helvetica-Bold", 8.4, colors.white, { width: 68, align: "center" });
    drawText(doc, itemX + 76, y + 8, item.description, "Helvetica-Bold", 8.1, colors.black, {
      width: itemWidth - 84,
      align: "left"
    });
  });
}

function drawCard(
  doc: PDFKit.PDFDocument,
  x: number,
  y: number,
  width: number,
  height: number,
  title: string,
  value: string,
  subtitle: string,
  valueColor = colors.textBlue
) {
  doc.rect(x, y, width, height).fillAndStroke(colors.white, colors.grid);
  drawText(doc, x, y + 16, title.toUpperCase(), "Helvetica-Bold", 7, colors.muted, { width, align: "center" });
  drawText(doc, x, y + (height >= 70 ? 31 : 26), value, "Helvetica-Bold", 18, valueColor, { width, align: "center" });
  drawText(doc, x + 4, y + height - 12, subtitle, "Helvetica", 6.8, colors.muted, { width: width - 8, align: "center" });
}

type SplitTableCell = {
  left: string;
  right: string;
  leftFill: string;
  rightFill: string;
};

function drawTable(
  doc: PDFKit.PDFDocument,
  x: number,
  y: number,
  widths: number[],
  rows: string[][],
  options: {
    rowHeight: number;
    headerHeight?: number;
    fills?: string[][];
    splitCells?: Map<string, SplitTableCell>;
    align?: Array<"left" | "center" | "right">;
    boldColumns?: Set<number>;
    fontSize?: number;
  }
) {
  const headerHeight = options.headerHeight ?? options.rowHeight;
  const align = options.align ?? widths.map(() => "center" as const);
  const boldColumns = options.boldColumns ?? new Set<number>();
  const fontSize = options.fontSize ?? 7.5;
  let cursorY = y;

  rows.forEach((row, rowIndex) => {
    const height = rowIndex === 0 ? headerHeight : options.rowHeight;
    let cursorX = x;

    row.forEach((cell, columnIndex) => {
      const fill = rowIndex === 0 ? colors.header : options.fills?.[rowIndex]?.[columnIndex] ?? (rowIndex % 2 === 0 ? colors.rowAlt : colors.white);
      const splitCell = rowIndex === 0 ? undefined : options.splitCells?.get(tableCellKey(rowIndex, columnIndex));

      if (splitCell) {
        drawSplitTableCell(doc, cursorX, cursorY, widths[columnIndex], height, splitCell, fontSize);
        cursorX += widths[columnIndex];
        return;
      }

      doc.rect(cursorX, cursorY, widths[columnIndex], height).fillAndStroke(fill, colors.grid);

      const isStrongStatusFill = isStrongFill(fill);
      const font = rowIndex === 0 || boldColumns.has(columnIndex) || isStrongStatusFill ? "Helvetica-Bold" : "Helvetica";
      const textColor = rowIndex === 0 ? colors.textBlue : isStrongStatusFill ? colors.white : colors.black;
      const size = rowIndex === 0 ? Math.max(fontSize - 0.1, 6) : fontSize;
      const text = fitText(doc, cell, font, size, widths[columnIndex] - 8);
      drawText(doc, cursorX + 4, cursorY + (height - size) / 2 - 1, text, font, size, textColor, {
        width: widths[columnIndex] - 8,
        align: align[columnIndex]
      });
      cursorX += widths[columnIndex];
    });

    cursorY += height;
  });

  return cursorY;
}

function drawSplitTableCell(
  doc: PDFKit.PDFDocument,
  x: number,
  y: number,
  width: number,
  height: number,
  cell: SplitTableCell,
  fontSize: number
) {
  const leftWidth = Math.floor(width / 2);
  const rightWidth = width - leftWidth;

  drawTableCellSegment(doc, x, y, leftWidth, height, cell.left, cell.leftFill, fontSize);
  drawTableCellSegment(doc, x + leftWidth, y, rightWidth, height, cell.right, cell.rightFill, fontSize);
  doc.rect(x, y, width, height).lineWidth(1.15).strokeColor(colors.black).stroke();
  doc.moveTo(x + leftWidth, y).lineTo(x + leftWidth, y + height).lineWidth(1.15).strokeColor(colors.black).stroke();
  doc.lineWidth(0.45).strokeColor(colors.grid);
}

function drawTableCellSegment(
  doc: PDFKit.PDFDocument,
  x: number,
  y: number,
  width: number,
  height: number,
  value: string,
  fill: string,
  fontSize: number
) {
  const size = Math.min(fontSize, width < 34 ? 6.2 : fontSize);
  const font = "Helvetica-Bold";
  const text = fitText(doc, value, font, size, width - 4);
  doc.rect(x, y, width, height).fillAndStroke(fill, colors.grid);
  drawText(doc, x + 2, y + (height - size) / 2 - 1, text, font, size, isStrongFill(fill) ? colors.white : colors.black, {
    width: width - 4,
    align: "center"
  });
}

function tableCellKey(rowIndex: number, columnIndex: number) {
  return `${rowIndex}:${columnIndex}`;
}

function isStrongFill(fill: string) {
  return fill === colors.green || fill === colors.red || fill === colors.movement;
}

function drawText(
  doc: PDFKit.PDFDocument,
  x: number,
  y: number,
  text: string,
  font: string,
  size: number,
  color: string,
  options: { width?: number; align?: "left" | "center" | "right" } = {}
) {
  doc.font(font).fontSize(size).fillColor(color).text(text, x, y, {
    width: options.width,
    align: options.align,
    lineBreak: false
  });
}

function drawWrappedText(doc: PDFKit.PDFDocument, x: number, y: number, text: string, width: number, size: number, color: string) {
  doc.font("Helvetica").fontSize(size).fillColor(color).text(text, x, y, {
    width,
    align: "left"
  });
}

function fitText(doc: PDFKit.PDFDocument, text: string, font: string, size: number, width: number) {
  const value = text || "";
  doc.font(font).fontSize(size);

  if (doc.widthOfString(value) <= width) {
    return value;
  }

  let trimmed = value;

  while (trimmed.length > 0 && doc.widthOfString(`${trimmed}...`) > width) {
    trimmed = trimmed.slice(0, -1);
  }

  return trimmed ? `${trimmed}...` : "";
}

function statusColor(status: FleetStatus | undefined) {
  if (status === "VERDE") {
    return colors.green;
  }

  if (status === "VERMELHO") {
    return colors.red;
  }

  if (status === "AZUL") {
    return colors.movement;
  }

  return colors.white;
}

function statusLabel(status: FleetStatus) {
  if (status === "VERDE") {
    return "verde";
  }

  if (status === "VERMELHO") {
    return "vermelho";
  }

  if (status === "AZUL") {
    return "azul";
  }

  return "sem status";
}

function formatPercent(value: number) {
  return `${value.toFixed(1).replace(".", ",")}%`;
}

function formatDateTime(value: Date) {
  return new Intl.DateTimeFormat("pt-BR", {
    dateStyle: "short",
    timeStyle: "short"
  }).format(value).replace(",", "");
}
