import fs from "node:fs/promises";
import path from "node:path";
import type { NextFunction, Request, Response } from "express";
import { Router } from "express";
import multer from "multer";
import { fleetMovementInputSchema, fleetMovementStatusInputSchema } from "@balanca/shared";
import {
  createFleetMovement,
  deleteFleetMovement,
  findFleetMovementById,
  listFleetMovements,
  updateFleetMovementStatus
} from "../db.js";
import { env } from "../env.js";
import { badRequest } from "../errors.js";
import { generateFleetReportPdf, previewFleetReport } from "../services/fleetReport.js";
import { assertUploadedFile } from "../services/uploadValidation.js";

await fs.mkdir(env.uploadDir, { recursive: true });

const upload = multer({
  dest: env.uploadDir,
  limits: {
    fileSize: 25 * 1024 * 1024
  }
});

export const fleetReportsRouter = Router();

fleetReportsRouter.get("/base/preview", async (_req, res, next) => {
  try {
    const base = await resolveFleetBaseFile();
    const preview = await previewFleetReport(base.filePath, base.fileName, listFleetMovements());
    return res.json(preview);
  } catch (error) {
    next(error);
  }
});

fleetReportsRouter.get("/base/pdf", async (_req, res, next) => {
  try {
    const base = await resolveFleetBaseFile();
    const pdf = await generateFleetReportPdf(base.filePath, base.fileName, listFleetMovements());
    const outputName = buildOutputName(base.fileName);

    res.setHeader("Content-Type", "application/pdf");
    res.setHeader("Content-Disposition", `attachment; filename="${outputName}"`);
    return res.send(pdf);
  } catch (error) {
    next(error);
  }
});

fleetReportsRouter.get("/movements", (_req, res) => {
  return res.json({ movements: listFleetMovements() });
});

fleetReportsRouter.post("/movements", (req, res) => {
  const input = fleetMovementInputSchema.safeParse(req.body);

  if (!input.success) {
    throw badRequest("Movimentacao de frota invalida.");
  }

  const movement = createFleetMovement(input.data);

  return res.status(201).json({ movement });
});

fleetReportsRouter.patch("/movements/:movementId/status", (req, res) => {
  const input = fleetMovementStatusInputSchema.safeParse(req.body);

  if (!input.success) {
    throw badRequest("Status de movimentacao invalido.");
  }

  const currentMovement = findFleetMovementById(req.params.movementId);

  if (!currentMovement) {
    return res.status(404).json({ message: "Movimentacao nao encontrada." });
  }

  const movement = updateFleetMovementStatus(currentMovement.id, input.data.status);

  return res.json({ movement });
});

fleetReportsRouter.delete("/movements/:movementId", (req, res) => {
  const currentMovement = findFleetMovementById(req.params.movementId);

  if (!currentMovement) {
    return res.status(404).json({ message: "Movimentacao nao encontrada." });
  }

  deleteFleetMovement(currentMovement.id);

  return res.status(204).send();
});

fleetReportsRouter.post("/preview", upload.single("file"), async (req, res, next) => {
  await handleUploadedFile(req, res, next, async () => {
    if (!req.file) {
      throw badRequest("Envie a planilha de frotas.");
    }

    await assertUploadedFile(req.file, [".xlsx"], "Envie uma planilha .xlsx valida.");
    const preview = await previewFleetReport(req.file.path, req.file.originalname, listFleetMovements());
    return res.json(preview);
  });
});

fleetReportsRouter.post("/pdf", upload.single("file"), async (req, res, next) => {
  await handleUploadedFile(req, res, next, async () => {
    if (!req.file) {
      throw badRequest("Envie a planilha de frotas.");
    }

    await assertUploadedFile(req.file, [".xlsx"], "Envie uma planilha .xlsx valida.");
    const pdf = await generateFleetReportPdf(req.file.path, req.file.originalname, listFleetMovements());
    const outputName = buildOutputName(req.file.originalname);

    res.setHeader("Content-Type", "application/pdf");
    res.setHeader("Content-Disposition", `attachment; filename="${outputName}"`);
    return res.send(pdf);
  });
});

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

async function resolveFleetBaseFile() {
  try {
    await fs.access(env.fleetBaseFile);
  } catch {
    throw badRequest(`Base de frotas nao encontrada em ${env.fleetBaseFile}.`);
  }

  return {
    filePath: env.fleetBaseFile,
    fileName: path.basename(env.fleetBaseFile)
  };
}

function buildOutputName(fileName: string) {
  const base = fileName.replace(/\.[^.]+$/, "") || "frotas";
  return `${base}-relatorio-frotas.pdf`;
}
