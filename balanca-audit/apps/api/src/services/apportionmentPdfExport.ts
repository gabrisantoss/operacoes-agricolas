import {
  apportionmentFieldMetrics,
  apportionmentResultMetrics,
  calculateTonsPerHectare,
  type ApportionmentResult
} from "./apportionment.js";

const colors = {
  primary: "#14532D",
  secondary: "#1E3A5F",
  light: "#EAF3FA",
  grid: "#D7DED9",
  text: "#333333",
  success: "#2E7D32",
  danger: "#B71C1C",
  accent: "#1D55A6"
};

export function renderAllApportionmentsPdf(
  doc: PDFKit.PDFDocument,
  results: ApportionmentResult[],
  closedOrderCount: number,
  generatedAt = new Date()
) {
  const totalGlobalCane = results.reduce((sum, result) => sum + result.allocatedWeight, 0);
  const totalUnassignedCane = results.reduce((sum, result) => sum + result.unassignedWeight, 0);
  const totalGlobalHa = results.reduce((sum, result) => sum + result.totalAreaHa, 0);
  const tchGlobal = calculateTonsPerHectare(totalGlobalCane, totalGlobalHa);

  doc.rect(0, 0, doc.page.width, 80).fill(colors.primary);
  doc.fillColor("#FFFFFF").fontSize(20).text("Rateio Geral - Operacoes Agricolas", 40, 30);
  doc.fontSize(10).text(`Gerado em: ${generatedAt.toLocaleString("pt-BR")}`, 40, 55);
  doc.fillColor(colors.secondary).fontSize(16).text("Resumo Global", 40, 110);
  doc.fontSize(12).fillColor(colors.text);
  doc.text(`Total de OS Fechadas: ${closedOrderCount}`, 40, 140);
  doc.text(`Total Cana Entregue: ${formatNumber(totalGlobalCane)} t`, 40, 160);
  doc.text(`Área Total Colhida: ${formatNumber(totalGlobalHa)} ha`, 40, 180);
  doc.fillColor(colors.accent).text(`TCH Global: ${formatNumber(tchGlobal)} t/ha`, 40, 200);
  if (totalUnassignedCane > 0) {
    doc.fillColor(colors.danger).text(`Peso sem fazenda identificada: ${formatNumber(totalUnassignedCane)} t`, 40, 220);
  }

  doc.addPage();
  let renderedOrder = false;

  for (const result of results) {
    if (result.fields.length === 0) continue;
    if (renderedOrder) doc.addPage();
    renderedOrder = true;
    renderApportionmentOrderTable(doc, result, {
      title: `OS ${result.orderNumber}`,
      continuationTitle: `OS ${result.orderNumber} - continuação`,
      columns: [50, 120, 200, 300, 430]
    });
  }

  if (!renderedOrder) {
    doc.fontSize(14).fillColor(colors.danger).text("Nenhuma OS encontrada com talhões.", 40, 250);
  }
}

export function renderSingleApportionmentPdf(doc: PDFKit.PDFDocument, result: ApportionmentResult) {
  renderApportionmentOrderTable(doc, result, {
    title: `Rateio OS ${result.orderNumber}`,
    continuationTitle: `Rateio OS ${result.orderNumber} - continuação`,
    columns: [50, 150, 250, 350, 450]
  });
}

type TableLayout = {
  title: string;
  continuationTitle: string;
  columns: [number, number, number, number, number];
};

function renderApportionmentOrderTable(doc: PDFKit.PDFDocument, result: ApportionmentResult, layout: TableLayout) {
  let currentY = drawOrderPageFrame(doc, result, layout.title, layout.columns);

  for (const field of result.fields) {
    if (currentY > doc.page.height - 100) {
      doc.addPage();
      currentY = drawOrderPageFrame(doc, result, layout.continuationTitle, layout.columns);
    }

    const { weightTons, tch } = apportionmentFieldMetrics(field);
    doc.fillColor(colors.text).font("Helvetica").fontSize(10);
    doc.text(`${field.farmCode || "S/C"}/${field.fieldCode}`, layout.columns[0], currentY);
    doc.text(field.areaHa.toFixed(2), layout.columns[1], currentY);
    doc.text(`${(field.percentage * 100).toFixed(2)}%`, layout.columns[2], currentY);
    doc.text(formatNumber(weightTons), layout.columns[3], currentY);

    if (tch > 80) doc.fillColor(colors.success);
    else if (tch > 0 && tch < 60) doc.fillColor(colors.danger);
    doc.text(formatNumber(tch), layout.columns[4], currentY);
    currentY += 20;
  }

  doc.moveTo(50, currentY - 5).lineTo(500, currentY - 5).stroke(colors.grid);
  currentY += 5;
  const { weightTons, tch } = apportionmentResultMetrics(result);
  doc.fillColor(colors.primary).font("Helvetica-Bold").fontSize(10);
  doc.text("TOTAL", layout.columns[0], currentY);
  doc.text(result.totalAreaHa.toFixed(2), layout.columns[1], currentY);
  doc.text(formatAllocatedPercentage(result), layout.columns[2], currentY);
  doc.text(formatNumber(weightTons), layout.columns[3], currentY);
  doc.text(formatNumber(tch), layout.columns[4], currentY);

  if (result.unassignedWeight > 0) {
    currentY += 22;
    doc.fillColor(colors.danger).font("Helvetica-Bold").fontSize(9)
      .text(`Peso sem fazenda identificada: ${formatNumber(result.unassignedWeight)} t`, 50, currentY);
  }
}

function drawOrderPageFrame(
  doc: PDFKit.PDFDocument,
  result: ApportionmentResult,
  title: string,
  columns: TableLayout["columns"]
) {
  doc.rect(40, 40, doc.page.width - 80, 60).fill(colors.light);
  doc.fillColor(colors.primary).font("Helvetica").fontSize(16).text(title, 50, 50);
  doc.fontSize(10).fillColor(colors.secondary).text(`Fazendas: ${formatFarmSummary(result)}`, 50, 75, {
    width: 490,
    ellipsis: true,
    lineBreak: false
  });

  const headerY = 125;
  doc.rect(40, headerY - 5, doc.page.width - 80, 20).fill(colors.secondary);
  doc.fillColor("#FFFFFF").fontSize(10).font("Helvetica-Bold");
  doc.text("Faz./Talhão", columns[0], headerY);
  doc.text("Área (ha)", columns[1], headerY);
  doc.text("Partic. (%)", columns[2], headerY);
  doc.text("Peso Rateado (t)", columns[3], headerY);
  doc.text("TCH (t/ha)", columns[4], headerY);
  return headerY + 25;
}

function formatFarmSummary(result: ApportionmentResult) {
  return result.farms.map((farm) => `${farm.farmCode || "S/C"} - ${farm.farmName}`).join(" | ");
}

function formatAllocatedPercentage(result: ApportionmentResult) {
  const percentage = result.totalWeight > 0 ? (result.allocatedWeight / result.totalWeight) * 100 : 0;
  return `${percentage.toFixed(2)}%`;
}

function formatNumber(value: number) {
  return value.toLocaleString("pt-BR", { maximumFractionDigits: 2 });
}
