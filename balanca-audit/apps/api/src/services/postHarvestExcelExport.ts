import ExcelJS from "exceljs";
import { systemIdentity } from "@balanca/shared";
import { db } from "../db.js";

export type PostHarvestExportSourceRow = {
  order_id: string;
  order_number: string;
  order_created_at: string;
  order_end_date: string | null;
  farm_code: string | null;
  farm_name: string;
  field_code: string | null;
  area_alq: number | null;
  area_ha: number | null;
  cane_tons?: number | null;
};

export type PostHarvestExportRow = {
  idTalhao: string;
  dataInicio: Date;
  dataFechamento: Date;
  setor: string;
  codigo: string;
  fundoAgricola: string;
  talhao: string;
  areaAlq: number;
  areaHa: number;
  caneTons: number;
  tch: number | null;
  tca: number | null;
  orderId: string;
  orderNumber: string;
};

export type PostHarvestExportIssue = {
  orderId: string;
  orderNumber: string;
  farmCode?: string | null;
  fieldCode?: string | null;
  message: string;
};

export type PostHarvestExportData = {
  rows: PostHarvestExportRow[];
  issues: PostHarvestExportIssue[];
  summary: {
    closedOrders: number;
    rowCount: number;
    invalidCount: number;
  };
};

export function readPostHarvestExportData(limit?: number): PostHarvestExportData {
  const boundedLimit = limit === undefined ? undefined : Math.min(Math.max(Math.trunc(limit), 1), 100_001);
  const limitClause = boundedLimit === undefined ? "" : "LIMIT ?";
  const sourceRows = db
    .prepare(
      `
      SELECT
        ho.id AS order_id,
        ho.number AS order_number,
        ho.created_at AS order_created_at,
        ho.end_date AS order_end_date,
        fa.code AS farm_code,
        fa.name AS farm_name,
        f.code AS field_code,
        f.area_alq,
        f.area_ha,
        COALESCE((
          SELECT SUM(ce.net_weight)
          FROM cane_entries ce
          JOIN import_batches b ON b.id = ce.batch_id
          WHERE ce.field_id = f.id
            AND ce.farm_id = fa.id
            AND (b.source_type = 'SCS0110P_PDF' OR lower(b.file_name) LIKE '%.pdf')
            AND (
              ce.order_id = ho.id
              OR (
                ce.order_id IS NULL
                AND UPPER(TRIM(COALESCE(ce.order_number_raw, ''))) = UPPER(TRIM(ho.number))
              )
            )
        ), 0) AS cane_tons
      FROM harvest_orders ho
      JOIN harvest_order_fields hof ON hof.order_id = ho.id
      JOIN fields f ON f.id = hof.field_id
      JOIN farms fa ON fa.id = f.farm_id
      WHERE ho.status = 'CLOSED'
      ORDER BY ho.end_date ASC, ho.id ASC, fa.code ASC, f.code ASC
      ${limitClause}
      `
    )
    .all(...(boundedLimit === undefined ? [] : [boundedLimit])) as PostHarvestExportSourceRow[];

  const rows: PostHarvestExportRow[] = [];
  const issues: PostHarvestExportIssue[] = [];

  for (const source of sourceRows) {
    try {
      rows.push(formatPostHarvestExportRow(source));
    } catch (error) {
      issues.push({
        orderId: source.order_id,
        orderNumber: source.order_number,
        farmCode: source.farm_code,
        fieldCode: source.field_code,
        message: error instanceof Error ? error.message : String(error)
      });
    }
  }

  rows.sort(comparePostHarvestExportRows);

  return {
    rows,
    issues,
    summary: {
      closedOrders: new Set(sourceRows.map((row) => row.order_id)).size,
      rowCount: sourceRows.length,
      invalidCount: issues.length
    }
  };
}

export function formatPostHarvestExportRow(source: PostHarvestExportSourceRow): PostHarvestExportRow {
  const farmCode = source.farm_code?.trim() ?? "";
  const match = /^(\d+)-(\d+)$/.exec(farmCode);

  if (!match) {
    throw new Error(`Codigo da fazenda invalido: ${farmCode || "vazio"}. Esperado: Setor-Codigo.`);
  }

  const setor = match[1];
  const rawCode = match[2];
  const rawField = source.field_code?.trim() ?? "";

  if (rawCode.length > 4) {
    throw new Error(`Codigo da fazenda ${farmCode} possui mais de 4 digitos depois do hifen.`);
  }

  if (!/^\d{1,4}$/.test(rawField)) {
    throw new Error(`Talhao invalido: ${rawField || "vazio"}. Esperado: ate 4 digitos numericos.`);
  }

  if (!source.farm_name.trim()) {
    throw new Error("Fundo Agricola nao informado.");
  }

  if (source.area_alq === null || !Number.isFinite(Number(source.area_alq))) {
    throw new Error("Area alq nao informada.");
  }

  if (source.area_ha === null || !Number.isFinite(Number(source.area_ha))) {
    throw new Error("Area Ha nao informada.");
  }

  if (!source.order_created_at) {
    throw new Error("Data de criacao da OS nao informada.");
  }

  if (!source.order_end_date) {
    throw new Error("Data de fechamento da OS nao informada.");
  }

  const codigo = rawCode.padStart(4, "0");
  const talhao = rawField.padStart(4, "0");
  const caneTons = Number(source.cane_tons ?? 0);
  const areaAlq = Number(source.area_alq);
  const areaHa = Number(source.area_ha);

  return {
    idTalhao: `${setor}${codigo}${talhao}`,
    dataInicio: toExcelDate(source.order_created_at),
    dataFechamento: toExcelDate(source.order_end_date),
    setor,
    codigo,
    fundoAgricola: source.farm_name.trim(),
    talhao,
    areaAlq,
    areaHa,
    caneTons,
    tch: areaHa > 0 && caneTons > 0 ? caneTons / areaHa : null,
    tca: areaAlq > 0 && caneTons > 0 ? caneTons / areaAlq : null,
    orderId: source.order_id,
    orderNumber: source.order_number
  };
}

export function buildPostHarvestExportWorkbook(rows: PostHarvestExportRow[]) {
  const workbook = new ExcelJS.Workbook();
  workbook.creator = `Operacoes Agricolas - ${systemIdentity.currentName}`;
  workbook.created = new Date();
  workbook.modified = new Date();

  buildSummaryWorksheet(workbook, rows);

  const worksheet = workbook.addWorksheet("Talhoes OS Fechadas", {
    views: [{ state: "frozen", ySplit: 1 }]
  });

  worksheet.columns = [
    { header: "ID_talhao", key: "idTalhao", width: 20 },
    { header: "Data_Inicio", key: "dataInicio", width: 16 },
    { header: "Data_Fechamento", key: "dataFechamento", width: 16 },
    { header: "Setor", key: "setor", width: 10 },
    { header: "Codigo", key: "codigo", width: 12 },
    { header: "Fundo Agricola", key: "fundoAgricola", width: 42 },
    { header: "Talhao", key: "talhao", width: 12 },
    { header: "Area alq", key: "areaAlq", width: 14 },
    { header: "Area Ha", key: "areaHa", width: 14 }
  ];

  for (const row of rows) {
    worksheet.addRow({
      idTalhao: row.idTalhao,
      dataInicio: row.dataInicio,
      dataFechamento: row.dataFechamento,
      setor: row.setor,
      codigo: row.codigo,
      fundoAgricola: row.fundoAgricola,
      talhao: row.talhao,
      areaAlq: row.areaAlq,
      areaHa: row.areaHa
    });
  }

  stylePostHarvestWorksheet(worksheet);
  buildHarvestDetailsWorksheet(workbook, rows);
  return workbook;
}

function buildHarvestDetailsWorksheet(workbook: ExcelJS.Workbook, rows: PostHarvestExportRow[]) {
  const worksheet = workbook.addWorksheet("Colheita por Talhao", {
    views: [{ state: "frozen", ySplit: 1 }]
  });

  worksheet.columns = [
    { header: "ID_talhao", key: "idTalhao", width: 20 },
    { header: "OS", key: "orderNumber", width: 16 },
    { header: "Fundo Agricola", key: "fundoAgricola", width: 42 },
    { header: "Talhao", key: "talhao", width: 12 },
    { header: "Data_Fechamento", key: "dataFechamento", width: 18 },
    { header: "Cana Entregue (t)", key: "caneTons", width: 20 },
    { header: "TCH (t/ha)", key: "tch", width: 16 },
    { header: "TCA (t/alq)", key: "tca", width: 16 }
  ];

  for (const row of rows) {
    worksheet.addRow({
      idTalhao: row.idTalhao,
      orderNumber: row.orderNumber,
      fundoAgricola: row.fundoAgricola,
      talhao: row.talhao,
      dataFechamento: row.dataFechamento,
      caneTons: row.caneTons,
      tch: row.tch,
      tca: row.tca
    });
  }

  // Add totals row
  worksheet.addRow({
    fundoAgricola: "TOTAL GERAL",
    caneTons: rows.reduce((sum, r) => sum + r.caneTons, 0)
  });
  worksheet.lastRow!.font = { bold: true };
  worksheet.lastRow!.fill = { type: "pattern", pattern: "solid", fgColor: { argb: "FFEAF3FA" } };

  styleHarvestDetailsWorksheet(worksheet);
}

function buildSummaryWorksheet(workbook: ExcelJS.Workbook, rows: PostHarvestExportRow[]) {
  const worksheet = workbook.addWorksheet("Resumo Safra", {
    views: [{ state: "frozen", xSplit: 0, ySplit: 0 }]
  });

  const totalCane = rows.reduce((sum, row) => sum + row.caneTons, 0);
  const totalHa = rows.reduce((sum, row) => sum + row.areaHa, 0);
  const totalAlq = rows.reduce((sum, row) => sum + row.areaAlq, 0);
  const tchGlobal = totalHa > 0 ? totalCane / totalHa : 0;
  const tcaGlobal = totalAlq > 0 ? totalCane / totalAlq : 0;
  const closedOrders = new Set(rows.map(r => r.orderId)).size;

  const farmStats = new Map<string, { cane: number, ha: number }>();
  for (const row of rows) {
    const stats = farmStats.get(row.fundoAgricola) || { cane: 0, ha: 0 };
    stats.cane += row.caneTons;
    stats.ha += row.areaHa;
    farmStats.set(row.fundoAgricola, stats);
  }

  const topFarms = Array.from(farmStats.entries())
    .map(([farm, stats]) => ({ farm, tch: stats.ha > 0 ? stats.cane / stats.ha : 0 }))
    .sort((a, b) => b.tch - a.tch)
    .slice(0, 10);

  worksheet.columns = [
    { width: 35 },
    { width: 25 },
    { width: 5 },
    { width: 45 },
    { width: 20 }
  ];

  worksheet.getCell("A1").value = "RESUMO GERAL DO RATEIO";
  worksheet.getCell("A1").font = { size: 16, bold: true, color: { argb: "FF14532D" } };
  worksheet.mergeCells("A1:B1");

  worksheet.addRow([]);
  worksheet.addRow(["Total de OS Fechadas:", closedOrders]).getCell(1).font = { bold: true };
  worksheet.lastRow!.getCell(2).numFmt = "0";

  worksheet.addRow(["Total Cana Entregue (t):", totalCane]).getCell(1).font = { bold: true };
  worksheet.lastRow!.getCell(2).numFmt = "#,##0.00";
  worksheet.lastRow!.getCell(2).font = { bold: true, color: { argb: "FF14532D" } };

  worksheet.addRow(["Área Total Colhida (ha):", totalHa]).getCell(1).font = { bold: true };
  worksheet.lastRow!.getCell(2).numFmt = "#,##0.00";

  worksheet.addRow(["TCH Global Médio (t/ha):", tchGlobal]).getCell(1).font = { bold: true };
  worksheet.lastRow!.getCell(2).numFmt = "#,##0.00";
  worksheet.lastRow!.getCell(2).font = { bold: true, color: { argb: "FF1D55A6" } };

  worksheet.addRow(["TCA Global Médio (t/alq):", tcaGlobal]).getCell(1).font = { bold: true };
  worksheet.lastRow!.getCell(2).numFmt = "#,##0.00";
  worksheet.lastRow!.getCell(2).font = { bold: true, color: { argb: "FF1D55A6" } };

  worksheet.getCell("D1").value = "RANKING DE FAZENDAS (Melhor TCH)";
  worksheet.getCell("D1").font = { size: 14, bold: true, color: { argb: "FF14532D" } };
  worksheet.mergeCells("D1:E1");

  worksheet.getCell("D2").value = "Fundo Agrícola";
  worksheet.getCell("D2").font = { bold: true, color: { argb: "FFFFFFFF" } };
  worksheet.getCell("D2").fill = { type: "pattern", pattern: "solid", fgColor: { argb: "FF1E3A5F" } };
  worksheet.getCell("E2").value = "TCH Médio (t/ha)";
  worksheet.getCell("E2").font = { bold: true, color: { argb: "FFFFFFFF" } };
  worksheet.getCell("E2").fill = { type: "pattern", pattern: "solid", fgColor: { argb: "FF1E3A5F" } };
  worksheet.getCell("E2").alignment = { horizontal: "center" };

  let r = 3;
  for (const f of topFarms) {
    worksheet.getCell(`D${r}`).value = f.farm;
    worksheet.getCell(`E${r}`).value = f.tch;
    worksheet.getCell(`E${r}`).numFmt = "#,##0.00";
    worksheet.getCell(`E${r}`).alignment = { horizontal: "center" };
    // Highlight top 3
    if (r <= 5) {
      worksheet.getCell(`D${r}`).font = { bold: true, color: { argb: "FF2E7D32" } };
      worksheet.getCell(`E${r}`).font = { bold: true, color: { argb: "FF2E7D32" } };
    }
    r++;
  }
}

function styleHarvestDetailsWorksheet(worksheet: ExcelJS.Worksheet) {
  const header = worksheet.getRow(1);
  header.font = { bold: true, color: { argb: "FFFFFFFF" } };
  header.fill = { type: "pattern", pattern: "solid", fgColor: { argb: "FF1E3A5F" } };
  header.alignment = { vertical: "middle", horizontal: "center" };
  header.height = 24;

  for (const column of ["A", "B", "D"]) {
    worksheet.getColumn(column).numFmt = "@";
  }
  worksheet.getColumn("E").numFmt = "dd/mm/yyyy";
  for (const column of ["F", "G", "H"]) {
    worksheet.getColumn(column).numFmt = "#,##0.00";
  }

  worksheet.autoFilter = "A1:H1";
  worksheet.eachRow((row, rowNumber) => {
    if (rowNumber > 1) row.height = 20;
    row.eachCell({ includeEmpty: true }, (cell, columnNumber) => {
      cell.border = {
        top: { style: "thin", color: { argb: "FFD7DED9" } },
        left: { style: "thin", color: { argb: "FFD7DED9" } },
        bottom: { style: "thin", color: { argb: "FFD7DED9" } },
        right: { style: "thin", color: { argb: "FFD7DED9" } }
      };
      if (rowNumber > 1 && cell.value !== "TOTAL GERAL") {
        cell.alignment = {
          vertical: "middle",
          horizontal: columnNumber === 3 ? "left" : "center",
          wrapText: columnNumber === 3
        };

        // Color-code TCH (column 7) and TCA (column 8)
        if (columnNumber === 7 || columnNumber === 8) {
           const val = Number(cell.value);
           if (val > 80) {
             cell.font = { color: { argb: "FF2E7D32" }, bold: true }; // Green for good yield
           } else if (val > 0 && val < 60) {
             cell.font = { color: { argb: "FFB71C1C" }, bold: true }; // Red for poor yield
           }
        }
      }
    });
  });
}

function stylePostHarvestWorksheet(worksheet: ExcelJS.Worksheet) {
  const header = worksheet.getRow(1);
  header.font = { bold: true, color: { argb: "FFFFFFFF" } };
  header.fill = { type: "pattern", pattern: "solid", fgColor: { argb: "FF14532D" } };
  header.alignment = { vertical: "middle", horizontal: "center" };
  header.height = 24;

  for (const column of ["A", "D", "E", "G"]) {
    worksheet.getColumn(column).numFmt = "@";
  }

  for (const column of ["B", "C"]) {
    worksheet.getColumn(column).numFmt = "dd/mm/yyyy";
  }

  for (const column of ["H", "I"]) {
    worksheet.getColumn(column).numFmt = "#,##0.00";
  }

  worksheet.autoFilter = "A1:I1";

  worksheet.eachRow((row, rowNumber) => {
    if (rowNumber > 1) {
      row.height = 20;
    }

    row.eachCell({ includeEmpty: true }, (cell, columnNumber) => {
      cell.border = {
        top: { style: "thin", color: { argb: "FFD7DED9" } },
        left: { style: "thin", color: { argb: "FFD7DED9" } },
        bottom: { style: "thin", color: { argb: "FFD7DED9" } },
        right: { style: "thin", color: { argb: "FFD7DED9" } }
      };

      if (rowNumber > 1) {
        cell.alignment = {
          vertical: "middle",
          horizontal: columnNumber === 6 ? "left" : "center",
          wrapText: columnNumber === 6
        };
      }
    });
  });
}

function comparePostHarvestExportRows(left: PostHarvestExportRow, right: PostHarvestExportRow) {
  return (
    Number(left.setor) - Number(right.setor) ||
    Number(left.codigo) - Number(right.codigo) ||
    Number(left.talhao) - Number(right.talhao) ||
    left.dataFechamento.getTime() - right.dataFechamento.getTime() ||
    left.orderNumber.localeCompare(right.orderNumber, "pt-BR", { numeric: true })
  );
}

function toExcelDate(value: string) {
  const dateOnly = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value.trim());

  if (dateOnly) {
    return new Date(Number(dateOnly[1]), Number(dateOnly[2]) - 1, Number(dateOnly[3]));
  }

  const parsed = new Date(value.includes("T") ? value : value.replace(" ", "T"));

  if (Number.isNaN(parsed.getTime())) {
    throw new Error(`Data invalida: ${value}`);
  }

  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: "America/Sao_Paulo",
    year: "numeric",
    month: "2-digit",
    day: "2-digit"
  }).formatToParts(parsed);
  const year = Number(parts.find((part) => part.type === "year")?.value);
  const month = Number(parts.find((part) => part.type === "month")?.value);
  const day = Number(parts.find((part) => part.type === "day")?.value);

  if (!year || !month || !day) {
    throw new Error(`Data invalida: ${value}`);
  }

  return new Date(year, month - 1, day);
}
