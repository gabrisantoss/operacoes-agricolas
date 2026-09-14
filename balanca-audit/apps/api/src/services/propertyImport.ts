import { randomUUID } from "node:crypto";
import { formatFarmCode, normalizeFarmText } from "@balanca/shared";
import ExcelJS from "exceljs";
import { backupCurrentDatabase } from "../databaseBackup.js";
import { db } from "../db.js";
import { badRequest } from "../errors.js";

export type PropertyImportAction = "INSERT" | "UPDATE" | "MERGE";

export type PropertyImportPreviewRow = PropertyRow & {
  action: PropertyImportAction;
  existingCode?: string | null;
  warnings: string[];
};

export type PropertyImportSummary = {
  rowCount: number;
  insertCount: number;
  updateCount: number;
  mergeCount: number;
  duplicateNameCount: number;
  missingAreaCount: number;
  missingAddressCount: number;
};

export type PropertyImportPreview = {
  fileName: string;
  summary: PropertyImportSummary;
  rows: PropertyImportPreviewRow[];
};

export type PropertyImportCommitResult = PropertyImportPreview & {
  backupPath?: string;
};

type PropertyRow = {
  code: string;
  legacyCode: string;
  legacyCodeUnpadded: string;
  propertyNumber: string;
  sequenceNumber: string;
  name: string;
  areaHa: number | null;
  areaAlq: number | null;
  street: string | null;
  city: string | null;
  postalCode: string | null;
};

type ImportCounters = {
  inserted: number;
  updated: number;
};

const headerRowNumber = 7;
const firstDataRowNumber = 8;

export async function previewPropertyImport(filePath: string, fileName: string): Promise<PropertyImportPreview> {
  const records = await readPropertyRows(filePath);
  return buildPreview(fileName, records);
}

export async function commitPropertyImport(
  filePath: string,
  fileName: string,
  options: { createBackup?: boolean } = {}
): Promise<PropertyImportCommitResult> {
  const records = await readPropertyRows(filePath);
  const preview = buildPreview(fileName, records);
  const backupPath = options.createBackup ? await backupDatabase() : undefined;

  importRows(records);

  return {
    ...preview,
    backupPath
  };
}

export function importPropertyRows(records: PropertyRow[]): ImportCounters {
  return importRows(records);
}

async function readPropertyRows(filePath: string) {
  // Verificacao removida

  const workbook = new ExcelJS.Workbook();
  await workbook.xlsx.readFile(filePath);

  const worksheet = workbook.worksheets[0];

  if (!worksheet) {
    throw badRequest("A planilha nao possui abas.");
  }

  const columns = mapColumns(worksheet.getRow(headerRowNumber));
  const rows: PropertyRow[] = [];

  for (let rowNumber = firstDataRowNumber; rowNumber <= worksheet.rowCount; rowNumber += 1) {
    const row = worksheet.getRow(rowNumber);
    const propertyNumber = digitsOnly(cellText(row.getCell(columns.property)));
    const sequenceNumber = digitsOnly(cellText(row.getCell(columns.sequence)));
    const name = normalizeFarmText(cellText(row.getCell(columns.name)));

    if (!propertyNumber || !sequenceNumber || !name) {
      continue;
    }

    const sequenceCode = buildSequenceCode(sequenceNumber);
    const propertyCode = propertyNumber.padStart(3, "0");

    rows.push({
      code: `${sequenceCode}-${propertyCode}`,
      legacyCode: `${sequenceCode}${propertyCode}`,
      legacyCodeUnpadded: `${sequenceCode}${propertyNumber}`,
      propertyNumber,
      sequenceNumber,
      name,
      areaHa: cellNumber(row.getCell(columns.areaHa)),
      areaAlq: cellNumber(row.getCell(columns.areaAlq)),
      street: nullIfEmpty(normalizeFarmText(cellText(row.getCell(columns.street)))),
      city: nullIfEmpty(normalizeFarmText(cellText(row.getCell(columns.city)))),
      postalCode: formatPostalCode(cellText(row.getCell(columns.postalCode)))
    });
  }

  if (rows.length === 0) {
    throw badRequest("Nenhuma propriedade valida encontrada na planilha.");
  }

  return rows;
}

function buildPreview(fileName: string, records: PropertyRow[]): PropertyImportPreview {
  const nameCounts = buildNameCounts(records);
  const rows = records.map((record) => {
    const candidates = findFarmCandidates(record);
    const selected = chooseFarmCandidate(candidates, record.code);
    const warnings: string[] = [];

    if (nameCounts.get(normalize(record.name))! > 1) {
      warnings.push("Nome repetido na planilha.");
    }

    if (record.areaHa === null || record.areaAlq === null) {
      warnings.push("Area incompleta.");
    }

    if (!record.street || !record.city || !record.postalCode) {
      warnings.push("Endereco incompleto.");
    }

    return {
      ...record,
      action: classifyAction(record, candidates, selected),
      existingCode: selected?.code,
      warnings
    };
  });

  return {
    fileName,
    summary: summarizeRows(rows),
    rows: rows.slice(0, 200)
  };
}

function summarizeRows(rows: PropertyImportPreviewRow[]): PropertyImportSummary {
  return {
    rowCount: rows.length,
    insertCount: rows.filter((row) => row.action === "INSERT").length,
    updateCount: rows.filter((row) => row.action === "UPDATE").length,
    mergeCount: rows.filter((row) => row.action === "MERGE").length,
    duplicateNameCount: rows.filter((row) => row.warnings.includes("Nome repetido na planilha.")).length,
    missingAreaCount: rows.filter((row) => row.areaHa === null || row.areaAlq === null).length,
    missingAddressCount: rows.filter((row) => !row.street || !row.city || !row.postalCode).length
  };
}

function importRows(records: PropertyRow[]): ImportCounters {
  return db.transaction((items: PropertyRow[]) => {
    const insertFarm = db.prepare(`
      INSERT INTO farms (
        id,
        code,
        name,
        property_number,
        sequence_number,
        area_ha,
        area_alq,
        street,
        city,
        postal_code,
        created_at,
        updated_at
      )
      VALUES (
        @id,
        @code,
        @name,
        @propertyNumber,
        @sequenceNumber,
        @areaHa,
        @areaAlq,
        @street,
        @city,
        @postalCode,
        CURRENT_TIMESTAMP,
        CURRENT_TIMESTAMP
      )
    `);

    const updateFarm = db.prepare(`
      UPDATE farms
      SET
        code = @code,
        name = @name,
        property_number = @propertyNumber,
        sequence_number = @sequenceNumber,
        area_ha = @areaHa,
        area_alq = @areaAlq,
        street = @street,
        city = @city,
        postal_code = @postalCode,
        updated_at = CURRENT_TIMESTAMP
      WHERE id = @id
    `);

    const deleteFarm = db.prepare("DELETE FROM farms WHERE id = ?");

    let inserted = 0;
    let updated = 0;

    const deleteParamsList: any[] = [];
    const updateParamsList: any[] = [];
    const insertParamsList: any[] = [];

    for (const record of items) {
      const normalizedRecord = {
        ...record,
        code: formatFarmCode(record.code),
        name: normalizeFarmText(record.name),
        street: record.street ? normalizeFarmText(record.street) : null,
        city: record.city ? normalizeFarmText(record.city) : null
      };
      const candidates = findFarmCandidates(normalizedRecord);
      const existing = chooseFarmCandidate(candidates, normalizedRecord.code);

      if (existing) {
        for (const candidate of candidates) {
          if (candidate.id === existing.id) {
            continue;
          }

          if (candidate.referenceCount > 0) {
            throw new Error(`Conflito: ${normalizedRecord.code} tem mais de uma fazenda com vinculos no banco.`);
          }

          deleteParamsList.push([candidate.id]);
        }

        updateParamsList.push({ ...normalizedRecord, id: existing.id });
        updated += 1;
        continue;
      }

      insertParamsList.push({ ...normalizedRecord, id: randomUUID() });
      inserted += 1;
    }

    if (deleteParamsList.length > 0) deleteFarm.runMany(deleteParamsList);
    if (updateParamsList.length > 0) updateFarm.runMany(updateParamsList);
    if (insertParamsList.length > 0) insertFarm.runMany(insertParamsList);

    return { inserted, updated };
  })(records);
}

async function backupDatabase() {
  return backupCurrentDatabase("balanca-before-properties");
}



function mapColumns(headerRow: ExcelJS.Row) {
  const headers = new Map<string, number>();

  headerRow.eachCell({ includeEmpty: true }, (cell, columnNumber) => {
    const header = normalizeHeader(cellText(cell));

    if (header && !headers.has(header)) {
      headers.set(header, columnNumber);
    }
  });

  return {
    property: requiredColumn(headers, "propriedade"),
    sequence: requiredColumn(headers, "sequencia"),
    name: requiredColumn(headers, "fundo agricola"),
    areaHa: requiredColumn(headers, "area ha"),
    areaAlq: requiredColumn(headers, "area alq"),
    street: requiredColumn(headers, "logradouro"),
    city: requiredColumn(headers, "cidade"),
    postalCode: requiredColumn(headers, "cep")
  };
}

function requiredColumn(headers: Map<string, number>, header: string) {
  const column = headers.get(header);

  if (!column) {
    throw badRequest(`Coluna obrigatoria nao encontrada: ${header}`);
  }

  return column;
}

function findFarmCandidates(record: PropertyRow) {
  const rows = db
    .prepare(
      `
      SELECT id, code
      FROM farms
      WHERE code = @code OR code = @legacyCode OR code = @legacyCodeUnpadded
      `
    )
    .all(record) as Array<{ id: string; code: string | null }>;

  return rows.map((candidate) => ({
    ...candidate,
    referenceCount: countFarmReferences(candidate.id)
  }));
}

function countFarmReferences(id: string) {
  return (
    db
      .prepare(
        `
        SELECT
          (SELECT COUNT(*) FROM fields WHERE farm_id = @id) +
          (SELECT COUNT(*) FROM harvest_orders WHERE farm_id = @id) +
          (SELECT COUNT(*) FROM cane_entries WHERE farm_id = @id) AS count
        `
      )
      .get({ id }) as { count: number }
  ).count;
}

function chooseFarmCandidate(candidates: Array<{ id: string; code: string | null; referenceCount: number }>, code: string) {
  if (candidates.length === 0) {
    return null;
  }

  return [...candidates].sort((left, right) => {
    if (left.referenceCount !== right.referenceCount) {
      return right.referenceCount - left.referenceCount;
    }

    if (left.code === code && right.code !== code) {
      return -1;
    }

    if (right.code === code && left.code !== code) {
      return 1;
    }

    return 0;
  })[0];
}

function classifyAction(
  record: PropertyRow,
  candidates: Array<{ id: string; code: string | null; referenceCount: number }>,
  selected: { code: string | null } | null
): PropertyImportAction {
  if (!selected) {
    return "INSERT";
  }

  if (selected.code !== record.code || candidates.length > 1) {
    return "MERGE";
  }

  return "UPDATE";
}

function buildNameCounts(records: PropertyRow[]) {
  const counts = new Map<string, number>();

  for (const record of records) {
    const name = normalize(record.name);
    counts.set(name, (counts.get(name) ?? 0) + 1);
  }

  return counts;
}

function buildSequenceCode(sequenceNumber: string) {
  const number = Number(sequenceNumber);

  if (!Number.isFinite(number) || number < 0) {
    throw badRequest(`Sequencia invalida: ${sequenceNumber}`);
  }

  if (number < 20) {
    return String(100 + number).padStart(3, "0");
  }

  if (number < 100) {
    return String(number * 10).padStart(3, "0");
  }

  return String(number);
}

function cellText(cell: ExcelJS.Cell) {
  const value = cell.value;

  if (value === null || value === undefined) {
    return "";
  }

  if (value instanceof Date) {
    return value.toISOString();
  }

  if (typeof value === "object") {
    if ("result" in value) {
      return String(value.result ?? "").trim();
    }

    if ("text" in value) {
      return String(value.text ?? "").trim();
    }

    if ("richText" in value && Array.isArray(value.richText)) {
      return value.richText.map((part) => part.text).join("").trim();
    }
  }

  return String(value).trim();
}

function cellNumber(cell: ExcelJS.Cell) {
  const text = normalizeNumberText(cellText(cell));

  if (!text) {
    return null;
  }

  const value = Number(text);
  return Number.isFinite(value) ? value : null;
}

function normalizeNumberText(value: string) {
  const text = value.trim();

  if (!text) {
    return "";
  }

  if (text.includes(",")) {
    return text.replace(/\./g, "").replace(",", ".");
  }

  return text;
}

function normalize(value: string) {
  return value
    .normalize("NFD")
    .replace(/\p{Diacritic}/gu, "")
    .toLowerCase()
    .trim();
}

function normalizeHeader(value: string) {
  return normalize(value);
}

function digitsOnly(value: string) {
  return value.replace(/\D/g, "");
}

function nullIfEmpty(value: string) {
  return value || null;
}

function formatPostalCode(value: string) {
  const digits = digitsOnly(value);

  if (!digits) {
    return null;
  }

  return digits.padStart(8, "0");
}
