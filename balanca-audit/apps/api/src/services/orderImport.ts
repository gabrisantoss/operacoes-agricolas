import { createHash } from "node:crypto";
import fs from "node:fs/promises";
import ExcelJS from "exceljs";
import { db } from "../db.js";
import { badRequest } from "../errors.js";
import { FarmsRepository } from "../repositories/farmsRepository.js";
import { OrderImportConflictError, OrdersRepository } from "../repositories/ordersRepository.js";
import { OrderImportHistoryRepository, isDuplicateOrderImportFileError } from "../repositories/orderImportHistoryRepository.js";
import { toSemicolonCsv } from "./csvExport.js";
import {
  buildOrderImportPlan,
  type OrderImportPlan,
  type OrderImportPreview,
  type OrderImportSourceRow
} from "./orderImportPlan.js";

const MAX_ORDER_IMPORT_ROWS = 10_000;
const SHA256_PATTERN = /^[a-f0-9]{64}$/i;

export async function previewOrderImport(filePath: string, fileName: string): Promise<OrderImportPreview> {
  const { rows, fileHash } = await readOrderImportFile(filePath);
  return publicPreview(buildOrderImportPlan(rows, snapshotImportState(fileHash), fileName, fileHash));
}

export async function commitOrderImport(filePath: string, fileName: string, expectedFileHash: string, importedById: string | null = null) {
  if (!SHA256_PATTERN.test(expectedFileHash)) {
    throw badRequest("Gere a previa deste arquivo antes de confirmar a importacao.");
  }

  const { rows, fileHash } = await readOrderImportFile(filePath);
  if (fileHash !== expectedFileHash.toLowerCase()) {
    throw badRequest("O arquivo enviado mudou depois da previa. Gere uma nova previa e confirme novamente.");
  }

  const plan = buildOrderImportPlan(rows, snapshotImportState(fileHash), fileName, fileHash);
  if (plan.previousImport) {
    throw badRequest(duplicateFileMessage(plan.previousImport));
  }
  if (plan.summary.errorsCount > 0) {
    throw badRequest(
      `Importacao bloqueada: a previa contem ${plan.summary.errorsCount} erro(s). ${plan.errors[0] ?? "Corrija a planilha."}`
    );
  }

  // Orders and the import record are written together; divergences are recorded, never applied.
  let importId = "";
  try {
    const history = new OrderImportHistoryRepository(db);
    const orders = new OrdersRepository(db).applyImportActions(plan.actions, () => {
      importId = history.insert(publicPreview(plan), importedById);
    });
    return {
      ...publicPreview(plan),
      importId,
      committedCount: orders.length,
      orders
    };
  } catch (error) {
    if (error instanceof OrderImportConflictError) {
      throw badRequest("As OS mudaram depois da previa. Gere uma nova previa antes de confirmar a importacao.");
    }
    if (isDuplicateOrderImportFileError(error)) {
      throw badRequest("Este arquivo acabou de ser importado por outra sessao; nenhuma alteracao foi aplicada.");
    }
    throw error;
  }
}

export function listOrderImports(limit?: number) {
  return new OrderImportHistoryRepository(db).list(limit);
}

export function findOrderImport(id: string) {
  const batch = new OrderImportHistoryRepository(db).find(id);
  if (!batch) {
    throw badRequest("Importacao de OS nao encontrada.");
  }
  return batch;
}

export function orderImportReportCsv(id: string) {
  const batch = findOrderImport(id);
  const rows: unknown[][] = [
    ["Arquivo", "Importado em", "Linha", "Codigo da OS", "Propriedade", "Setor", "Resultado", "Detalhe"]
  ];
  for (const item of batch.items) {
    rows.push([batch.fileName, batch.importedAt, item.rowNumber, item.orderNumber, item.farmReference, item.fieldReference, statusLabels[item.status], item.message]);
  }
  for (const divergence of batch.divergences.filter((item) => item.rowNumber === null)) {
    rows.push([batch.fileName, batch.importedAt, "", divergence.orderNumber, divergence.farmName, divergence.fieldCode, statusLabels.DIVERGENCE, divergence.message]);
  }
  return toSemicolonCsv(rows);
}

const statusLabels: Record<OrderImportPreview["items"][number]["status"], string> = {
  CREATE: "OS criada",
  UPDATE: "Setor adicionado",
  SKIP: "Sem alteracao",
  DIVERGENCE: "Divergencia (nao aplicada)",
  ERROR: "Erro"
};

function duplicateFileMessage(previous: NonNullable<OrderImportPreview["previousImport"]>) {
  return `Este arquivo ja foi importado em ${new Date(previous.importedAt).toLocaleString("pt-BR")} como '${previous.fileName}'; nenhuma alteracao foi aplicada.`;
}

async function readOrderImportFile(filePath: string) {
  const contents = await fs.readFile(filePath);
  const fileHash = createHash("sha256").update(contents).digest("hex");
  const workbook = new ExcelJS.Workbook();

  try {
    await workbook.xlsx.readFile(filePath);
  } catch {
    throw badRequest("Planilha XLSX invalida ou corrompida.");
  }

  const worksheet = workbook.getWorksheet(1);
  if (!worksheet) {
    throw badRequest("Planilha vazia ou invalida.");
  }
  if (worksheet.actualRowCount - 1 > MAX_ORDER_IMPORT_ROWS) {
    throw badRequest(`A planilha excede o limite de ${MAX_ORDER_IMPORT_ROWS} linhas.`);
  }

  const header = new Map<string, number>();
  worksheet.getRow(1).eachCell((cell, columnNumber) => {
    header.set(normalizeText(readCell(cell).text), columnNumber);
  });
  const orderColumn = header.get("codigo da os");
  const farmColumn = header.get("propriedade");
  const fieldColumn = header.get("setor");
  if (!orderColumn || !farmColumn || !fieldColumn) {
    throw badRequest("Cabecalho invalido. Sao obrigatorias as colunas 'Codigo da OS', 'Propriedade' e 'Setor'.");
  }

  const rows: OrderImportSourceRow[] = [];
  worksheet.eachRow({ includeEmpty: false }, (row, rowNumber) => {
    if (rowNumber === 1) return;
    const order = readCell(row.getCell(orderColumn));
    const farm = readCell(row.getCell(farmColumn));
    const field = readCell(row.getCell(fieldColumn));
    if (!order.text && !farm.text && !field.text) return;

    rows.push({
      rowNumber,
      orderNumber: order.text,
      farmReference: farm.text,
      fieldReference: field.text,
      error: order.formula || farm.formula || field.formula
        ? "formulas nao sao aceitas nas colunas de identificacao; substitua-as por valores."
        : undefined
    });
  });

  if (rows.length === 0) {
    throw badRequest("A planilha nao contem linhas de OS para importar.");
  }

  return { rows, fileHash };
}

function snapshotImportState(fileHash: string) {
  const previous = new OrderImportHistoryRepository(db).findByFileHash(fileHash);
  return {
    farms: new FarmsRepository(db).listFarms(),
    orders: new OrdersRepository(db).listOrders(),
    previousImport: previous ? { fileName: previous.fileName, importedAt: previous.importedAt } : null
  };
}

function publicPreview(plan: OrderImportPlan): OrderImportPreview {
  const { actions: _actions, ...preview } = plan;
  return preview;
}

function normalizeText(value: string | null | undefined) {
  return String(value ?? "")
    .normalize("NFD")
    .replace(/\p{Diacritic}/gu, "")
    .replace(/\s+/g, " ")
    .trim()
    .toLocaleLowerCase("pt-BR");
}

function readCell(cell: ExcelJS.Cell) {
  const value = cell.value;
  if (value === null || value === undefined) return { text: "", formula: false };
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") {
    return { text: String(value).trim(), formula: false };
  }
  if (value instanceof Date) {
    return { text: value.toISOString(), formula: false };
  }
  if ("formula" in value || "sharedFormula" in value) {
    const result = "result" in value ? value.result : "";
    return { text: result === null || result === undefined ? "" : String(result).trim(), formula: true };
  }
  if ("richText" in value) {
    return { text: value.richText.map((part) => part.text).join("").trim(), formula: false };
  }
  if ("text" in value) {
    return { text: String(value.text).trim(), formula: false };
  }

  return { text: String(value).trim(), formula: false };
}
