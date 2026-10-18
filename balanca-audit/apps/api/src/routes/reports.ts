import { Router } from "express";
import { caneReportFilterSchema, type CaneReportFilterInput } from "@balanca/shared";
import { listCaneReportRows, listFarms } from "../db.js";
import { badRequest } from "../errors.js";
import { buildCaneReport } from "../services/caneReport.js";
import { renderCaneReportPdf } from "../services/caneReportPdf.js";
import {
  assertExportRowLimit,
  exportCacheKey,
  exportController,
  exportRequestIdentity
} from "../services/exportControl.js";

export const reportsRouter = Router();

reportsRouter.get("/cane/options", (_req, res) => {
  const farms = listFarms().map((farm) => ({
    id: farm.id,
    code: farm.code ?? null,
    name: farm.name,
    fields: farm.fields
      .map((field) => ({ id: field.id, code: field.code, name: field.name ?? null }))
      .sort((left, right) => left.code.localeCompare(right.code, "pt-BR", { numeric: true }))
  }));

  return res.json({ farms });
});

reportsRouter.get("/cane/preview", (req, res) => {
  return res.json(loadCaneReport(parseFilters(req.query)));
});

reportsRouter.get("/cane.pdf", async (req, res) => {
  const filters = parseFilters(req.query);
  const exported = await exportController.run({
    requestKey: exportRequestIdentity({ userId: req.user?.id, ip: req.ip }),
    cacheKey: exportCacheKey("reports:cane.pdf", filters, req.user?.id),
    producer: () => renderCaneReportPdf(loadCaneReport(filters))
  });
  const fileName = filters.type === "DETAILED" ? "relatorio-safra-detalhado.pdf" : "relatorio-safra-geral.pdf";

  res.setHeader("Content-Type", "application/pdf");
  res.setHeader("Content-Disposition", `attachment; filename="${fileName}"`);
  res.setHeader("X-Export-Cache", exported.cache);
  return res.send(exported.value);
});

// Preview and PDF share this single path: same query, same calculation.
export function loadCaneReport(filters: CaneReportFilterInput) {
  const rows = listCaneReportRows(filters);
  assertExportRowLimit(rows.length);
  return buildCaneReport(rows, filters, describeFilters(filters));
}

function describeFilters(filters: CaneReportFilterInput) {
  if (!filters.farmId && !filters.fieldId) {
    return {};
  }

  const farms = listFarms();
  const farm = farms.find((item) => item.id === filters.farmId);
  const field = farms.flatMap((item) => item.fields).find((item) => item.id === filters.fieldId);

  if (filters.farmId && !farm) {
    throw badRequest("Fazenda nao encontrada.");
  }

  if (filters.fieldId && (!field || (filters.farmId && field.farmId !== filters.farmId))) {
    throw badRequest("Talhao nao encontrado para a fazenda selecionada.");
  }

  return {
    farmLabel: farm ? `${farm.code ? `${farm.code} - ` : ""}${farm.name}` : undefined,
    fieldLabel: field ? `${field.code}${field.name ? ` - ${field.name}` : ""}` : undefined
  };
}

function parseFilters(query: Record<string, unknown>) {
  const normalized = Object.fromEntries(
    Object.entries(query).map(([key, value]) => [key, Array.isArray(value) ? value[0] : value])
  );
  const parsed = caneReportFilterSchema.safeParse(normalized);

  if (!parsed.success) {
    throw badRequest(parsed.error.issues[0]?.message === "A data inicial deve ser anterior ou igual a data final."
      ? parsed.error.issues[0].message
      : "Filtros invalidos.");
  }

  return parsed.data;
}
