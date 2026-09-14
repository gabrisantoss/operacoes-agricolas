import { Router } from "express";
import type { PostHarvestIntegrationEventStatus } from "../repositories/postHarvestIntegrationRepository.js";
import {
  countPostHarvestIntegrationEvents,
  listPostHarvestIntegrationEvents,
  summarizePostHarvestIntegrationEvents
} from "../db.js";
import { requireRoles } from "../middleware/requireAuth.js";
import {
  dispatchPendingPostHarvestEvents,
  dispatchPostHarvestEventById,
  getPostHarvestConnectionInfo
} from "../services/postHarvestIntegrationService.js";
import {
  buildPostHarvestExportWorkbook,
  readPostHarvestExportData
} from "../services/postHarvestExcelExport.js";
import { buildPostHarvestExportPdf } from "../services/postHarvestPdfExport.js";
import { assertExportRowLimit, MAX_EXPORT_ROWS } from "../services/exportControl.js";

export const postHarvestIntegrationsRouter = Router();

const adminOnly = requireRoles(["ADMIN"]);
const fullAccessOnly = requireRoles(["ADMIN", "ANALYST"]);

postHarvestIntegrationsRouter.get("/", fullAccessOnly, async (req, res) => {
  const status = parseStatus(req.query.status);
  const limit = parseInteger(req.query.limit, 100);
  const offset = parseInteger(req.query.offset, 0);
  const events = listPostHarvestIntegrationEvents({ status, limit, offset });
  const total = countPostHarvestIntegrationEvents(status);

  return res.json({
    events,
    total,
    limit,
    offset,
    summary: summarizePostHarvestIntegrationEvents(),
    connection: getPostHarvestConnectionInfo()
  });
});

postHarvestIntegrationsRouter.get("/connection", fullAccessOnly, async (_req, res) => {
  return res.json({ connection: getPostHarvestConnectionInfo() });
});

postHarvestIntegrationsRouter.get("/export-summary", fullAccessOnly, async (_req, res) => {
  const data = readPostHarvestExportData();

  return res.json({
    ...data.summary,
    issues: data.issues.slice(0, 50)
  });
});

postHarvestIntegrationsRouter.get("/export.xlsx", fullAccessOnly, async (_req, res) => {
  const data = readPostHarvestExportData(MAX_EXPORT_ROWS + 1);
  assertExportRowLimit(data.summary.rowCount);

  if (data.summary.rowCount === 0) {
    return res.status(409).json({ message: "Nenhuma OS fechada disponivel para exportacao." });
  }

  if (data.issues.length > 0) {
    const detail = data.issues
      .slice(0, 5)
      .map((issue) => `OS ${issue.orderNumber}: ${issue.message}`)
      .join(" ");

    return res.status(422).json({
      message: `Excel nao gerado. Existem ${data.issues.length} registro(s) invalido(s). ${detail}`,
      issues: data.issues.slice(0, 50)
    });
  }

  const workbook = buildPostHarvestExportWorkbook(data.rows);
  const buffer = await workbook.xlsx.writeBuffer();
  const fileName = `integracao-pos-colheita-${new Date().toISOString().slice(0, 10)}.xlsx`;

  res.setHeader("Content-Type", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet");
  res.setHeader("Content-Disposition", `attachment; filename="${fileName}"`);
  return res.send(buffer);
});

postHarvestIntegrationsRouter.get("/export.pdf", fullAccessOnly, async (_req, res) => {
  const data = readPostHarvestExportData(MAX_EXPORT_ROWS + 1);
  assertExportRowLimit(data.summary.rowCount);

  if (data.summary.rowCount === 0) {
    return res.status(409).json({ message: "Nenhuma OS fechada disponivel para exportacao." });
  }

  try {
    const buffer = await buildPostHarvestExportPdf(data);
    const fileName = `integracao-pos-colheita-${new Date().toISOString().slice(0, 10)}.pdf`;

    res.setHeader("Content-Type", "application/pdf");
    res.setHeader("Content-Disposition", `attachment; filename="${fileName}"`);
    return res.send(buffer);
  } catch (error) {
    return res.status(500).json({ message: "Erro ao gerar PDF", details: String(error) });
  }
});

postHarvestIntegrationsRouter.post("/send-pending", adminOnly, async (req, res) => {
  const limit = parseInteger(req.body?.limit, 50);
  const results = await dispatchPendingPostHarvestEvents(limit);

  return res.json({
    results,
    summary: {
      total: results.length,
      sent: results.filter((result) => result.sent).length,
      skipped: results.filter((result) => result.skipped).length,
      error: results.filter((result) => !result.sent && !result.skipped).length
    }
  });
});

postHarvestIntegrationsRouter.post("/:eventId/send", adminOnly, async (req, res) => {
  const result = await dispatchPostHarvestEventById(String(req.params.eventId ?? ""));

  if (!result.event && result.skipped) {
    return res.status(404).json({ message: result.reason ?? "Evento nao encontrado." });
  }

  return res.json({ result });
});

function parseStatus(value: unknown): PostHarvestIntegrationEventStatus | undefined {
  if (value === "PENDING" || value === "PROCESSING" || value === "SENT" || value === "ERROR" || value === "DEAD") {
    return value;
  }

  return undefined;
}

function parseInteger(value: unknown, fallback: number) {
  const raw = Array.isArray(value) ? value[0] : value;
  const parsed = Number(raw);

  return Number.isFinite(parsed) ? Math.trunc(parsed) : fallback;
}
