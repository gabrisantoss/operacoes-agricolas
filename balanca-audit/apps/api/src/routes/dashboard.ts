import { Router, type Request } from "express";
import PDFDocument from "pdfkit";
import type { DashboardFilterInput, EntryStatus } from "@balanca/shared";
import { dashboardFilterSchema, systemIdentity } from "@balanca/shared";
import { getDashboardSummary, getFieldProductionDashboard, getHarvestExecutiveDashboard, listDivergencesForExport } from "../db.js";
import { badRequest } from "../errors.js";
import { toSemicolonCsv } from "../services/csvExport.js";
import { fitPdfSingleLine } from "../services/pdfTextLayout.js";
import {
  assertExportRowLimit,
  exportCacheKey,
  exportController,
  exportRequestIdentity,
  MAX_EXPORT_ROWS
} from "../services/exportControl.js";

export const dashboardRouter = Router();

dashboardRouter.get("/summary", async (req, res) => {
  const filters = parseFilters(req.query);
  return res.json(getDashboardSummary(filters));
});

dashboardRouter.get("/production", async (req, res) => {
  const filters = parseFilters(req.query);
  return res.json(getFieldProductionDashboard(filters));
});

dashboardRouter.get("/harvest", async (req, res) => {
  const filters = parseFilters(req.query);
  return res.json(getHarvestExecutiveDashboard(filters));
});

dashboardRouter.get("/harvest-report.pdf", async (req, res) => {
  const filters = parseFilters(req.query);
  const exported = await runDashboardExport(req, "harvest-report.pdf", filters, async () => {
    const production = getFieldProductionDashboard(filters);
    assertExportRowLimit(production.rows.length);
    const harvest = getHarvestExecutiveDashboard(filters, production);
    return toHarvestReportPdf(filters, harvest, production.periods);
  });

  res.setHeader("Content-Type", "application/pdf");
  res.setHeader("Content-Disposition", 'attachment; filename="relatorio-fechamento-safra.pdf"');
  res.setHeader("X-Export-Cache", exported.cache);
  return res.send(exported.value);
});

dashboardRouter.get("/divergences.csv", async (req, res) => {
  const filters = parseFilters(req.query);
  const exported = await runDashboardExport(req, "divergences.csv", filters, () => {
    const rows = listDivergencesForExport(filters, MAX_EXPORT_ROWS + 1);
    assertExportRowLimit(rows.length);
    return toCsv(rows);
  });

  res.setHeader("Content-Type", "text/csv; charset=utf-8");
  res.setHeader("Content-Disposition", 'attachment; filename="divergencias-talhoes.csv"');
  res.setHeader("X-Export-Cache", exported.cache);
  return res.send(exported.value);
});

dashboardRouter.get("/divergences-report.pdf", async (req, res) => {
  const filters = parseFilters(req.query);
  const exported = await runDashboardExport(req, "divergences-report.pdf", filters, async () => {
    const summary = getDashboardSummary(filters);
    const rows = listDivergencesForExport(filters, MAX_EXPORT_ROWS + 1);
    assertExportRowLimit(rows.length);
    return toDivergenceReportPdf(filters, summary, rows);
  });

  res.setHeader("Content-Type", "application/pdf");
  res.setHeader("Content-Disposition", 'attachment; filename="relatorio-divergencias-talhoes.pdf"');
  res.setHeader("X-Export-Cache", exported.cache);
  return res.send(exported.value);
});

dashboardRouter.get("/divergences-report-total.pdf", async (req, res) => {
  const filters = parseFilters(req.query);
  const exported = await runDashboardExport(req, "divergences-report-total.pdf", filters, async () => {
    const summary = getDashboardSummary(filters);
    const rows = listDivergencesForExport(filters, MAX_EXPORT_ROWS + 1);
    assertExportRowLimit(rows.length);
    return toTotalDivergenceReportPdf(filters, summary, rows);
  });

  res.setHeader("Content-Type", "application/pdf");
  res.setHeader("Content-Disposition", 'attachment; filename="relatorio-divergencias-total.pdf"');
  res.setHeader("X-Export-Cache", exported.cache);
  return res.send(exported.value);
});

function runDashboardExport<T>(
  req: Request,
  namespace: string,
  filters: DashboardFilterInput,
  producer: () => Promise<T> | T
) {
  return exportController.run({
    requestKey: exportRequestIdentity({ userId: req.user?.id, ip: req.ip }),
    cacheKey: exportCacheKey(`dashboard:${namespace}`, filters, req.user?.id),
    producer
  });
}

function parseFilters(query: Record<string, unknown>) {
  const normalized = Object.fromEntries(
    Object.entries(query)
      .map(([key, value]) => [key, Array.isArray(value) ? value[0] : value])
      .filter((entry): entry is [string, string] => typeof entry[1] === "string" && entry[1].trim().length > 0)
  );
  const parsed = dashboardFilterSchema.safeParse(normalized);

  if (!parsed.success) {
    throw badRequest("Filtros invalidos.");
  }

  return parsed.data;
}

function toCsv(rows: ReturnType<typeof listDivergencesForExport>) {
  const headers = [
    "Arquivo",
    "Importado em",
    "Periodo inicial",
    "Periodo final",
    "Data relatorio",
    "Data entrada",
    "Nota",
    "Codigo fazenda",
    "Fazenda",
    "Talhao",
    "Colheita",
    "Placa",
    "Peso bruto",
    "Peso liquido",
    "Area ha",
    "Area alq",
    "Status",
    "Observacao"
  ];
  const values = rows.map((row) => [
    row.fileName,
    row.importedAt,
    row.periodStart,
    row.periodEnd,
    row.reportDate,
    row.entryDate,
    row.ticketNumber,
    row.farmCode,
    row.farmNameRaw,
    row.fieldCodeRaw,
    row.orderNumberRaw,
    row.vehiclePlate,
    row.grossWeight,
    row.netWeight,
    row.fieldAreaHa,
    row.fieldAreaAlq,
    row.status,
    row.notes
  ]);

  return toSemicolonCsv([headers, ...values]);
}

async function toDivergenceReportPdf(
  filters: DashboardFilterInput,
  summary: ReturnType<typeof getDashboardSummary>,
  rows: ReturnType<typeof listDivergencesForExport>
) {
  const doc = new PDFDocument({
    size: "A4",
    layout: "landscape",
    margin: 30,
    info: {
      Title: "Relatório de Divergências de Talhões",
      Author: systemIdentity.currentName
    }
  });
  const chunks: Buffer[] = [];
  const done = new Promise<Buffer>((resolve, reject) => {
    doc.on("data", (chunk: Buffer) => chunks.push(Buffer.from(chunk)));
    doc.on("end", () => resolve(Buffer.concat(chunks)));
    doc.on("error", reject);
  });

  drawReportHeader(doc, filters, summary);
  drawAreaSummary(doc, summary);
  drawDivergenceRows(doc, rows);
  doc.end();

  return done;
}

async function toTotalDivergenceReportPdf(
  filters: DashboardFilterInput,
  summary: ReturnType<typeof getDashboardSummary>,
  rows: ReturnType<typeof listDivergencesForExport>
) {
  const doc = new PDFDocument({
    size: "A4",
    layout: "landscape",
    margin: 30,
    info: {
      Title: "Relatório Total de Divergências por Fazenda",
      Author: systemIdentity.currentName
    }
  });
  const chunks: Buffer[] = [];
  const done = new Promise<Buffer>((resolve, reject) => {
    doc.on("data", (chunk: Buffer) => chunks.push(Buffer.from(chunk)));
    doc.on("end", () => resolve(Buffer.concat(chunks)));
    doc.on("error", reject);
  });

  drawReportHeader(doc, filters, summary);
  drawAreaSummary(doc, summary);
  drawDivergenceRowsByFarm(doc, rows);
  doc.end();

  return done;
}

async function toHarvestReportPdf(
  filters: DashboardFilterInput,
  harvest: ReturnType<typeof getHarvestExecutiveDashboard>,
  periods: ReturnType<typeof getFieldProductionDashboard>["periods"]
) {
  const doc = new PDFDocument({
    size: "A4",
    layout: "landscape",
    margin: 30,
    bufferPages: true,
    info: {
      Title: "Relatório de Fechamento da Safra",
      Author: systemIdentity.currentName
    }
  });
  const chunks: Buffer[] = [];
  const done = new Promise<Buffer>((resolve, reject) => {
    doc.on("data", (chunk: Buffer) => chunks.push(Buffer.from(chunk)));
    doc.on("end", () => resolve(Buffer.concat(chunks)));
    doc.on("error", reject);
  });

  drawHarvestCover(doc, filters, harvest);
  drawHarvestCharts(doc, harvest, periods);
  doc.addPage();
  drawHarvestRankings(doc, harvest);
  doc.end();

  return done;
}

function drawHarvestCover(
  doc: PDFKit.PDFDocument,
  filters: DashboardFilterInput,
  harvest: ReturnType<typeof getHarvestExecutiveDashboard>
) {
  doc.font("Helvetica-Bold").fontSize(19).fillColor(reportColors.text).text("Relatório de Fechamento da Safra", 30, 28);
  doc
    .font("Helvetica")
    .fontSize(8)
    .fillColor(reportColors.muted)
    .text(`Operacoes Agricolas | Gerado em ${formatDateTime(new Date().toISOString())}`, 30, 52);

  const period = formatOptionalPeriod(harvest.periodStart, harvest.periodEnd);
  const activeFilters = [
    filters.year ? `Safra: ${filters.year}` : undefined,
    period ? `Período da base: ${period}` : "Período da base: sem data",
    filters.fileName ? `Arquivo: ${filters.fileName}` : undefined,
    filters.order ? `OS: ${filters.order}` : undefined
  ].filter(Boolean);

  doc.font("Helvetica").fontSize(8).fillColor(reportColors.muted).text(activeFilters.join(" | "), 30, 66, { width: 780 });
  doc
    .roundedRect(30, 86, 780, 58, 6)
    .fillAndStroke("#f8fafb", reportColors.border);
  doc
    .font("Helvetica-Bold")
    .fontSize(10)
    .fillColor(reportColors.text)
    .text("Leitura executiva", 44, 98);
  doc
    .font("Helvetica")
    .fontSize(8.5)
    .fillColor(reportColors.muted)
    .text(
      "Este é o primeiro ano de base consolidada de colheita no sistema. Por isso, o relatório apresenta a safra atual e seus indicadores acumulados, sem comparação histórica. A classificação de cana própria e fornecedor segue a regra operacional: fazendas 1xx como cana própria e 2xx como fornecedor.",
      44,
      114,
      { width: 750, lineGap: 2 }
    );

  const cards = [
    ["Cana própria", `${formatNumber(harvest.totals.ownPercentage)}%`],
    ["Cana entregue", `${formatNumber(harvest.totals.totalNetWeight)} t`],
    ["TCH (estimado)*", `${formatNumber(harvest.totals.tch)} t/ha`],
    ["TCA (estimado)*", `${formatNumber(harvest.totals.tca)} t/alq`],
    ["Área cadastrada vinculada", `${formatNumber(harvest.totals.areaAlq)} alq`],
    ["Fornecedor", `${formatNumber(harvest.totals.supplierNetWeight)} t`],
    ["Fazendas observadas", String(harvest.totals.farms)],
    ["Talhões observados", String(harvest.totals.fields)]
  ] as const;

  drawHarvestMetricCards(doc, cards, 30, 164);
  doc
    .font("Helvetica")
    .fontSize(7)
    .fillColor(reportColors.muted)
    .text(
      `* TCH/TCA usam todo o peso recebido dividido pela área cadastrada vinculada. Cobertura: ${formatNumber(harvest.totals.areaCoveragePercentage)}% do peso; ${formatNumber(harvest.totals.netWeightWithoutArea)} t sem área (${harvest.totals.entriesWithoutArea} entradas em ${harvest.totals.fieldsWithoutArea} talhões).`,
      30,
      304,
      { width: 780 }
    );
}

function drawHarvestCharts(
  doc: PDFKit.PDFDocument,
  harvest: ReturnType<typeof getHarvestExecutiveDashboard>,
  periods: ReturnType<typeof getFieldProductionDashboard>["periods"]
) {
  doc.y = 324;
  const chartY = doc.y;
  drawOwnershipChart(doc, harvest, 30, chartY, 365, 168);
  drawPeriodChart(doc, periods, 420, chartY, 390, 168);
}

function drawHarvestRankings(doc: PDFKit.PDFDocument, harvest: ReturnType<typeof getHarvestExecutiveDashboard>) {
  doc.font("Helvetica-Bold").fontSize(15).fillColor(reportColors.text).text("Rankings da safra", 30, 30);
  doc
    .font("Helvetica")
    .fontSize(8)
    .fillColor(reportColors.muted)
    .text("Ranking por peso líquido acumulado nos PDFs de colheita importados.", 30, 50);

  drawTopFarmsChart(doc, harvest, 30, 78, 360, 190);
  drawTopFieldsTable(doc, harvest, 420, 78, 390);
  drawTopFarmsTable(doc, harvest, 30, 294);
}

function drawHarvestMetricCards(doc: PDFKit.PDFDocument, cards: readonly (readonly [string, string])[], x: number, y: number) {
  const width = 185;
  const height = 58;
  const gap = 12;

  cards.forEach(([label, value], index) => {
    const col = index % 4;
    const row = Math.floor(index / 4);
    const cardX = x + col * (width + gap);
    const cardY = y + row * (height + gap);

    doc.roundedRect(cardX, cardY, width, height, 6).fillAndStroke(index === 0 ? "#eef7f1" : "#f8fafb", reportColors.border);
    doc.font("Helvetica-Bold").fontSize(8).fillColor(reportColors.muted).text(label, cardX + 10, cardY + 10, { width: width - 20 });
    doc.font("Helvetica-Bold").fontSize(14).fillColor(index === 0 ? reportColors.green : reportColors.text).text(value, cardX + 10, cardY + 30, {
      width: width - 20,
      ellipsis: true
    });
  });
}

function drawOwnershipChart(doc: PDFKit.PDFDocument, harvest: ReturnType<typeof getHarvestExecutiveDashboard>, x: number, y: number, width: number, height: number) {
  drawChartFrame(doc, "Composição da cana", x, y, width, height);
  let cursorY = y + 36;

  for (const item of harvest.ownership) {
    const barWidth = Math.max(2, (width - 132) * (item.percentage / 100));
    const color = item.type === "OWN" ? reportColors.green : item.type === "SUPPLIER" ? "#f07812" : reportColors.muted;

    doc.font("Helvetica-Bold").fontSize(8).fillColor(reportColors.text).text(item.label, x + 12, cursorY, { width: 92 });
    doc.roundedRect(x + 112, cursorY + 1, width - 132, 9, 5).fill("#e8edf2");
    doc.roundedRect(x + 112, cursorY + 1, barWidth, 9, 5).fill(color);
    doc
      .font("Helvetica-Bold")
      .fontSize(8)
      .fillColor(reportColors.text)
      .text(`${formatNumber(item.percentage)}%`, x + width - 70, cursorY - 1, { width: 56, align: "right" });
    doc
      .font("Helvetica")
      .fontSize(7)
      .fillColor(reportColors.muted)
      .text(`${formatNumber(item.totalNetWeight)} t | ${item.farmCount} fazendas`, x + 112, cursorY + 15, { width: width - 124 });
    cursorY += 42;
  }
}

function drawPeriodChart(
  doc: PDFKit.PDFDocument,
  periods: ReturnType<typeof getFieldProductionDashboard>["periods"],
  x: number,
  y: number,
  width: number,
  height: number
) {
  drawChartFrame(doc, "Evolução por período", x, y, width, height);
  const visible = periods.slice(-10);
  const max = Math.max(1, ...visible.map((period) => period.totalNetWeight));
  const chartX = x + 24;
  const chartY = y + 38;
  const chartWidth = width - 48;
  const chartHeight = height - 78;
  const barGap = 5;
  const barWidth = visible.length > 0 ? Math.max(10, (chartWidth - barGap * (visible.length - 1)) / visible.length) : 10;

  if (visible.length === 0) {
    doc.font("Helvetica").fontSize(8).fillColor(reportColors.muted).text("Sem períodos importados.", chartX, chartY);
    return;
  }

  doc.moveTo(chartX, chartY + chartHeight).lineTo(chartX + chartWidth, chartY + chartHeight).stroke(reportColors.border);

  visible.forEach((period, index) => {
    const valueHeight = Math.max(2, chartHeight * (period.totalNetWeight / max));
    const barX = chartX + index * (barWidth + barGap);
    const barY = chartY + chartHeight - valueHeight;
    const label = formatPeriodShort(period.periodStart, period.periodEnd);

    doc.rect(barX, barY, barWidth, valueHeight).fill(index % 2 === 0 ? "#245b8f" : "#2f9f78");
    doc
      .font("Helvetica")
      .fontSize(6)
      .fillColor(reportColors.muted)
      .text(label, barX - 4, chartY + chartHeight + 6, { width: barWidth + 8, align: "center" });
  });

  doc
    .font("Helvetica")
    .fontSize(7)
    .fillColor(reportColors.muted)
    .text(`Maior período: ${formatNumber(max)} t`, x + 12, y + height - 24, { width: width - 24 });
}

function drawTopFarmsChart(doc: PDFKit.PDFDocument, harvest: ReturnType<typeof getHarvestExecutiveDashboard>, x: number, y: number, width: number, height: number) {
  drawChartFrame(doc, "Fazendas com mais cana", x, y, width, height);
  const rows = harvest.topFarms.slice(0, 8);
  const max = Math.max(1, ...rows.map((row) => row.totalNetWeight));
  let cursorY = y + 34;

  for (const row of rows) {
    const barWidth = Math.max(2, (width - 174) * (row.totalNetWeight / max));
    const label = `${row.farmCode ?? "-"} ${row.farmName}`.slice(0, 34);

    doc.font("Helvetica").fontSize(7).fillColor(reportColors.text);
    doc.text(fitPdfSingleLine(doc, label, 118), x + 12, cursorY - 1, { lineBreak: false });
    doc.roundedRect(x + 140, cursorY, width - 174, 8, 4).fill("#e8edf2");
    doc.roundedRect(x + 140, cursorY, barWidth, 8, 4).fill("#2f9f78");
    doc.font("Helvetica-Bold").fontSize(7).fillColor(reportColors.text).text(formatNumber(row.totalNetWeight), x + width - 46, cursorY - 1, {
      width: 34,
      align: "right"
    });
    cursorY += 18;
  }
}

function drawTopFieldsTable(doc: PDFKit.PDFDocument, harvest: ReturnType<typeof getHarvestExecutiveDashboard>, x: number, y: number, width: number) {
  drawChartFrame(doc, "Talhões com mais cana", x, y, width, 190);
  const rows = harvest.topFields.slice(0, 8);
  const headers = ["Fazenda", "Talhão", "Toneladas", "TCH*"];
  const widths = [130, 54, 82, 64];
  let cursorY = y + 34;

  drawMiniTableHeader(doc, headers, widths, x + 12, cursorY);
  cursorY += 18;

  for (const row of rows) {
    drawMiniTableRow(
      doc,
      [`${row.farmCode ?? "-"} ${row.farmName}`, row.fieldCode, formatNumber(row.totalNetWeight), formatNumber(row.tch)],
      widths,
      x + 12,
      cursorY
    );
    cursorY += 18;
  }
}

function drawTopFarmsTable(doc: PDFKit.PDFDocument, harvest: ReturnType<typeof getHarvestExecutiveDashboard>, x: number, y: number) {
  doc.font("Helvetica-Bold").fontSize(11).fillColor(reportColors.text).text("Resumo das principais fazendas", x, y);
  doc.y = y + 18;
  drawTableHeader(doc, ["Fazenda", "Talhões", "Toneladas", "Alqueires", "TCH*", "% safra"], [260, 70, 110, 90, 80, 80]);

  for (const row of harvest.topFarms.slice(0, 12)) {
    drawSimpleRow(
      doc,
      [
        `${row.farmCode ?? "-"} - ${row.farmName}`,
        String(row.fieldCount),
        formatNumber(row.totalNetWeight),
        formatNumber(row.areaAlq),
        formatNumber(row.tch),
        `${formatNumber(row.percentage)}%`
      ],
      [260, 70, 110, 90, 80, 80]
    );
  }
}

function drawChartFrame(doc: PDFKit.PDFDocument, title: string, x: number, y: number, width: number, height: number) {
  doc.roundedRect(x, y, width, height, 6).fillAndStroke("#ffffff", reportColors.border);
  doc.font("Helvetica-Bold").fontSize(10).fillColor(reportColors.text).text(title, x + 12, y + 12, { width: width - 24 });
}

function drawMiniTableHeader(doc: PDFKit.PDFDocument, labels: string[], widths: number[], x: number, y: number) {
  let cursor = x;
  doc.font("Helvetica-Bold").fontSize(7).fillColor(reportColors.muted);

  labels.forEach((label, index) => {
    doc.text(label, cursor, y, { width: widths[index], ellipsis: true });
    cursor += widths[index];
  });
}

function drawMiniTableRow(doc: PDFKit.PDFDocument, values: string[], widths: number[], x: number, y: number) {
  let cursor = x;
  doc.font("Helvetica").fontSize(7).fillColor(reportColors.text);

  values.forEach((value, index) => {
    doc.text(fitPdfSingleLine(doc, value, widths[index] - 4), cursor, y, { lineBreak: false });
    cursor += widths[index];
  });
}

function drawPageNumbers(doc: PDFKit.PDFDocument) {
  const range = doc.bufferedPageRange();

  for (let index = range.start; index < range.start + range.count; index += 1) {
    doc.switchToPage(index);
    doc
      .font("Helvetica")
      .fontSize(7)
      .fillColor(reportColors.muted)
      .text(`Página ${index + 1} de ${range.count}`, 30, doc.page.height - 22, { width: doc.page.width - 60, align: "right" });
  }
}

const statusLabels: Record<EntryStatus, string> = {
  OK: "Correto",
  OS_NOT_FOUND: "OS não encontrada",
  FARM_NOT_FOUND: "Fazenda não encontrada",
  FIELD_NOT_FOUND: "Talhão não cadastrado",
  FARM_MISMATCH: "Fazenda diferente da OS",
  FIELD_NOT_RELEASED: "Talhão fora da colheita atual",
  MISSING_DATA: "Dados incompletos"
};

const reportColors = {
  text: "#17202a",
  muted: "#647183",
  border: "#dce2e8",
  header: "#f3f6f8",
  danger: "#9b1c1c",
  green: "#26734d"
};

function drawReportHeader(doc: PDFKit.PDFDocument, filters: DashboardFilterInput, summary: ReturnType<typeof getDashboardSummary>) {
  doc.font("Helvetica-Bold").fontSize(17).fillColor(reportColors.text).text("Relatório de divergências de talhões", 30, 28);
  doc
    .font("Helvetica")
    .fontSize(8)
    .fillColor(reportColors.muted)
    .text(`Gerado em ${formatDateTime(new Date().toISOString())}`, 30, 50);

  const activeFilters = [
    filters.fileName ? `Arquivo: ${filters.fileName}` : undefined,
    filters.from ? `De: ${formatDateOnly(filters.from)}` : undefined,
    filters.to ? `Até: ${formatDateOnly(filters.to)}` : undefined,
    filters.order ? `OS: ${filters.order}` : undefined,
    filters.status ? `Status: ${statusLabels[filters.status]}` : undefined
  ].filter(Boolean);

  doc
    .font("Helvetica")
    .fontSize(8)
    .fillColor(reportColors.muted)
    .text(activeFilters.length ? activeFilters.join(" | ") : "Filtros: todos os registros", 30, 64, { width: 780 });

  const cards = [
    ["Linhas", summary.totalEntries],
    ["Corretas", summary.okEntries],
    ["Divergentes", summary.divergentEntries],
    ["Alqueires", formatNumber(summary.areaAlq)],
    ["Alq divergente", formatNumber(summary.areaByDate.reduce((total, item) => total + item.divergentAreaAlq, 0))]
  ] as const;
  const width = 150;
  const top = 84;

  cards.forEach(([label, value], index) => {
    const x = 30 + index * 156;
    doc.roundedRect(x, top, width, 46, 5).fillAndStroke(index === 2 ? "#fff5f5" : "#f8fafb", reportColors.border);
    doc.font("Helvetica").fontSize(8).fillColor(reportColors.muted).text(label, x + 10, top + 9, { width: width - 20 });
    doc.font("Helvetica-Bold").fontSize(14).fillColor(index === 2 ? reportColors.danger : reportColors.text).text(String(value), x + 10, top + 24, { width: width - 20 });
  });

  doc.y = 150;
}

function drawAreaSummary(doc: PDFKit.PDFDocument, summary: ReturnType<typeof getDashboardSummary>) {
  ensureSpace(doc, 70);
  doc.font("Helvetica-Bold").fontSize(11).fillColor(reportColors.text).text("Alqueires por data", 30, doc.y);
  doc.y += 8;

  drawTableHeader(doc, ["Data PDF", "Talhões", "Alq no dia", "Alq acumulado", "Alq divergente"], [90, 70, 100, 110, 120]);

  if (summary.areaByDate.length === 0) {
    drawSimpleRow(doc, ["Sem áreas encontradas nos filtros atuais."], [490]);
    doc.y += 10;
    return;
  }

  for (const item of summary.areaByDate) {
    drawSimpleRow(
      doc,
      [
        formatDateOnly(item.date),
        String(item.fieldCount),
        formatNumber(item.areaAlq),
        formatNumber(item.cumulativeAreaAlq),
        formatNumber(item.divergentAreaAlq)
      ],
      [90, 70, 100, 110, 120]
    );
  }

  doc.y += 12;
}

function drawDivergenceRows(doc: PDFKit.PDFDocument, rows: ReturnType<typeof listDivergencesForExport>) {
  ensureSpace(doc, 70);
  doc.font("Helvetica-Bold").fontSize(11).fillColor(reportColors.text).text("Divergências por data", 30, doc.y);
  doc.y += 8;

  if (rows.length === 0) {
    drawSimpleRow(doc, ["Nenhuma divergência encontrada nos filtros atuais."], [780]);
    return;
  }

  for (const group of groupDivergenceRowsByPeriod(rows)) {
    ensureSpace(doc, 76);
    doc
      .font("Helvetica-Bold")
      .fontSize(10)
      .fillColor(reportColors.text)
      .text(`${group.label} - ${group.rows.length} divergência${group.rows.length === 1 ? "" : "s"}`, 30, doc.y);
    doc.y += 4;

    if (group.reportDates.length > 0) {
      doc
        .font("Helvetica")
        .fontSize(7.5)
        .fillColor(reportColors.muted)
        .text(`Relatório emitido em: ${group.reportDates.map(formatDateOnly).join(", ")}`, 30, doc.y, { width: 780 });
      doc.y += 6;
    }

    const grouped = new Map<EntryStatus, typeof rows>();

    for (const row of group.rows) {
      grouped.set(row.status, [...(grouped.get(row.status) ?? []), row]);
    }

    for (const [status, statusRows] of grouped.entries()) {
      ensureSpace(doc, 58);
      doc.font("Helvetica-Bold").fontSize(9).fillColor(reportColors.danger).text(`${statusLabels[status] ?? status} (${statusRows.length})`, 30, doc.y);
      doc.y += 6;
      drawTableHeader(doc, ["Código", "Fazenda", "Talhão", "Observação"], [62, 210, 56, 452]);

      for (const row of statusRows) {
        drawDivergenceRow(doc, row);
      }

      doc.y += 8;
    }

    doc.y += 6;
  }
}

function drawDivergenceRowsByFarm(doc: PDFKit.PDFDocument, rows: ReturnType<typeof listDivergencesForExport>) {
  ensureSpace(doc, 70);
  doc.font("Helvetica-Bold").fontSize(11).fillColor(reportColors.text).text("Divergências agrupadas por fazenda", 30, doc.y);
  doc.y += 8;

  if (rows.length === 0) {
    drawSimpleRow(doc, ["Nenhuma divergência encontrada nos filtros atuais."], [780]);
    return;
  }

  for (const group of groupDivergenceRowsByFarm(rows)) {
    ensureSpace(doc, 76);
    doc
      .font("Helvetica-Bold")
      .fontSize(10)
      .fillColor(reportColors.text)
      .text(`${group.label} - ${group.rows.length} divergência${group.rows.length === 1 ? "" : "s"}`, 30, doc.y);
    doc.y += 4;

    const grouped = new Map<EntryStatus, typeof rows>();

    for (const row of group.rows) {
      grouped.set(row.status, [...(grouped.get(row.status) ?? []), row]);
    }

    for (const [status, statusRows] of grouped.entries()) {
      ensureSpace(doc, 58);
      doc.font("Helvetica-Bold").fontSize(9).fillColor(reportColors.danger).text(`${statusLabels[status] ?? status} (${statusRows.length})`, 30, doc.y);
      doc.y += 6;
      drawTableHeader(doc, ["Código", "Fazenda", "Talhão", "Observação"], [62, 210, 56, 452]);

      for (const row of statusRows) {
        drawDivergenceRow(doc, row);
      }

      doc.y += 8;
    }

    doc.y += 6;
  }
}

function drawDivergenceRow(doc: PDFKit.PDFDocument, row: ReturnType<typeof listDivergencesForExport>[number]) {
  const columns = [
    row.farmCode ?? "-",
    row.farmNameRaw ?? "-",
    row.fieldCodeRaw ?? "-",
    explainDivergence(row)
  ];
  drawSimpleRow(doc, columns, [62, 210, 56, 452]);
}

function groupDivergenceRowsByPeriod(rows: ReturnType<typeof listDivergencesForExport>) {
  const groups = new Map<
    string,
    {
      start: string;
      end: string;
      label: string;
      reportDates: string[];
      rows: typeof rows;
    }
  >();

  for (const row of rows) {
    const isPdfRow = /\.pdf$/i.test(row.fileName);
    const start = isPdfRow ? row.periodStart ?? row.reportDate ?? "sem-data-pdf" : row.periodStart ?? dateOnly(row.entryDate) ?? "sem-data";
    const end = isPdfRow ? row.periodEnd ?? row.reportDate ?? start : row.periodEnd ?? start;
    const key = `${start}|${end}`;
    const group =
      groups.get(key) ??
      {
        start,
        end,
        label: formatPeriodLabel(start, end),
        reportDates: [],
        rows: []
      };

    if (row.reportDate && !group.reportDates.includes(row.reportDate)) {
      group.reportDates.push(row.reportDate);
    }

    group.rows.push(row);
    groups.set(key, group);
  }

  return [...groups.values()].sort((left, right) => left.start.localeCompare(right.start) || left.end.localeCompare(right.end));
}

function groupDivergenceRowsByFarm(rows: ReturnType<typeof listDivergencesForExport>) {
  const groups = new Map<
    string,
    {
      label: string;
      rows: typeof rows;
    }
  >();

  for (const row of rows) {
    const key = row.farmCode || "SEM-FAZENDA";
    const label = `Fazenda ${row.farmCode || "S/N"} - ${row.farmNameRaw || "Sem Nome"}`;
    const group =
      groups.get(key) ??
      {
        label,
        rows: []
      };

    group.rows.push(row);
    groups.set(key, group);
  }

  return [...groups.values()].sort((left, right) => left.label.localeCompare(right.label));
}

function dateOnly(value: string | null | undefined) {
  return value?.slice(0, 10) || undefined;
}

function formatPeriodLabel(start: string, end: string) {
  if (start === "sem-data-pdf") {
    return "Sem data do PDF";
  }

  if (start === "sem-data") {
    return "Sem data";
  }

  return start === end ? formatDateOnly(start) : `${formatDateOnly(start)} a ${formatDateOnly(end)}`;
}

function formatOptionalPeriod(start: string | null | undefined, end: string | null | undefined) {
  if (!start) {
    return null;
  }

  return formatPeriodLabel(start, end ?? start);
}

function formatPeriodShort(start: string | null | undefined, end: string | null | undefined) {
  if (!start) {
    return "-";
  }

  const startLabel = formatDateOnly(start).slice(0, 5);
  const endLabel = end && end !== start ? formatDateOnly(end).slice(0, 5) : "";

  return endLabel ? `${startLabel}-${endLabel}` : startLabel;
}

function explainDivergence(row: ReturnType<typeof listDivergencesForExport>[number]) {
  const farm = row.farmNameRaw ?? "-";
  const field = row.fieldCodeRaw ?? "-";
  const order = row.orderNumberRaw ?? "-";

  switch (row.status) {
    case "FARM_NOT_FOUND":
      return `Fazenda não cadastrada: ${farm}.`;
    case "FIELD_NOT_FOUND":
      return `Talhão não existe no cadastro: ${field}.`;
    case "FIELD_NOT_RELEASED":
      return `Talhão não liberado para colher: ${field}.`;
    case "FARM_MISMATCH":
      return `Fazenda diferente da colheita/OS: ${farm}.`;
    case "OS_NOT_FOUND":
      return `OS não encontrada na colheita atual: ${order}.`;
    case "MISSING_DATA":
      return "Linha sem fazenda ou talhão para conferir.";
    default:
      return row.notes ?? statusLabels[row.status] ?? "Divergência identificada na validação.";
  }
}

function drawTableHeader(doc: PDFKit.PDFDocument, labels: string[], widths: number[]) {
  ensureSpace(doc, 24);
  const x = 30;
  const y = doc.y;
  const height = 18;
  let cursor = x;

  doc.rect(x, y, widths.reduce((total, width) => total + width, 0), height).fillAndStroke(reportColors.header, reportColors.border);
  doc.font("Helvetica-Bold").fontSize(7.5).fillColor(reportColors.text);

  labels.forEach((label, index) => {
    doc.text(label, cursor + 4, y + 5, { width: widths[index] - 8, height: height - 4 });
    cursor += widths[index];
  });

  doc.y = y + height;
}

function drawSimpleRow(doc: PDFKit.PDFDocument, values: string[], widths: number[]) {
  const cells = values.map((value, index) => ({
    value,
    width: widths[index]
  }));
  const rowHeight = Math.max(
    18,
    ...cells.map((cell) => doc.heightOfString(cell.value, { width: cell.width - 8 }) + 8)
  );

  ensureSpace(doc, rowHeight + 4);

  const x = 30;
  const y = doc.y;
  let cursor = x;

  doc.rect(x, y, widths.reduce((total, width) => total + width, 0), rowHeight).stroke(reportColors.border);
  doc.font("Helvetica").fontSize(7.2).fillColor(reportColors.text);

  for (const cell of cells) {
    doc.text(cell.value, cursor + 4, y + 5, { width: cell.width - 8, height: rowHeight - 6, ellipsis: true });
    cursor += cell.width;
  }

  doc.y = y + rowHeight;
}

function ensureSpace(doc: PDFKit.PDFDocument, height: number) {
  if (doc.y + height <= doc.page.height - 30) {
    return;
  }

  doc.addPage();
  doc.y = 30;
}

function formatDateOnly(value: string) {
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(value);

  if (match) {
    return `${match[3]}/${match[2]}/${match[1]}`;
  }

  return value || "-";
}

function formatDateTime(value: string) {
  const date = new Date(value);

  if (Number.isNaN(date.getTime())) {
    return value;
  }

  return new Intl.DateTimeFormat("pt-BR", {
    dateStyle: "short",
    timeStyle: "short"
  }).format(date);
}

function formatNumber(value: number | null | undefined) {
  if (value === null || value === undefined) {
    return "-";
  }

  return new Intl.NumberFormat("pt-BR", {
    minimumFractionDigits: value % 1 === 0 ? 0 : 2,
    maximumFractionDigits: 2
  }).format(value);
}
