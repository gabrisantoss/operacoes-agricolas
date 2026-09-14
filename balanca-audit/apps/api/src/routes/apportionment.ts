import { Router } from "express";
import ExcelJS from "exceljs";
import PDFDocument from "pdfkit";
import { db } from "../db.js";
import { OrdersRepository } from "../repositories/ordersRepository.js";
import {
  apportionmentFieldMetrics,
  apportionmentResultMetrics,
  calculateTonsPerHectare,
  calculateApportionments,
  countClosedApportionmentOrders,
  type ApportionmentHarvestedFieldRow,
  type ApportionmentWeightRow
} from "../services/apportionment.js";
import { renderAllApportionmentsPdf, renderSingleApportionmentPdf } from "../services/apportionmentPdfExport.js";
import { assertExportRowLimit } from "../services/exportControl.js";


export const apportionmentRouter = Router();

const ordersRepository = new OrdersRepository(db);

export function readApportionments(year?: number) {
  return readApportionmentSnapshot(year).results;
}

function readApportionmentSnapshot(year?: number) {
  const orders = year ? ordersRepository.listOrdersByYear(year) : ordersRepository.listOrders();
  const weights = db.prepare(`
    SELECT
      ce.order_id,
      COALESCE(ce.farm_id, f.farm_id) AS farm_id,
      SUM(ce.net_weight) AS total_weight
    FROM cane_entries ce
    LEFT JOIN fields f ON f.id = ce.field_id
    WHERE ce.status != 'ERROR' AND ce.order_id IS NOT NULL
    GROUP BY ce.order_id, COALESCE(ce.farm_id, f.farm_id)
  `).all() as ApportionmentWeightRow[];
  const harvestedFields = db.prepare(`
    SELECT
      ce.order_id,
      COALESCE(ce.farm_id, f.farm_id) AS farm_id,
      ce.field_id,
      ce.field_code_raw
    FROM cane_entries ce
    LEFT JOIN fields f ON f.id = ce.field_id
    WHERE ce.status != 'ERROR' AND ce.order_id IS NOT NULL
    GROUP BY ce.order_id, COALESCE(ce.farm_id, f.farm_id), ce.field_id, ce.field_code_raw
  `).all() as ApportionmentHarvestedFieldRow[];

  return {
    results: calculateApportionments(orders, weights, harvestedFields),
    closedOrderCount: countClosedApportionmentOrders(orders)
  };
}

apportionmentRouter.get("/", (req, res) => {
  const yearParam = req.query.year ? Number(req.query.year) : undefined;
  res.json(readApportionments(yearParam));
});

apportionmentRouter.get("/export/all/excel", async (req, res) => {
  const yearParam = req.query.year ? Number(req.query.year) : undefined;
  const { results, closedOrderCount } = readApportionmentSnapshot(yearParam);
  assertExportRowLimit(results.reduce((total, result) => total + Math.max(1, result.fields.length), 0));

  const workbook = new ExcelJS.Workbook();
  workbook.creator = "Operacoes Agricolas";

  const totalGlobalCane = results.reduce((sum, result) => sum + result.allocatedWeight, 0);
  const totalUnassignedCane = results.reduce((sum, result) => sum + result.unassignedWeight, 0);
  const totalGlobalHa = results.reduce((s, r) => s + r.totalAreaHa, 0);
  const tchGlobal = calculateTonsPerHectare(totalGlobalCane, totalGlobalHa);

  const summarySheet = workbook.addWorksheet("Resumo Safra", {
    views: [{ state: "frozen", xSplit: 0, ySplit: 0 }]
  });
  summarySheet.columns = [{ width: 35 }, { width: 25 }];
  summarySheet.getCell("A1").value = "RESUMO GERAL DO RATEIO";
  summarySheet.getCell("A1").font = { size: 16, bold: true, color: { argb: "FF14532D" } };
  summarySheet.mergeCells("A1:B1");
  summarySheet.addRow([]);
  summarySheet.addRow(["Total de OS Fechadas:", closedOrderCount]).font = { bold: true };
  summarySheet.addRow(["Total Peso Rateado (t):", totalGlobalCane]).font = { bold: true };
  summarySheet.lastRow!.getCell(2).numFmt = "#,##0.00";
  summarySheet.lastRow!.getCell(2).font = { bold: true, color: { argb: "FF14532D" } };
  summarySheet.addRow(["Peso sem fazenda identificada (t):", totalUnassignedCane]).font = { bold: true };
  summarySheet.lastRow!.getCell(2).numFmt = "#,##0.00";
  summarySheet.addRow(["Área Total Colhida (ha):", totalGlobalHa]).font = { bold: true };
  summarySheet.lastRow!.getCell(2).numFmt = "#,##0.00";
  summarySheet.addRow(["TCH Médio Global (t/ha):", tchGlobal]).font = { bold: true };
  summarySheet.lastRow!.getCell(2).numFmt = "#,##0.00";
  summarySheet.lastRow!.getCell(2).font = { bold: true, color: { argb: "FF1D55A6" } };

  const worksheet = workbook.addWorksheet("Rateio Geral", {
    views: [{ state: "frozen", ySplit: 1 }]
  });

  worksheet.columns = [
    { header: "OS", key: "orderNumber", width: 12 },
    { header: "Código", key: "farmCode", width: 12 },
    { header: "Fazenda", key: "farmName", width: 35 },
    { header: "Talhão", key: "fieldCode", width: 15 },
    { header: "Área (ha)", key: "areaHa", width: 15 },
    { header: "Participação (%)", key: "percentage", width: 20 },
    { header: "Peso Rateado (t)", key: "proratedWeight", width: 25 },
    { header: "TCH (t/ha)", key: "tch", width: 20 },
  ];

  worksheet.getRow(1).font = { bold: true, color: { argb: "FFFFFFFF" } };
  worksheet.getRow(1).fill = { type: "pattern", pattern: "solid", fgColor: { argb: "FF14532D" } };

  for (const result of results) {
    if (result.fields.length === 0) continue;

    for (const field of result.fields) {
      const { weightTons: fieldCane, tch } = apportionmentFieldMetrics(field);
      const row = worksheet.addRow({
        orderNumber: result.orderNumber,
        farmCode: field.farmCode || "-",
        farmName: field.farmName,
        fieldCode: field.fieldCode,
        areaHa: field.areaHa,
        percentage: field.percentage,
        proratedWeight: fieldCane,
        tch: tch
      });
      row.getCell("areaHa").numFmt = "#,##0.00";
      row.getCell("percentage").numFmt = "0.00%";
      row.getCell("proratedWeight").numFmt = "#,##0.00";
      row.getCell("tch").numFmt = "#,##0.00";

      // Color-code TCH
      if (tch > 80) row.getCell("tch").font = { color: { argb: "FF2E7D32" }, bold: true };
      else if (tch > 0 && tch < 60) row.getCell("tch").font = { color: { argb: "FFB71C1C" }, bold: true };
    }

    const { weightTons: totalCaneResult, tch: resultTch } = apportionmentResultMetrics(result);

    const totalRow = worksheet.addRow({
      orderNumber: result.orderNumber,
      farmCode: result.farmCode || "-",
      farmName: "TOTAL",
      fieldCode: "",
      areaHa: result.totalAreaHa,
      percentage: result.totalWeight > 0 ? result.allocatedWeight / result.totalWeight : 0,
      proratedWeight: totalCaneResult,
      tch: resultTch
    });
    totalRow.font = { bold: true, color: { argb: "FF1E3A5F" } };
    totalRow.fill = { type: "pattern", pattern: "solid", fgColor: { argb: "FFEAF3FA" } };
    totalRow.getCell("areaHa").numFmt = "#,##0.00";
    totalRow.getCell("percentage").numFmt = "0.00%";
    totalRow.getCell("proratedWeight").numFmt = "#,##0.00";
    totalRow.getCell("tch").numFmt = "#,##0.00";

    if (result.unassignedWeight > 0) {
      const warningRow = worksheet.addRow({
        orderNumber: result.orderNumber,
        farmName: "PESO SEM FAZENDA IDENTIFICADA",
        proratedWeight: result.unassignedWeight
      });
      warningRow.font = { bold: true, color: { argb: "FFB71C1C" } };
      warningRow.getCell("proratedWeight").numFmt = "#,##0.00";
    }

    worksheet.addRow({}); // Linha em branco separando as OS
  }

  res.setHeader("Content-Type", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet");
  res.setHeader("Content-Disposition", `attachment; filename="Rateio_Geral_Todas_OS.xlsx"`);

  await workbook.xlsx.write(res);
  res.end();
});

apportionmentRouter.get("/export/all/pdf", (req, res) => {
  const yearParam = req.query.year ? Number(req.query.year) : undefined;
  const { results, closedOrderCount } = readApportionmentSnapshot(yearParam);
  assertExportRowLimit(results.reduce((total, result) => total + Math.max(1, result.fields.length), 0));

  const doc = new PDFDocument({ margin: 40, size: "A4" });

  res.setHeader("Content-Type", "application/pdf");
  res.setHeader("Content-Disposition", `attachment; filename="Rateio_Geral_Todas_OS.pdf"`);

  doc.pipe(res);
  renderAllApportionmentsPdf(doc, results, closedOrderCount);
  doc.end();
});

apportionmentRouter.get("/:orderId", (req, res) => {
  const result = findApportionment(req.params.orderId);
  if (!result) return res.status(404).json({ message: "OS nao encontrada" });
  res.json(result);
});

apportionmentRouter.get("/:orderId/export/excel", async (req, res) => {
  const result = findApportionment(req.params.orderId);
  if (!result) return res.status(404).json({ message: "OS nao encontrada" });
  assertExportRowLimit(result.fields.length);

  const workbook = new ExcelJS.Workbook();
  workbook.creator = "Operacoes Agricolas";
  const worksheet = workbook.addWorksheet("Rateio");

  worksheet.columns = [
    { header: "Código fazenda", key: "farmCode", width: 18 },
    { header: "Fazenda", key: "farmName", width: 35 },
    { header: "Talhão", key: "fieldCode", width: 15 },
    { header: "Área (ha)", key: "areaHa", width: 15 },
    { header: "Participação (%)", key: "percentage", width: 20 },
    { header: "Peso Rateado (t)", key: "proratedWeight", width: 25 },
    { header: "TCH (t/ha)", key: "tch", width: 20 },
  ];

  worksheet.getRow(1).font = { bold: true, color: { argb: "FFFFFFFF" } };
  worksheet.getRow(1).fill = { type: "pattern", pattern: "solid", fgColor: { argb: "FF14532D" } };

  for (const field of result.fields) {
    const { weightTons: fieldCane, tch } = apportionmentFieldMetrics(field);
    const row = worksheet.addRow({
      farmCode: field.farmCode || "-",
      farmName: field.farmName,
      fieldCode: field.fieldCode,
      areaHa: field.areaHa,
      percentage: field.percentage,
      proratedWeight: fieldCane,
      tch: tch
    });
    row.getCell("areaHa").numFmt = "#,##0.00";
    row.getCell("percentage").numFmt = "0.00%";
    row.getCell("proratedWeight").numFmt = "#,##0.00";
    row.getCell("tch").numFmt = "#,##0.00";

    // Color-code TCH
    if (tch > 80) row.getCell("tch").font = { color: { argb: "FF2E7D32" }, bold: true };
    else if (tch > 0 && tch < 60) row.getCell("tch").font = { color: { argb: "FFB71C1C" }, bold: true };
  }

  worksheet.addRow({});

  const { weightTons: totalCaneResult, tch: resultTch } = apportionmentResultMetrics(result);
  const totalRow = worksheet.addRow({
    farmName: "TOTAL RATEADO",
    fieldCode: "TOTAL",
    areaHa: result.totalAreaHa,
    percentage: result.totalWeight > 0 ? result.allocatedWeight / result.totalWeight : 0,
    proratedWeight: totalCaneResult,
    tch: resultTch
  });
  totalRow.font = { bold: true, color: { argb: "FF1E3A5F" } };
  totalRow.fill = { type: "pattern", pattern: "solid", fgColor: { argb: "FFEAF3FA" } };
  totalRow.getCell("areaHa").numFmt = "#,##0.00";
  totalRow.getCell("percentage").numFmt = "0.00%";
  totalRow.getCell("proratedWeight").numFmt = "#,##0.00";
  totalRow.getCell("tch").numFmt = "#,##0.00";

  if (result.unassignedWeight > 0) {
    const warningRow = worksheet.addRow({
      farmName: "PESO SEM FAZENDA IDENTIFICADA",
      proratedWeight: result.unassignedWeight
    });
    warningRow.font = { bold: true, color: { argb: "FFB71C1C" } };
    warningRow.getCell("proratedWeight").numFmt = "#,##0.00";
  }

  res.setHeader("Content-Type", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet");
  res.setHeader("Content-Disposition", `attachment; filename="Rateio_OS_${result.orderNumber}.xlsx"`);

  await workbook.xlsx.write(res);
  res.end();
});

apportionmentRouter.get("/:orderId/export/pdf", (req, res) => {
  const result = findApportionment(req.params.orderId);
  if (!result) return res.status(404).json({ message: "OS nao encontrada" });
  assertExportRowLimit(result.fields.length);

  const doc = new PDFDocument({ margin: 40, size: "A4" });

  res.setHeader("Content-Type", "application/pdf");
  res.setHeader("Content-Disposition", `attachment; filename="Rateio_OS_${result.orderNumber}.pdf"`);

  doc.pipe(res);
  renderSingleApportionmentPdf(doc, result);
  doc.end();
});

function findApportionment(orderId: string | string[]) {
  const normalizedOrderId = Array.isArray(orderId) ? orderId[0] : orderId;
  return readApportionments().find((result) => result.orderId === normalizedOrderId) ?? null;
}
