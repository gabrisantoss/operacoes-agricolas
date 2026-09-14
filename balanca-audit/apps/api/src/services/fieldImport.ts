import { randomUUID } from "node:crypto";
import path from "node:path";
import ExcelJS from "exceljs";
import { backupCurrentDatabase } from "../databaseBackup.js";
import { db } from "../db.js";
import { badRequest } from "../errors.js";

export type FieldImportAction = "INSERT" | "UPDATE" | "SKIP";

export type FieldImportPreviewRow = FieldImportRow & {
  action: FieldImportAction;
  existingFieldCode?: string | null;
  warnings: string[];
};

export type FieldImportSummary = {
  rowCount: number;
  insertCount: number;
  updateCount: number;
  skipCount: number;
  missingFarmCount: number;
  missingAreaCount: number;
  duplicateFieldCount: number;
  totalAreaHa: number;
  totalAreaAlq: number;
};

export type FieldImportPreview = {
  fileName: string;
  summary: FieldImportSummary;
  rows: FieldImportPreviewRow[];
};

export type FieldImportCommitResult = FieldImportPreview & {
  backupPath?: string;
};

type FieldImportRow = {
  farmCode: string;
  legacyFarmCode: string;
  legacyFarmCodeUnpadded: string;
  propertyNumber: string;
  sequenceNumber: string;
  farmName: string;
  fieldCode: string;
  fieldNumber: string;
  fieldLetter: string | null;
  areaHa: number | null;
  areaAlq: number | null;
  plantedAreaHa: number | null;
  cropYear: string | null;
  areaType: string | null;
  active: boolean;
};

type FarmCandidate = {
  id: string;
  code: string | null;
  name: string;
  property_number: string | null;
  sequence_number: string | null;
};

const headerRowNumber = 6;
const firstDataRowNumber = 7;
const hectaresPerAlqueire = 2.42;
const previewLimit = 200;

export async function previewFieldImport(filePath: string, fileName: string): Promise<FieldImportPreview> {
  const records = await readFieldRows(filePath, fileName);
  return buildPreview(fileName, records);
}

export async function commitFieldImport(
  filePath: string,
  fileName: string,
  options: { createBackup?: boolean } = {}
): Promise<FieldImportCommitResult> {
  const records = await readFieldRows(filePath, fileName);
  const preview = buildPreview(fileName, records);
  const backupPath = options.createBackup ? await backupDatabase() : undefined;

  importRows(records);

  return {
    ...preview,
    backupPath
  };
}

async function readFieldRows(filePath: string, fileName: string) {
  // Verificacao removida

  if (path.extname(fileName).toLowerCase() !== ".xlsx") {
    throw badRequest("Envie a planilha de talhoes em formato .xlsx.");
  }

  const workbook = new ExcelJS.Workbook();
  await workbook.xlsx.readFile(filePath);

  const worksheet = workbook.worksheets[0];

  if (!worksheet) {
    throw badRequest("A planilha nao possui abas.");
  }

  const columns = mapColumns(worksheet.getRow(headerRowNumber));
  const rows: FieldImportRow[] = [];

  for (let rowNumber = firstDataRowNumber; rowNumber <= worksheet.rowCount; rowNumber += 1) {
    const row = worksheet.getRow(rowNumber);
    const propertyNumber = digitsOnly(cellText(row.getCell(columns.property)));
    const sequenceNumber = digitsOnly(cellText(row.getCell(columns.sequence)));
    const fieldNumber = normalizeNumericCode(cellText(row.getCell(columns.field)));
    const farmName = cellText(row.getCell(columns.farmName));

    if (!propertyNumber || sequenceNumber === "" || !fieldNumber || !farmName) {
      continue;
    }

    const fieldLetter = normalizeFieldLetter(columns.fieldLetter ? cellText(row.getCell(columns.fieldLetter)) : "");
    const sequenceCode = buildSequenceCode(sequenceNumber);
    const propertyCode = propertyNumber.padStart(3, "0");
    const areaHa = cellNumber(row.getCell(columns.areaHa));

    rows.push({
      farmCode: `${sequenceCode}-${propertyCode}`,
      legacyFarmCode: `${sequenceCode}${propertyCode}`,
      legacyFarmCodeUnpadded: `${sequenceCode}${propertyNumber}`,
      propertyNumber,
      sequenceNumber,
      farmName,
      fieldCode: buildFieldCode(fieldNumber, fieldLetter),
      fieldNumber,
      fieldLetter,
      areaHa,
      areaAlq: calculateAreaAlq(areaHa),
      plantedAreaHa: cellNumber(row.getCell(columns.plantedAreaHa)),
      cropYear: nullIfEmpty(cellText(row.getCell(columns.cropYear))),
      areaType: nullIfEmpty(cellText(row.getCell(columns.areaType))),
      active: parseActive(cellText(row.getCell(columns.active)))
    });
  }

  if (rows.length === 0) {
    throw badRequest("Nenhum talhao valido encontrado na planilha.");
  }

  return rows;
}

function buildPreview(fileName: string, records: FieldImportRow[]): FieldImportPreview {
  const keyCounts = buildKeyCounts(records);
  const rows = records.map((record) => {
    const farm = findFarmCandidate(record);
    const existing = farm ? findFieldCandidate(farm.id, record) : null;
    const warnings: string[] = [];
    const duplicate = keyCounts.get(recordKey(record))! > 1;

    if (!farm) {
      warnings.push("Fazenda nao encontrada para propriedade/sequencia.");
    }

    if (record.areaHa === null) {
      warnings.push("Area do talhao ausente.");
    }

    if (duplicate) {
      warnings.push("Talhao repetido na planilha.");
    }

    const action: FieldImportAction = farm ? (existing ? "UPDATE" : "INSERT") : "SKIP";

    return {
      ...record,
      action,
      existingFieldCode: existing?.code,
      warnings
    };
  });

  return {
    fileName,
    summary: summarizeRows(rows),
    rows: rows.slice(0, previewLimit)
  };
}

function summarizeRows(rows: FieldImportPreviewRow[]): FieldImportSummary {
  return {
    rowCount: rows.length,
    insertCount: rows.filter((row) => row.action === "INSERT").length,
    updateCount: rows.filter((row) => row.action === "UPDATE").length,
    skipCount: rows.filter((row) => row.action === "SKIP").length,
    missingFarmCount: rows.filter((row) => row.warnings.includes("Fazenda nao encontrada para propriedade/sequencia.")).length,
    missingAreaCount: rows.filter((row) => row.areaHa === null).length,
    duplicateFieldCount: rows.filter((row) => row.warnings.includes("Talhao repetido na planilha.")).length,
    totalAreaHa: roundArea(rows.reduce((sum, row) => sum + (row.areaHa ?? 0), 0)),
    totalAreaAlq: roundArea(rows.reduce((sum, row) => sum + (row.areaAlq ?? 0), 0))
  };
}

function importRows(records: FieldImportRow[]) {
  db.transaction((items: FieldImportRow[]) => {
    const insertField = db.prepare(`
      INSERT INTO fields (
        id,
        code,
        farm_id,
        area_ha,
        area_alq,
        planted_area_ha,
        crop_year,
        area_type,
        active,
        created_at,
        updated_at
      )
      VALUES (
        @id,
        @fieldCode,
        @farmId,
        @areaHa,
        @areaAlq,
        @plantedAreaHa,
        @cropYear,
        @areaType,
        @activeInt,
        CURRENT_TIMESTAMP,
        CURRENT_TIMESTAMP
      )
    `);

    const updateField = db.prepare(`
      UPDATE fields
      SET
        code = @fieldCode,
        area_ha = @areaHa,
        area_alq = @areaAlq,
        planted_area_ha = @plantedAreaHa,
        crop_year = @cropYear,
        area_type = @areaType,
        active = @activeInt,
        updated_at = CURRENT_TIMESTAMP
      WHERE id = @id
    `);

    const insertParamsList = [];
    const updateParamsList = [];

    for (const record of items) {
      const farm = findFarmCandidate(record);
      if (!farm) {
        continue;
      }

      const existing = findFieldCandidate(farm.id, record);
      const params = {
        ...record,
        id: existing?.id ?? randomUUID(),
        farmId: farm.id,
        activeInt: record.active ? 1 : 0
      };

      if (existing) {
        updateParamsList.push(params);
      } else {
        insertParamsList.push(params);
      }
    }

    if (insertParamsList.length > 0) {
      insertField.runMany(insertParamsList);
    }
    if (updateParamsList.length > 0) {
      updateField.runMany(updateParamsList);
    }
  })(records);
}

async function backupDatabase() {
  return backupCurrentDatabase("balanca-before-fields");
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
    property: requiredColumn(headers, ["propriedade"]),
    sequence: requiredColumn(headers, ["seq.", "sequencia"]),
    farmName: requiredColumn(headers, ["fundo agricola"]),
    field: requiredColumn(headers, ["talhao"]),
    fieldLetter: optionalColumn(headers, ["letra"]),
    active: requiredColumn(headers, ["ativo"]),
    areaHa: requiredColumn(headers, ["area ha"]),
    plantedAreaHa: requiredColumn(headers, ["area plantada"]),
    cropYear: requiredColumn(headers, ["ano safra"]),
    areaType: requiredColumn(headers, ["tipo area"])
  };
}

function requiredColumn(headers: Map<string, number>, names: string[]) {
  const column = optionalColumn(headers, names);

  if (!column) {
    throw badRequest(`Coluna obrigatoria nao encontrada: ${names[0]}`);
  }

  return column;
}

function optionalColumn(headers: Map<string, number>, names: string[]) {
  for (const name of names) {
    const column = headers.get(name);

    if (column) {
      return column;
    }
  }

  return 0;
}

function findFarmCandidate(record: FieldImportRow) {
  const rows = db
    .prepare(
      `
      SELECT id, code, name, property_number, sequence_number
      FROM farms
      WHERE
        code = @farmCode
        OR code = @legacyFarmCode
        OR code = @legacyFarmCodeUnpadded
        OR (property_number = @propertyNumber AND sequence_number = @sequenceNumber)
      `
    )
    .all(record) as FarmCandidate[];

  return (
    rows.sort((left, right) => farmCandidateScore(left, record) - farmCandidateScore(right, record))[0] ?? null
  );
}

function farmCandidateScore(candidate: FarmCandidate, record: FieldImportRow) {
  if (candidate.code === record.farmCode) {
    return 0;
  }

  if (candidate.property_number === record.propertyNumber && candidate.sequence_number === record.sequenceNumber) {
    return 1;
  }

  return 2;
}

function findFieldCandidate(farmId: string, record: FieldImportRow) {
  const paddedFieldCode = buildFieldCode(record.fieldNumber.padStart(3, "0"), record.fieldLetter);
  const rows = db
    .prepare(
      `
      SELECT id, code
      FROM fields
      WHERE farm_id = @farmId AND (code = @fieldCode OR code = @paddedFieldCode)
      `
    )
    .all({ farmId, fieldCode: record.fieldCode, paddedFieldCode }) as Array<{ id: string; code: string }>;

  return rows.find((row) => row.code === record.fieldCode) ?? rows[0] ?? null;
}

function buildKeyCounts(records: FieldImportRow[]) {
  const counts = new Map<string, number>();

  for (const record of records) {
    const key = recordKey(record);
    counts.set(key, (counts.get(key) ?? 0) + 1);
  }

  return counts;
}

function recordKey(record: FieldImportRow) {
  return `${record.farmCode}|${record.fieldCode}`;
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

function buildFieldCode(fieldNumber: string, fieldLetter: string | null) {
  return `${fieldNumber}${fieldLetter ?? ""}`;
}

function normalizeFieldLetter(value: string) {
  const text = value.trim().toUpperCase();
  return text ? text.replace(/\s+/g, "") : null;
}

function calculateAreaAlq(areaHa: number | null) {
  return areaHa === null ? null : roundArea(areaHa / hectaresPerAlqueire);
}

function roundArea(value: number) {
  return Math.round(value * 1000) / 1000;
}

function parseActive(value: string) {
  const normalized = normalize(value);

  if (!normalized) {
    return true;
  }

  return !["0", "n", "nao", "false"].includes(normalized);
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

function normalizeNumericCode(value: string) {
  const digits = digitsOnly(value);

  if (!digits) {
    return "";
  }

  const number = Number(digits);

  if (!Number.isFinite(number)) {
    return digits;
  }

  return String(number);
}

function normalize(value: string) {
  return value
    .normalize("NFD")
    .replace(/\p{Diacritic}/gu, "")
    .toLowerCase()
    .trim();
}

function normalizeHeader(value: string) {
  return normalize(value).replace(/\s+/g, " ");
}

function digitsOnly(value: string) {
  return value.replace(/\D/g, "");
}

function nullIfEmpty(value: string) {
  return value || null;
}
