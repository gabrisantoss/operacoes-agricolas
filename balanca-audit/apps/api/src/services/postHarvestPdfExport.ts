import PDFDocument from "pdfkit";
import { systemIdentity } from "@balanca/shared";
import type { PostHarvestExportData, PostHarvestExportRow } from "./postHarvestExcelExport.js";

const colors = {
  primary: "#14532D", // Dark Green
  secondary: "#1E3A5F", // Dark Blue
  accent: "#2E7D32", // Green Accent
  danger: "#B71C1C", // Red
  textMain: "#102033",
  textMuted: "#60748C",
  gridLine: "#D7DED9",
  lightBg: "#EAF3FA"
};

export function buildPostHarvestExportPdf(data: PostHarvestExportData): Promise<Buffer> {
  return new Promise((resolve, reject) => {
    try {
      const doc = new PDFDocument({ margin: 40, size: "A4", layout: "landscape" });
      const buffers: Buffer[] = [];
      doc.on("data", buffers.push.bind(buffers));
      doc.on("end", () => resolve(Buffer.concat(buffers)));

      renderPostHarvestExportPdf(doc, data);

      doc.end();
    } catch (error) {
      reject(error);
    }
  });
}

export function renderPostHarvestExportPdf(doc: PDFKit.PDFDocument, data: PostHarvestExportData) {
  renderSummaryDashboard(doc, data);
  renderDetailedTable(doc, data.rows);
}

function renderSummaryDashboard(doc: PDFKit.PDFDocument, data: PostHarvestExportData) {
  const { rows } = data;
  const totalCane = rows.reduce((sum, row) => sum + row.caneTons, 0);
  const totalHa = rows.reduce((sum, row) => sum + row.areaHa, 0);
  const totalAlq = rows.reduce((sum, row) => sum + row.areaAlq, 0);
  const tchGlobal = totalHa > 0 ? totalCane / totalHa : 0;
  const tcaGlobal = totalAlq > 0 ? totalCane / totalAlq : 0;
  const closedOrders = new Set(rows.map(r => r.orderId)).size;

  // Header
  doc.rect(0, 0, doc.page.width, 80).fill(colors.primary);
  doc.fillColor("#FFFFFF").fontSize(20).text(`Rateio de OS - Fechamento de Colheita`, 40, 25);
  doc.fontSize(10).text(`Gerado em: ${new Date().toLocaleString("pt-BR")}`, 40, 50);
  doc.text(`Operacoes Agricolas - ${systemIdentity.currentName}`, 0, 50, { align: "right", width: doc.page.width - 40 });

  doc.moveDown(3);

  // KPIs
  const yKpi = 110;
  const kpiWidth = 120;
  const spacing = 15;
  let xKpi = 40;

  const drawKpi = (title: string, value: string, color: string) => {
    doc.rect(xKpi, yKpi, kpiWidth, 60).fill(colors.lightBg).stroke(colors.gridLine);
    doc.fillColor(colors.textMuted).fontSize(10).text(title, xKpi + 10, yKpi + 10);
    doc.fillColor(color).fontSize(16).text(value, xKpi + 10, yKpi + 30);
    xKpi += kpiWidth + spacing;
  };

  drawKpi("Total Cana (t)", totalCane.toLocaleString("pt-BR", { minimumFractionDigits: 2 }), colors.textMain);
  drawKpi("Área (ha)", totalHa.toLocaleString("pt-BR", { minimumFractionDigits: 2 }), colors.textMain);
  drawKpi("TCH Global", tchGlobal.toLocaleString("pt-BR", { minimumFractionDigits: 2 }), colors.secondary);
  drawKpi("TCA Global", tcaGlobal.toLocaleString("pt-BR", { minimumFractionDigits: 2 }), colors.secondary);
  drawKpi("OS Fechadas", closedOrders.toString(), colors.textMain);

  doc.moveDown(5);
}

function renderDetailedTable(doc: PDFKit.PDFDocument, rows: PostHarvestExportRow[]) {
  // Group by Farm
  const byFarm = new Map<string, PostHarvestExportRow[]>();
  for (const row of rows) {
    const list = byFarm.get(row.fundoAgricola) || [];
    list.push(row);
    byFarm.set(row.fundoAgricola, list);
  }

  const farms = Array.from(byFarm.entries()).sort((a, b) => a[0].localeCompare(b[0]));
  const colX = [40, 120, 200, 300, 380, 480, 580, 680];

  for (const [farmName, farmRows] of farms) {
    doc.addPage();
    let y = drawFarmTablePage(doc, farmName, colX, false);

    let farmTotalCane = 0;
    let farmTotalHa = 0;

    for (const row of farmRows) {
      if (y > doc.page.height - 60) {
        doc.addPage();
        y = drawFarmTablePage(doc, farmName, colX, true);
      }

      farmTotalCane += row.caneTons;
      farmTotalHa += row.areaHa;

      doc.fillColor(colors.textMain).fontSize(9);
      doc.text(row.orderNumber, colX[0], y);
      doc.text(row.talhao, colX[1], y);
      doc.text(row.dataFechamento.toLocaleDateString("pt-BR"), colX[2], y);
      doc.text(row.areaHa.toLocaleString("pt-BR"), colX[3], y);
      doc.text(row.areaAlq.toLocaleString("pt-BR"), colX[4], y);
      doc.text(row.caneTons.toLocaleString("pt-BR"), colX[5], y);

      // TCH
      if (row.tch && row.tch > 80) doc.fillColor(colors.accent);
      else if (row.tch && row.tch < 60) doc.fillColor(colors.danger);
      doc.text(row.tch ? row.tch.toLocaleString("pt-BR") : "-", colX[6], y);

      // TCA
      doc.fillColor(colors.textMain);
      if (row.tca && row.tca > 80 * 2.42) doc.fillColor(colors.accent); // Approx conversion 1 Alq = 2.42 Ha
      else if (row.tca && row.tca < 60 * 2.42) doc.fillColor(colors.danger);
      doc.text(row.tca ? row.tca.toLocaleString("pt-BR") : "-", colX[7], y);

      y += 15;

      // Line separator
      doc.strokeColor(colors.gridLine).moveTo(40, y - 5).lineTo(doc.page.width - 40, y - 5).stroke();
    }

    // Subtotal
    y += 5;
    doc.fillColor(colors.primary).fontSize(10).text("SUBTOTAL FAZENDA", colX[3], y);
    doc.text(farmTotalCane.toLocaleString("pt-BR"), colX[5], y);
    doc.text(farmTotalHa > 0 ? (farmTotalCane/farmTotalHa).toLocaleString("pt-BR") : "-", colX[6], y);
  }
}

function drawFarmTablePage(
  doc: PDFKit.PDFDocument,
  farmName: string,
  colX: number[],
  continuation: boolean
) {
  const title = continuation ? `Fazenda: ${farmName} - continuação` : `Fazenda: ${farmName}`;
  doc.fillColor(colors.primary).font("Helvetica").fontSize(16).text(title, 40, 40, {
    width: doc.page.width - 80,
    ellipsis: true,
    lineBreak: false
  });
  const tableTop = 75;
  const colHeaders = ["OS", "Talhão", "Fechamento", "Área (ha)", "Área (alq)", "Cana (t)", "TCH", "TCA"];
  doc.rect(40, tableTop - 5, doc.page.width - 80, 20).fill(colors.secondary);
  doc.fillColor("#FFFFFF").fontSize(10);
  colHeaders.forEach((header, index) => doc.text(header, colX[index], tableTop));
  return tableTop + 25;
}
