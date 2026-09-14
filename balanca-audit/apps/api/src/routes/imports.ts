import fs from "node:fs/promises";
import path from "node:path";
import { randomUUID } from "node:crypto";
import type { NextFunction, Request, Response } from "express";
import { Router } from "express";
import multer from "multer";
import { importMappingSchema } from "@balanca/shared";
import {
  deleteAllPdfImportBatches,
  deleteImportBatch,
  deletePdfImportBatchGroupByPeriod,
  findImportBatch,
  listImportBatchEntries,
  listImportBatches,
  updateImportBatchFile
} from "../db.js";
import { env } from "../env.js";
import { badRequest } from "../errors.js";
import { requireRoles } from "../middleware/requireAuth.js";
import { commitImport, highlightCaneSummaryPdfDivergences, previewImport } from "../services/importer.js";
import { assertUploadedFile } from "../services/uploadValidation.js";

await fs.mkdir(env.uploadDir, { recursive: true });
await fs.mkdir(env.analysisArchiveDir, { recursive: true });

const upload = multer({
  dest: env.uploadDir,
  limits: {
    fileSize: 25 * 1024 * 1024
  }
});

export const importsRouter = Router();
const manageImportsOnly = requireRoles(["ADMIN", "ANALYST"]);

importsRouter.get("/batches", (req, res) => {
  const limit = typeof req.query.limit === "string" ? Number(req.query.limit) : 100;
  return res.json({ batches: listImportBatches(Number.isFinite(limit) ? limit : 100) });
});

importsRouter.delete("/pdf-batches", manageImportsOnly, async (_req, res) => {
  const deletedBatches = deleteAllPdfImportBatches();
  await removeArchivedBatchFiles(deletedBatches);

  return res.json({
    deletedBatches: deletedBatches.length,
    deletedRows: deletedBatches.reduce((total, batch) => total + batch.rowCount, 0)
  });
});

importsRouter.delete("/batch-groups", manageImportsOnly, async (req, res) => {
  const from = parseDateQuery(req.query.from);
  const to = parseDateQuery(req.query.to) ?? from;

  if (!from) {
    throw badRequest("Informe a data do grupo para excluir.");
  }

  const deletedBatches = deletePdfImportBatchGroupByPeriod(from, to ?? from);
  await removeArchivedBatchFiles(deletedBatches);

  return res.json({
    deletedBatches: deletedBatches.length,
    deletedRows: deletedBatches.reduce((total, batch) => total + batch.rowCount, 0)
  });
});

importsRouter.get("/batches/:batchId/entries", (req, res) => {
  const batch = findImportBatch(req.params.batchId);

  if (!batch) {
    throw badRequest("Analise nao encontrada.");
  }

  return res.json({ batch, entries: listImportBatchEntries(batch.id) });
});

importsRouter.get("/batches/:batchId/file", async (req, res) => {
  const batch = findImportBatch(req.params.batchId);

  if (!batch) {
    throw badRequest("Analise nao encontrada.");
  }

  if (!batch.storedFileName) {
    throw badRequest("O PDF original dessa analise ainda nao esta arquivado no sistema.");
  }

  const filePath = path.join(env.analysisArchiveDir, batch.storedFileName);
  await fs.access(filePath).catch(() => {
    throw badRequest("O PDF arquivado dessa analise nao foi encontrado no disco.");
  });

  return res.download(filePath, batch.fileName);
});

importsRouter.get("/batches/:batchId/highlighted-file", async (req, res) => {
  const batch = findImportBatch(req.params.batchId);

  if (!batch) {
    throw badRequest("Analise nao encontrada.");
  }

  if (!batch.storedFileName) {
    throw badRequest("O PDF original dessa analise ainda nao esta arquivado no sistema.");
  }

  const filePath = path.join(env.analysisArchiveDir, batch.storedFileName);
  await fs.access(filePath).catch(() => {
    throw badRequest("O PDF arquivado dessa analise nao foi encontrado no disco.");
  });

  const result = await highlightCaneSummaryPdfDivergences(filePath, batch.fileName);
  const fileName = buildHighlightedPdfFileName(batch.fileName);

  res.setHeader("Content-Type", "application/pdf");
  res.setHeader("Content-Disposition", `attachment; filename="${fileName}"`);
  return res.send(result.pdf);
});

importsRouter.delete("/batches/:batchId", manageImportsOnly, async (req, res) => {
  const batch = findImportBatch(routeParam(req.params.batchId));

  if (!batch) {
    throw badRequest("Analise nao encontrada.");
  }

  const archivedPath = batch.storedFileName ? path.join(env.analysisArchiveDir, batch.storedFileName) : null;
  const stagedPath = archivedPath ? `${archivedPath}.deleting-${randomUUID()}` : null;
  const staged = archivedPath && stagedPath ? await stageFileForDeletion(archivedPath, stagedPath) : false;

  try {
    deleteImportBatch(batch.id);
  } catch (error) {
    if (staged && archivedPath && stagedPath) {
      await fs.rename(stagedPath, archivedPath).catch(() => undefined);
    }
    throw error;
  }

  if (staged && stagedPath) {
    await fs.unlink(stagedPath).catch((error) => console.warn("Falha ao remover arquivo de analise excluido.", error));
  }

  return res.status(204).send();
});

importsRouter.post("/preview", manageImportsOnly, upload.single("file"), async (req, res, next) => {
  await handleUploadedFile(req, res, next, async () => {
    if (!req.file) {
      throw badRequest("Envie um arquivo.");
    }

    await assertUploadedFile(req.file, [".xlsx", ".csv", ".pdf", ".jpg", ".jpeg", ".png"], "Envie um arquivo suportado.");
    const mapping = parseMapping(req.body.mapping);
    const result = await previewImport(req.file.path, req.file.originalname, { mapping });

    return res.json(result);
  });
});

importsRouter.post("/", manageImportsOnly, upload.single("file"), async (req, res, next) => {
  await handleUploadedFile(req, res, next, async () => {
    if (!req.file) {
      throw badRequest("Envie um arquivo.");
    }

    const uploadInfo = await assertUploadedFile(
      req.file,
      [".xlsx", ".csv", ".pdf", ".jpg", ".jpeg", ".png"],
      "Envie um arquivo suportado."
    );
    const mapping = parseMapping(req.body.mapping);
    const expectedFileHash = readOptionalFileHash(req.body.previewHash);
    const result = await commitImport(req.file.path, req.file.originalname, req.user?.id, { mapping, expectedFileHash });
    let batch = result.batch;
    let archivedFilePath: string | null = null;

    if (result.batch) {
      try {
        const storedFileName = await archiveUploadedAnalysisFile(req.file, result.batch.id);
        archivedFilePath = path.join(env.analysisArchiveDir, storedFileName);
        batch = updateImportBatchFile({
          id: result.batch.id,
          storedFileName,
          mimeType: uploadInfo.mimeType,
          fileSize: req.file.size
        });
      } catch (error) {
        if (archivedFilePath) {
          await fs.unlink(archivedFilePath).catch(() => undefined);
        }
        deleteImportBatch(result.batch.id);
        throw error;
      }
    }

    return res.status(201).json({ ...result, batch });
  });
});

importsRouter.post("/highlight-divergences", manageImportsOnly, upload.single("file"), async (req, res, next) => {
  await handleUploadedFile(req, res, next, async () => {
    if (!req.file) {
      throw badRequest("Envie um PDF.");
    }

    await assertUploadedFile(req.file, [".pdf"], "Envie um PDF valido.");
    const result = await highlightCaneSummaryPdfDivergences(req.file.path, req.file.originalname);
    const fileName = buildHighlightedPdfFileName(req.file.originalname);

    res.setHeader("Content-Type", "application/pdf");
    res.setHeader("Content-Disposition", `attachment; filename="${fileName}"`);
    res.setHeader("X-Highlighted-Rows", String(result.highlightedRows));
    res.setHeader("X-Parsed-Rows", String(result.parsedRows));

    return res.send(result.pdf);
  });
});

function parseMapping(value: unknown) {
  if (!value) {
    return undefined;
  }

  let parsed: unknown;

  try {
    parsed = typeof value === "string" ? JSON.parse(value) : value;
  } catch {
    throw badRequest("Mapeamento de colunas invalido.");
  }

  const result = importMappingSchema.safeParse(parsed);

  if (!result.success) {
    throw badRequest("Mapeamento de colunas invalido.");
  }

  return result.data;
}

function readOptionalFileHash(value: unknown) {
  if (value === undefined || value === null || value === "") {
    return undefined;
  }

  if (typeof value !== "string" || !/^[a-f0-9]{64}$/i.test(value)) {
    throw badRequest("Identificador da previa invalido. Compare o arquivo novamente.");
  }

  return value.toLowerCase();
}

function parseDateQuery(value: unknown) {
  if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(value)) {
    return null;
  }

  return value;
}

async function removeArchivedBatchFiles(batches: Array<{ storedFileName?: string | null }>) {
  await Promise.all(
    batches
      .filter((batch) => batch.storedFileName)
      .map((batch) => fs.unlink(path.join(env.analysisArchiveDir, batch.storedFileName!)).catch(() => undefined))
  );
}

async function stageFileForDeletion(sourcePath: string, stagedPath: string) {
  try {
    await fs.rename(sourcePath, stagedPath);
    return true;
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") {
      return false;
    }
    throw error;
  }
}

function buildHighlightedPdfFileName(fileName: string) {
  const base = fileName.replace(/\.[^.]+$/, "") || "resumo-cana";
  return `${base}-divergencias-marcadas.pdf`.replace(/[^\w.-]+/g, "-");
}

function routeParam(value: string | string[]) {
  return Array.isArray(value) ? value[0] : value;
}

async function archiveUploadedAnalysisFile(file: Express.Multer.File, batchId: string) {
  const extension = path.extname(file.originalname).toLowerCase() || ".bin";
  const storedFileName = `${batchId}${extension}`;
  await fs.copyFile(file.path, path.join(env.analysisArchiveDir, storedFileName));
  return storedFileName;
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
