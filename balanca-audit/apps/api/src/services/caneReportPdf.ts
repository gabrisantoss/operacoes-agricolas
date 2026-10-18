import PDFDocument from "pdfkit";
import { systemIdentity } from "@balanca/shared";
import type { CaneReport, CaneReportDayRow, CaneReportFarmRow, CaneReportFieldRow } from "./caneReport.js";
import { formatReportDate } from "./caneReport.js";
import { fitPdfSingleLine } from "./pdfTextLayout.js";

const colors = {
  text: "#17202a",
  muted: "#647183",
  border: "#dce2e8",
  header: "#f3f6f8",
  total: "#e7efe9",
  green: "#26734d"
};

const margin = 30;

type Column<T> = {
  label: string;
  width: number;
  align?: "left" | "right";
  value: (row: T) => string;
};

export function renderCaneReportPdf(report: CaneReport): Promise<Buffer> {
  const doc = new PDFDocument({
    size: "A4",
    layout: "landscape",
    margin,
    bufferPages: true,
    // Creation date comes from the report, so the same report always renders the same bytes.
    info: { Title: report.title, Author: systemIdentity.currentName, CreationDate: new Date(report.generatedAt) }
  });
  const chunks: Buffer[] = [];
  const done = new Promise<Buffer>((resolve, reject) => {
    doc.on("data", (chunk: Buffer) => chunks.push(Buffer.from(chunk)));
    doc.on("end", () => resolve(Buffer.concat(chunks)));
    doc.on("error", reject);
  });

  drawHeader(doc, report);
  drawTotals(doc, report);
  // Every following page repeats which report and filters it belongs to.
  doc.on("pageAdded", () => drawContinuationHeader(doc, report));

  if (report.isEmpty) {
    doc.moveDown(1);
    doc.font("Helvetica-Bold").fontSize(11).fillColor(colors.text)
      .text("Nenhum registro encontrado para os filtros selecionados.", margin, doc.y);
  } else if (report.type === "GENERAL") {
    drawGeneral(doc, report);
  } else {
    drawDetailed(doc, report);
  }

  drawPageNumbers(doc);
  doc.end();
  return done;
}

export function formatTons(value: number | null | undefined) {
  return formatDecimal(value, 3);
}

export function formatDecimal(value: number | null | undefined, digits = 2) {
  if (value === null || value === undefined || !Number.isFinite(value)) return "-";
  return new Intl.NumberFormat("pt-BR", { minimumFractionDigits: digits, maximumFractionDigits: digits }).format(value);
}

// Area and TCH that cannot be determined are shown as N/D, never as zero.
export function formatIndicator(value: number | null | undefined, digits = 2) {
  return value === null || value === undefined || !Number.isFinite(value) ? "N/D" : formatDecimal(value, digits);
}

export function formatInteger(value: number) {
  return new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 0 }).format(value);
}

function drawHeader(doc: PDFKit.PDFDocument, report: CaneReport) {
  doc.font("Helvetica-Bold").fontSize(17).fillColor(colors.text).text(report.title, margin, 28);
  doc.font("Helvetica").fontSize(8).fillColor(colors.muted)
    .text(`${systemIdentity.currentName} · Gerado em ${new Date(report.generatedAt).toLocaleString("pt-BR")}`, margin, 50);
  doc.font("Helvetica").fontSize(9).fillColor(colors.text)
    .text(
      `Fazenda: ${report.filterLabels.farm}   ·   Talhão: ${report.filterLabels.field}   ·   Período: ${report.filterLabels.period}`,
      margin,
      66,
      { width: doc.page.width - margin * 2 }
    );
  doc.y = 84;
}

function drawContinuationHeader(doc: PDFKit.PDFDocument, report: CaneReport) {
  const text = `${report.title} (continuação)   ·   Fazenda: ${report.filterLabels.farm}   ·   Talhão: ${report.filterLabels.field}   ·   Período: ${report.filterLabels.period}`;
  doc.font("Helvetica").fontSize(7.5).fillColor(colors.muted)
    .text(fitPdfSingleLine(doc, text, doc.page.width - margin * 2), margin, 18, { lineBreak: false });
  doc.y = margin + 6;
}

function drawTotals(doc: PDFKit.PDFDocument, report: CaneReport) {
  const { totals } = report;
  const basis = `${formatInteger(totals.provenFieldCount)} de ${formatInteger(totals.fieldCount)} talhões`;
  const cards: Array<[string, string, string?]> = [
    ["Cana entregue (t)", formatTons(totals.totalNetWeight)],
    ["Cargas", formatInteger(totals.entryCount)],
    ["Média por carga (t)", formatTons(totals.averageNetWeightPerEntry)],
    ["Fazendas / talhões", `${formatInteger(totals.farmCount)} / ${formatInteger(totals.fieldCount)}`],
    ["Dias com entrega", formatInteger(totals.deliveryDays)],
    ["Área cadastrada (ha)", formatDecimal(totals.registeredAreaHa)],
    ["Área colhida comprovada (ha)", formatDecimal(totals.provenAreaHa), basis],
    [effectiveTchLabel(report), formatIndicator(totals.effectiveTch), basis],
    ["Cargas divergentes", formatInteger(totals.divergentCount)]
  ];
  const gap = 5;
  const width = (doc.page.width - margin * 2 - gap * (cards.length - 1)) / cards.length;
  const y = doc.y;

  cards.forEach(([label, value, caption], index) => {
    const x = margin + index * (width + gap);
    doc.rect(x, y, width, 44).fillAndStroke(colors.header, colors.border);
    doc.font("Helvetica").fontSize(6.5).fillColor(colors.muted).text(label, x + 5, y + 5, { width: width - 10, height: 16 });
    doc.font("Helvetica-Bold").fontSize(11.5).fillColor(colors.text).text(value, x + 5, y + 20, { width: width - 10, lineBreak: false });
    if (caption) {
      doc.font("Helvetica").fontSize(6).fillColor(colors.muted).text(caption, x + 5, y + 34, { width: width - 10, lineBreak: false });
    }
  });

  doc.y = y + 52;
  doc.font("Helvetica").fontSize(7.5).fillColor(colors.muted);
  for (const note of report.notes) {
    doc.text(note, margin, doc.y, { width: doc.page.width - margin * 2 });
    doc.moveDown(0.2);
  }
  doc.moveDown(0.6);
}

// "Parcial" whenever the effective TCH covers only part of the fields in the report.
export function effectiveTchLabel(report: Pick<CaneReport, "totals">) {
  const { provenFieldCount, fieldCount } = report.totals;
  return provenFieldCount > 0 && provenFieldCount < fieldCount ? "TCH efetivo parcial (t/ha)" : "TCH efetivo (t/ha)";
}

function drawGeneral(doc: PDFKit.PDFDocument, report: CaneReport) {
  sectionTitle(doc, "Cana entregue por fazenda");
  drawTable<CaneReportFarmRow>(doc, farmColumns(), report.farms, farmTotalRow(report));

  sectionTitle(doc, "Entregas por dia");
  drawTable<CaneReportDayRow>(doc, [
    { label: "Data", width: 120, value: (row) => formatReportDate(row.date) },
    { label: "Cargas", width: 120, align: "right", value: (row) => formatInteger(row.entryCount) },
    { label: "Talhões com entrega", width: 120, align: "right", value: (row) => formatInteger(row.fieldCount) },
    { label: "Cana entregue (t)", width: 160, align: "right", value: (row) => formatTons(row.totalNetWeight) },
    { label: "Cana em cargas divergentes (t)", width: 180, align: "right", value: (row) => formatTons(row.divergentNetWeight) }
  ], report.days, {
    date: "Total",
    entryCount: report.totals.entryCount,
    fieldCount: report.totals.fieldCount,
    totalNetWeight: report.totals.totalNetWeight,
    divergentNetWeight: report.totals.divergentNetWeight
  }, (row) => (row.date === "Total" ? "Total" : formatReportDate(row.date)));
}

function drawDetailed(doc: PDFKit.PDFDocument, report: CaneReport) {
  const columns: Column<CaneReportFieldRow>[] = [
    { label: "Talhão", width: 44, value: (row) => row.fieldCode },
    { label: "Nome", width: 86, value: (row) => row.fieldName ?? "-" },
    { label: "Área cad. (ha)", width: 58, align: "right", value: (row) => formatIndicator(row.registeredAreaHa) },
    { label: "Cargas", width: 44, align: "right", value: (row) => formatInteger(row.entryCount) },
    { label: "Cana (t)", width: 72, align: "right", value: (row) => formatTons(row.totalNetWeight) },
    { label: "Média/carga (t)", width: 66, align: "right", value: (row) => formatTons(row.averageNetWeightPerEntry) },
    { label: "Situação da colheita", width: 142, value: (row) => row.evidenceLabel },
    { label: "TCH efetivo", width: 56, align: "right", value: (row) => formatIndicator(row.effectiveTch) },
    { label: "Dias", width: 32, align: "right", value: (row) => (row.key === "subtotal" ? "-" : formatInteger(row.deliveryDays)) },
    { label: "Primeira", width: 56, value: (row) => formatReportDate(row.firstDate) },
    { label: "Última", width: 56, value: (row) => formatReportDate(row.lastDate) },
    { label: "Divergentes", width: 58, align: "right", value: (row) => formatInteger(row.divergentCount) }
  ];

  for (const farm of report.farms) {
    sectionTitle(doc, `${farm.farmCode ? `${farm.farmCode} - ` : ""}${farm.farmName}`);
    const fields = report.fields.filter((field) => field.farmKey === farm.key);
    drawTable(doc, columns, fields, {
      key: "subtotal",
      farmKey: farm.key,
      farmCode: farm.farmCode,
      farmName: farm.farmName,
      fieldCode: "Subtotal",
      fieldName: `${formatInteger(farm.fieldCount)} talhão(ões)`,
      registeredAreaHa: farm.registeredAreaHa || null,
      entryCount: farm.entryCount,
      divergentCount: farm.divergentCount,
      totalNetWeight: farm.totalNetWeight,
      averageNetWeightPerEntry: farm.entryCount > 0 ? farm.totalNetWeight / farm.entryCount : null,
      evidence: "OPEN",
      evidenceLabel: `${formatInteger(farm.provenFieldCount)} de ${formatInteger(farm.fieldCount)} comprovados`,
      closedOrderNumber: null,
      closedOrderEndDate: null,
      effectiveTch: farm.effectiveTch,
      deliveryDays: 0,
      firstDate: farm.firstDate,
      lastDate: farm.lastDate
    });
  }

  sectionTitle(doc, "Resumo por fazenda");
  drawTable<CaneReportFarmRow>(doc, farmColumns(), report.farms, farmTotalRow(report));
}

function farmColumns(): Column<CaneReportFarmRow>[] {
  return [
    { label: "Código", width: 50, value: (row) => row.farmCode ?? "-" },
    { label: "Fazenda", width: 122, value: (row) => row.farmName },
    { label: "Talhões", width: 44, align: "right", value: (row) => formatInteger(row.fieldCount) },
    { label: "Cargas", width: 46, align: "right", value: (row) => formatInteger(row.entryCount) },
    { label: "Cana (t)", width: 76, align: "right", value: (row) => formatTons(row.totalNetWeight) },
    { label: "% do total", width: 46, align: "right", value: (row) => formatDecimal(row.shareOfTotal, 1) },
    { label: "Área cad. (ha)", width: 60, align: "right", value: (row) => formatDecimal(row.registeredAreaHa) },
    { label: "Área comprov. (ha)", width: 70, align: "right", value: (row) => formatDecimal(row.provenAreaHa) },
    { label: "Comprovados", width: 58, align: "right", value: (row) => `${formatInteger(row.provenFieldCount)}/${formatInteger(row.fieldCount)}` },
    { label: "TCH efetivo", width: 54, align: "right", value: (row) => formatIndicator(row.effectiveTch) },
    { label: "Divergentes", width: 54, align: "right", value: (row) => formatInteger(row.divergentCount) },
    { label: "Período", width: 102, value: (row) => `${formatReportDate(row.firstDate)} a ${formatReportDate(row.lastDate)}` }
  ];
}

function farmTotalRow(report: CaneReport): CaneReportFarmRow {
  return {
    key: "total",
    farmCode: "Total",
    farmName: `${formatInteger(report.totals.farmCount)} fazenda(s)`,
    fieldCount: report.totals.fieldCount,
    entryCount: report.totals.entryCount,
    divergentCount: report.totals.divergentCount,
    totalNetWeight: report.totals.totalNetWeight,
    shareOfTotal: report.totals.totalNetWeight > 0 ? 100 : 0,
    registeredAreaHa: report.totals.registeredAreaHa,
    provenAreaHa: report.totals.provenAreaHa,
    provenFieldCount: report.totals.provenFieldCount,
    provenNetWeight: report.totals.provenNetWeight,
    effectiveTch: report.totals.effectiveTch,
    firstDate: report.totals.firstDate,
    lastDate: report.totals.lastDate
  };
}
function sectionTitle(doc: PDFKit.PDFDocument, title: string) {
  ensureSpace(doc, 60);
  doc.moveDown(0.4);
  doc.font("Helvetica-Bold").fontSize(11).fillColor(colors.green).text(title, margin, doc.y);
  doc.moveDown(0.3);
}

function drawTable<T>(
  doc: PDFKit.PDFDocument,
  columns: Column<T>[],
  rows: T[],
  totalRow?: T,
  firstCell?: (row: T) => string
) {
  const rowHeight = 16;
  const header = () => drawHeaderRow(doc, columns);

  header();
  for (const row of rows) {
    if (doc.y + rowHeight > doc.page.height - margin - 14) {
      doc.addPage();
      header();
    }
    drawRow(doc, cellValues(columns, row, firstCell), columns, null, false);
  }

  if (totalRow) {
    ensureSpace(doc, rowHeight + 4);
    drawRow(doc, cellValues(columns, totalRow, firstCell), columns, colors.total, true);
  }
  doc.moveDown(0.6);
}

function cellValues<T>(columns: Column<T>[], row: T, firstCell?: (row: T) => string) {
  return columns.map((column, index) => (index === 0 && firstCell ? firstCell(row) : column.value(row)));
}

// Header labels wrap instead of being truncated; the row grows to the tallest label.
function headerRowHeight<T>(doc: PDFKit.PDFDocument, columns: Column<T>[]) {
  doc.font("Helvetica-Bold").fontSize(7.5);
  const tallest = Math.max(...columns.map((column) => doc.heightOfString(column.label, { width: column.width - 8 })));
  return Math.max(16, Math.ceil(tallest) + 8);
}

function drawHeaderRow<T>(doc: PDFKit.PDFDocument, columns: Column<T>[]) {
  const height = headerRowHeight(doc, columns);
  const y = doc.y;
  const width = columns.reduce((total, column) => total + column.width, 0);

  doc.rect(margin, y, width, height).fillAndStroke(colors.header, colors.border);
  doc.font("Helvetica-Bold").fontSize(7.5).fillColor(colors.text);
  let x = margin;
  for (const column of columns) {
    doc.text(column.label, x + 4, y + 5, { width: column.width - 8, align: column.align ?? "left", height: height - 6 });
    x += column.width;
  }
  doc.y = y + height;
}

function drawRow<T>(doc: PDFKit.PDFDocument, values: string[], columns: Column<T>[], fill: string | null, bold: boolean) {
  const height = 16;
  const y = doc.y;
  const width = columns.reduce((total, column) => total + column.width, 0);

  if (fill) {
    doc.rect(margin, y, width, height).fillAndStroke(fill, colors.border);
  } else {
    doc.moveTo(margin, y + height).lineTo(margin + width, y + height).strokeColor(colors.border).stroke();
  }

  doc.font(bold ? "Helvetica-Bold" : "Helvetica").fontSize(7.5).fillColor(colors.text);
  let x = margin;
  values.forEach((value, index) => {
    const column = columns[index]!;
    const text = fitPdfSingleLine(doc, value, column.width - 8);
    doc.text(text, x + 4, y + 5, { width: column.width - 8, align: column.align ?? "left", lineBreak: false });
    x += column.width;
  });
  doc.y = y + height;
}

function ensureSpace(doc: PDFKit.PDFDocument, height: number) {
  if (doc.y + height > doc.page.height - margin - 14) {
    doc.addPage();
  }
}

function drawPageNumbers(doc: PDFKit.PDFDocument) {
  const range = doc.bufferedPageRange();
  for (let index = range.start; index < range.start + range.count; index += 1) {
    doc.switchToPage(index);
    doc.page.margins.bottom = 0;
    doc.font("Helvetica").fontSize(7).fillColor(colors.muted)
      .text(`Página ${index + 1} de ${range.count}`, margin, doc.page.height - margin + 6, {
        width: doc.page.width - margin * 2,
        align: "right",
        lineBreak: false
      });
  }
}
