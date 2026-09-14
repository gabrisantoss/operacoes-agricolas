import fs from "node:fs/promises";
import type { NextFunction, Request, Response } from "express";
import { Router } from "express";
import ExcelJS from "exceljs";
import multer from "multer";
import { createFarmSchema, createFieldSchema, systemIdentity, updateFarmSchema, updateFieldSchema } from "@balanca/shared";
import { createFarm, createField, listFarms, updateFarm, updateField } from "../db.js";
import { env } from "../env.js";
import { badRequest } from "../errors.js";
import { paginateList, readPagination } from "../httpPagination.js";
import { requireRoles } from "../middleware/requireAuth.js";
import { commitFieldImport, previewFieldImport } from "../services/fieldImport.js";
import { commitPropertyImport, previewPropertyImport } from "../services/propertyImport.js";
import { assertUploadedFile } from "../services/uploadValidation.js";
import { reconcileGlobalOrphansAsync } from "../services/importer.js";
import { assertExportRowLimit } from "../services/exportControl.js";

await fs.mkdir(env.uploadDir, { recursive: true });

const upload = multer({
  dest: env.uploadDir,
  limits: {
    fileSize: 25 * 1024 * 1024
  }
});

export const farmsRouter = Router();
const manageFarmsOnly = requireRoles(["ADMIN", "ANALYST"]);

farmsRouter.get("/", async (req, res) => {
  const farms = listFarms();
  const pagination = readPagination(req.query, { defaultLimit: 200, maxLimit: 2000 });

  if (pagination.requested) {
    const page = paginateList(farms, pagination);
    return res.json({ farms: page.items, total: page.total, limit: page.limit, offset: page.offset });
  }

  return res.json({ farms });
});

farmsRouter.get("/export.xlsx", async (_req, res) => {
  const farms = listFarms();
  assertExportRowLimit(farms.reduce((total, farm) => total + Math.max(1, farm.fields.length), 0));
  const workbook = buildFarmRegistryWorkbook(farms);
  const fileName = `cadastro-fazendas-talhoes-${new Date().toISOString().slice(0, 10)}.xlsx`;
  const buffer = await workbook.xlsx.writeBuffer();

  res.setHeader("Content-Type", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet");
  res.setHeader("Content-Disposition", `attachment; filename="${fileName}"`);
  return res.send(Buffer.from(buffer));
});

farmsRouter.post("/", manageFarmsOnly, async (req, res) => {
  const input = createFarmSchema.safeParse(req.body);

  if (!input.success) {
    return res.status(400).json({ message: "Cadastro de fazenda invalido." });
  }

  const farm = createFarm(input.data);

  reconcileGlobalOrphansAsync();

  return res.status(201).json({ farm });
});

farmsRouter.post("/import/preview", manageFarmsOnly, upload.single("file"), async (req, res, next) => {
  await handleUploadedFile(req, res, next, async () => {
    if (!req.file) {
      throw badRequest("Envie uma planilha.");
    }

    await assertUploadedFile(req.file, [".xlsx"], "Envie uma planilha .xlsx valida.");
    const preview = await previewPropertyImport(req.file.path, req.file.originalname);
    return res.json(preview);
  });
});

farmsRouter.post("/import", manageFarmsOnly, upload.single("file"), async (req, res, next) => {
  await handleUploadedFile(req, res, next, async () => {
    if (!req.file) {
      throw badRequest("Envie uma planilha.");
    }

    await assertUploadedFile(req.file, [".xlsx"], "Envie uma planilha .xlsx valida.");
    const result = await commitPropertyImport(req.file.path, req.file.originalname, { createBackup: true });

    reconcileGlobalOrphansAsync();

    return res.status(201).json(result);
  });
});

farmsRouter.post("/fields/import/preview", manageFarmsOnly, upload.single("file"), async (req, res, next) => {
  await handleUploadedFile(req, res, next, async () => {
    if (!req.file) {
      throw badRequest("Envie uma planilha.");
    }

    await assertUploadedFile(req.file, [".xlsx"], "Envie uma planilha .xlsx valida.");
    const preview = await previewFieldImport(req.file.path, req.file.originalname);
    return res.json(preview);
  });
});

farmsRouter.post("/fields/import", manageFarmsOnly, upload.single("file"), async (req, res, next) => {
  await handleUploadedFile(req, res, next, async () => {
    if (!req.file) {
      throw badRequest("Envie uma planilha.");
    }

    await assertUploadedFile(req.file, [".xlsx"], "Envie uma planilha .xlsx valida.");
    const result = await commitFieldImport(req.file.path, req.file.originalname, { createBackup: true });

    reconcileGlobalOrphansAsync();

    return res.status(201).json(result);
  });
});

farmsRouter.post("/:farmId/fields", manageFarmsOnly, async (req, res) => {
  const farmId = routeParam(req.params.farmId);
  const input = createFieldSchema.safeParse(req.body);

  if (!input.success) {
    return res.status(400).json({ message: "Cadastro de talhao invalido." });
  }

  const codes = parseFieldCodes(input.data.code);

  if (codes.length === 0) {
    return res.status(400).json({ message: "Informe o talhao." });
  }

  const fields = codes.map((code) => createField(farmId, code, input.data.name ?? null, input.data.areaAlq));

  reconcileGlobalOrphansAsync();

  return res.status(201).json({ field: fields[0], fields });
});

farmsRouter.put("/fields/:fieldId", manageFarmsOnly, async (req, res) => {
  const fieldId = routeParam(req.params.fieldId);
  const input = updateFieldSchema.safeParse(req.body);

  if (!input.success) {
    return res.status(400).json({ message: "Edicao de talhao invalida." });
  }

  const field = updateField(fieldId, input.data);

  if (!field) {
    return res.status(404).json({ message: "Talhao nao encontrado." });
  }

  reconcileGlobalOrphansAsync();

  return res.json({ field });
});

farmsRouter.put("/:farmId", manageFarmsOnly, async (req, res) => {
  const farmId = routeParam(req.params.farmId);
  const input = updateFarmSchema.safeParse(req.body);

  if (!input.success) {
    return res.status(400).json({ message: "Edicao de fazenda invalida." });
  }

  const farm = updateFarm(farmId, input.data);

  if (!farm) {
    return res.status(404).json({ message: "Fazenda nao encontrada." });
  }

  reconcileGlobalOrphansAsync();

  return res.json({ farm });
});

function parseFieldCodes(value: string) {
  return Array.from(
    new Set(
      value
        .split(/[\s,;]+/)
        .map((item) => item.trim())
        .filter(Boolean)
    )
  );
}

function routeParam(value: string | string[]) {
  return Array.isArray(value) ? value[0] : value;
}

function buildFarmRegistryWorkbook(farms: ReturnType<typeof listFarms>) {
  const workbook = new ExcelJS.Workbook();
  workbook.creator = `Operacoes Agricolas - ${systemIdentity.currentName}`;
  workbook.created = new Date();
  workbook.modified = new Date();

  const sortedFarms = [...farms].sort(compareFarms);
  const summary = workbook.addWorksheet("Resumo Fazendas", {
    views: [{ state: "frozen", ySplit: 1 }]
  });
  const fields = workbook.addWorksheet("Talhoes por Fazenda", {
    views: [{ state: "frozen", ySplit: 1 }]
  });

  summary.columns = [
    { header: "Codigo fazenda", key: "code", width: 18 },
    { header: "Fazenda", key: "name", width: 44 },
    { header: "Cidade", key: "city", width: 24 },
    { header: "Talhoes", key: "fieldCount", width: 12 },
    { header: "Area talhoes ha", key: "fieldsAreaHa", width: 18 },
    { header: "Area talhoes alq", key: "fieldsAreaAlq", width: 18 },
    { header: "Area cadastro ha", key: "areaHa", width: 18 },
    { header: "Area cadastro alq", key: "areaAlq", width: 18 },
    { header: "Secao", key: "sectionName", width: 34 },
    { header: "Proprietario", key: "ownerName", width: 34 },
    { header: "Municipio", key: "municipality", width: 24 },
    { header: "Safra", key: "cropYear", width: 14 },
    { header: "Atualizado", key: "metadataUpdatedAt", width: 20 }
  ];

  fields.columns = [
    { header: "Codigo fazenda", key: "farmCode", width: 18 },
    { header: "Fazenda", key: "farmName", width: 44 },
    { header: "Talhao", key: "fieldCode", width: 12 },
    { header: "Nome talhao", key: "fieldName", width: 24 },
    { header: "Area ha", key: "areaHa", width: 14 },
    { header: "Area alq", key: "areaAlq", width: 14 },
    { header: "Area plantada ha", key: "plantedAreaHa", width: 18 },
    { header: "Safra", key: "cropYear", width: 14 },
    { header: "Tipo area", key: "areaType", width: 16 },
    { header: "Ativo", key: "active", width: 10 }
  ];

  styleHeader(summary);
  styleHeader(fields);

  for (const farm of sortedFarms) {
    const activeFields = farm.fields.filter((field) => field.active !== false);
    const fieldsAreaHa = sumNumbers(activeFields.map((field) => field.areaHa));
    const fieldsAreaAlq = sumNumbers(activeFields.map((field) => field.areaAlq));

    summary.addRow({
      code: farm.code ?? "",
      name: farm.name,
      city: farm.city ?? "",
      fieldCount: activeFields.length,
      fieldsAreaHa,
      fieldsAreaAlq,
      areaHa: farm.areaHa ?? "",
      areaAlq: farm.areaAlq ?? "",
      sectionName: farm.sectionName ?? "",
      ownerName: farm.ownerName ?? "",
      municipality: farm.municipality ?? "",
      cropYear: farm.cropYear ?? "",
      metadataUpdatedAt: farm.metadataUpdatedAt ?? ""
    });

    const farmHeaderRow = fields.addRow({
      farmCode: farm.code ?? "",
      farmName: farm.name,
      fieldCode: `${activeFields.length} talhoes`,
      fieldName: "",
      areaHa: fieldsAreaHa,
      areaAlq: fieldsAreaAlq,
      active: "Resumo"
    });
    farmHeaderRow.font = { bold: true, color: { argb: "FF0F3B2E" } };
    farmHeaderRow.fill = { type: "pattern", pattern: "solid", fgColor: { argb: "FFEAF5EE" } };

    for (const field of activeFields.sort(compareFields)) {
      fields.addRow({
        farmCode: farm.code ?? "",
        farmName: farm.name,
        fieldCode: field.code,
        fieldName: field.name ?? "",
        areaHa: field.areaHa ?? "",
        areaAlq: field.areaAlq ?? "",
        plantedAreaHa: field.plantedAreaHa ?? "",
        cropYear: field.cropYear ?? "",
        areaType: field.areaType ?? "",
        active: field.active === false ? "Nao" : "Sim"
      });
    }

    fields.addRow({});
  }

  formatNumericColumns(summary, ["E", "F", "G", "H", "M", "N"]);
  formatNumericColumns(fields, ["E", "F", "G"]);
  summary.autoFilter = "A1:O1";
  fields.autoFilter = "A1:J1";

  return workbook;
}

function styleHeader(worksheet: ExcelJS.Worksheet) {
  const header = worksheet.getRow(1);
  header.font = { bold: true, color: { argb: "FFFFFFFF" } };
  header.fill = { type: "pattern", pattern: "solid", fgColor: { argb: "FF14532D" } };
  header.alignment = { vertical: "middle", horizontal: "center" };
  header.height = 22;
}

function formatNumericColumns(worksheet: ExcelJS.Worksheet, columns: string[]) {
  for (const column of columns) {
    worksheet.getColumn(column).numFmt = "#,##0.00";
  }
}

function sumNumbers(values: Array<number | null | undefined>) {
  return values.reduce<number>(
    (total, value) => total + (typeof value === "number" && Number.isFinite(value) ? value : 0),
    0
  );
}

function compareFarms(left: ReturnType<typeof listFarms>[number], right: ReturnType<typeof listFarms>[number]) {
  return compareFarmCodes(left.code ?? "", right.code ?? "") || left.name.localeCompare(right.name, "pt-BR");
}

function compareFields(left: ReturnType<typeof listFarms>[number]["fields"][number], right: ReturnType<typeof listFarms>[number]["fields"][number]) {
  return compareFieldCodes(left.code, right.code);
}

function compareFarmCodes(left: string, right: string) {
  const leftParts = parseCodeParts(left);
  const rightParts = parseCodeParts(right);

  for (let index = 0; index < Math.max(leftParts.length, rightParts.length); index += 1) {
    const leftPart = leftParts[index];
    const rightPart = rightParts[index];

    if (leftPart === undefined) return -1;
    if (rightPart === undefined) return 1;
    if (leftPart !== rightPart) return leftPart - rightPart;
  }

  return left.localeCompare(right, "pt-BR", { numeric: true, sensitivity: "base" });
}

function compareFieldCodes(left: string, right: string) {
  return compareFarmCodes(left, right);
}

function parseCodeParts(value: string) {
  const parts = value.match(/\d+/g);
  return parts ? parts.map((part) => Number(part)) : [Number.MAX_SAFE_INTEGER];
}

async function handleUploadedFile(
  req: Request,
  res: Response,
  next: NextFunction,
  action: () => Promise<Response>
) {
  try {
    await action();
  } catch (error) {
    next(error);
  } finally {
    if (req.file) {
      await fs.unlink(req.file.path).catch(() => undefined);
    }
  }
}
