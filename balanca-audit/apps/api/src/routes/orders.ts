import { Router } from "express";
import PDFDocument from "pdfkit";
import multer from "multer";
import fs from "node:fs/promises";
import { bulkCloseOrdersSchema, createOrderSchema, systemIdentity, type CreateOrderInput, updateOrderSchema } from "@balanca/shared";
import {
  countOrderHistory,
  countExistingFields,
  createOrder,
  db,
  deleteOrder,
  findActiveOrderForFront,
  findOrderById,
  listOrderHistory,
  listOrders,
  listOrdersByYear,
  reopenOrder,
  removeOrderFarm,
  updateOrder
} from "../db.js";
import { reconcileRetroactiveEntriesForOrder } from "../services/importer.js";
import { commitOrderImport, previewOrderImport } from "../services/orderImport.js";
import { assertUploadedFile } from "../services/uploadValidation.js";
import { paginateList, readPagination } from "../httpPagination.js";
import { requireRoles } from "../middleware/requireAuth.js";
import { closeOrderAndReleasePostHarvest } from "../services/postHarvestIntegrationService.js";
import { env } from "../env.js";
import { assertExportRowLimit } from "../services/exportControl.js";


const upload = multer({
  dest: env.uploadDir,
  limits: {
    fileSize: 10 * 1024 * 1024
  }
});

export const ordersRouter = Router();
const manageOrdersOnly = requireRoles(["ADMIN", "ANALYST"]);






ordersRouter.post("/import-excel/preview", manageOrdersOnly, upload.single("file"), async (req, res) => {
  if (!req.file) {
    return res.status(400).json({ message: "Nenhum arquivo enviado." });
  }

  try {
    await assertUploadedFile(req.file, [".xlsx"], "Envie uma planilha XLSX valida.");
    return res.json(await previewOrderImport(req.file.path, req.file.originalname));
  } finally {
    await fs.unlink(req.file.path).catch(() => undefined);
  }
});

ordersRouter.post("/import-excel", manageOrdersOnly, upload.single("file"), async (req, res) => {
  if (!req.file) {
    return res.status(400).json({ message: "Nenhum arquivo enviado." });
  }

  try {
    await assertUploadedFile(req.file, [".xlsx"], "Envie uma planilha XLSX valida.");
    const previewHash = typeof req.body?.previewHash === "string" ? req.body.previewHash.trim() : "";
    return res.json(await commitOrderImport(req.file.path, req.file.originalname, previewHash));
  } finally {
    await fs.unlink(req.file.path).catch(() => undefined);
  }
});

ordersRouter.get("/", async (req, res) => {
  const yearParam = req.query.year ? Number(req.query.year) : undefined;
  const orders = yearParam ? listOrdersByYear(yearParam) : listOrders();
  const pagination = readPagination(req.query, { defaultLimit: 200, maxLimit: 2000 });

  if (pagination.requested) {
    const page = paginateList(orders, pagination);
    return res.json({ orders: page.items, total: page.total, limit: page.limit, offset: page.offset });
  }

  return res.json({ orders });
});

ordersRouter.get("/report.pdf", async (_req, res) => {
  const orders = listOrders();
  assertExportRowLimit(orders.reduce((total, order) => total + Math.max(1, order.fields.length), 0));
  const pdf = await buildHarvestReportPdf(orders);

  res.setHeader("Content-Type", "application/pdf");
  res.setHeader("Content-Disposition", 'attachment; filename="relatorio-fazendas-colheita.pdf"');
  return res.send(pdf);
});

ordersRouter.get("/summary-report.pdf", async (_req, res) => {
  const orders = listOrders();
  assertExportRowLimit(orders.reduce((total, order) => total + Math.max(1, order.fields.length), 0));
  const pdf = await buildHarvestSummaryReportPdf(orders);

  res.setHeader("Content-Type", "application/pdf");
  res.setHeader("Content-Disposition", 'attachment; filename="relatorio-resumido-fazendas.pdf"');
  return res.send(pdf);
});

ordersRouter.get("/history", async (req, res) => {
  const pagination = readPagination(req.query, { defaultLimit: 200, maxLimit: 2000 });
  const history = listOrderHistory(pagination.limit, pagination.offset);
  const total = countOrderHistory();

  return res.json({ history, total, limit: pagination.limit, offset: pagination.offset });
});

ordersRouter.post("/", manageOrdersOnly, async (req, res) => {
  const input = createOrderSchema.safeParse(req.body);

  if (!input.success) {
    return res.status(400).json({ message: "Cadastro de talhoes em colheita invalido." });
  }

  const validation = validateOrderInput(input.data);

  if (validation) {
    return res.status(validation.status).json({ message: validation.message });
  }

  const order = createOrder({
    number: input.data.number,
    frontNumber: input.data.frontNumber,
    frontNumbers: input.data.frontNumbers,
    farmId: input.data.farmId,
    fieldIds: input.data.fieldIds,
    startDate: input.data.startDate,
    endDate: input.data.endDate
  });

  if (order) {
    const farms = order.farms?.length ? order.farms : (order.farm ? [order.farm] : []);
    const farmIds = Array.from(new Set(farms.map((f: any) => f.id).filter(Boolean)));
    for (const farmId of farmIds) {
      reconcileRetroactiveEntriesForOrder(farmId).catch((err) => {
        console.error(`Falha ao conciliar entradas retroativas do PDF (fazenda ${farmId}):`, err);
      });
    }
  }

  return res.status(201).json({ order });
});

ordersRouter.post("/bulk-close", manageOrdersOnly, async (req, res) => {
  const input = bulkCloseOrdersSchema.safeParse(req.body);

  if (!input.success) {
    return res.status(400).json({ message: "Informe uma ou mais OS para encerramento." });
  }

  const requestedNumbers = normalizeBulkOrderNumbers(input.data.numbers);

  if (requestedNumbers.length === 0) {
    return res.status(400).json({ message: "Informe uma ou mais OS para encerramento." });
  }

  const orders = listOrders();
  const results = requestedNumbers.map((number) => {
    const matchingOrders = orders.filter((order) => normalizeOrderNumber(order.number) === normalizeOrderNumber(number));

    if (matchingOrders.length === 0) {
      return {
        number,
        status: "NOT_FOUND" as const,
        message: "OS nao encontrada."
      };
    }

    const activeOrders = matchingOrders.filter((order) => order.status === "ACTIVE");

    if (activeOrders.length === 0) {
      return {
        number,
        status: "ALREADY_CLOSED" as const,
        orderIds: matchingOrders.map((order) => order.id),
        fronts: Array.from(new Set(matchingOrders.flatMap(getOrderFrontNumbers))).sort((left, right) => left - right),
        farms: Array.from(new Set(matchingOrders.flatMap((order) => getOrderFarms(order).map(formatFarmLabel)))),
        message: "OS ja estava fechada."
      };
    }

    const closeResults = activeOrders
      .map((order) => closeOrderAndReleasePostHarvest(order.id))
      .filter((result): result is NonNullable<typeof result> => Boolean(result));
    const closedOrders = closeResults.map((result) => result.order);
    const integrationEvents = closeResults.flatMap((result) => result.events);

    return {
      number,
      status: "CLOSED" as const,
      orderIds: closedOrders.map((order) => order.id),
      fronts: Array.from(new Set(closedOrders.flatMap(getOrderFrontNumbers))).sort((left, right) => left - right),
      farms: Array.from(new Set(closedOrders.flatMap((order) => getOrderFarms(order).map(formatFarmLabel)))),
      closedCount: closedOrders.length,
      integrationEventCount: integrationEvents.length,
      message: closedOrders.length === 1 ? "OS fechada." : `${closedOrders.length} registros da OS foram fechados.`
    };
  });

  return res.json({
    results,
    summary: {
      total: results.length,
      closed: results.filter((item) => item.status === "CLOSED").length,
      alreadyClosed: results.filter((item) => item.status === "ALREADY_CLOSED").length,
      notFound: results.filter((item) => item.status === "NOT_FOUND").length
    }
  });
});

ordersRouter.put("/:orderId", manageOrdersOnly, async (req, res) => {
  const orderId = routeParam(req.params.orderId);
  const input = updateOrderSchema.safeParse(req.body);

  if (!input.success) {
    return res.status(400).json({ message: "Cadastro de talhoes em colheita invalido." });
  }

  const currentOrder = findOrderById(orderId);

  if (!currentOrder) {
    return res.status(404).json({ message: "Colheita nao encontrada." });
  }

  // OS encerradas podem ser editadas (apenas talhoes/fazenda), sem validar conflito de frente
  if (currentOrder.status === "ACTIVE") {
    const validation = validateOrderInput(input.data, currentOrder.id);
    if (validation) {
      return res.status(validation.status).json({ message: validation.message });
    }
  } else {
    // Para OS encerradas: apenas valida que os talhoes existem no cadastro
    const fieldCount = countExistingFields(input.data.fieldIds);
    if (fieldCount !== input.data.fieldIds.length) {
      return res.status(400).json({ message: "A OS tem talhoes que nao foram encontrados no cadastro." });
    }
  }

  const order = updateOrder(currentOrder.id, input.data);

  if (order) {
    const farms = order.farms?.length ? order.farms : (order.farm ? [order.farm] : []);
    const farmIds = Array.from(new Set(farms.map((f: any) => f.id).filter(Boolean)));
    for (const farmId of farmIds) {
      reconcileRetroactiveEntriesForOrder(farmId).catch((err) => {
        console.error(`Falha ao conciliar entradas retroativas do PDF (fazenda ${farmId}):`, err);
      });
    }
  }

  return res.json({ order });
});

ordersRouter.patch("/:orderId/close", manageOrdersOnly, async (req, res) => {
  const currentOrder = findOrderById(routeParam(req.params.orderId));

  if (!currentOrder) {
    return res.status(404).json({ message: "Colheita nao encontrada." });
  }

  if (currentOrder.status === "CLOSED") {
    return res.json({ order: currentOrder });
  }

  const result = closeOrderAndReleasePostHarvest(currentOrder.id);
  const order = result?.order ?? null;
  const integrationEvents = result?.events ?? [];

  return res.json({ order, integrationEvents });
});

ordersRouter.patch("/:orderId/reopen", manageOrdersOnly, async (req, res) => {
  const currentOrder = findOrderById(routeParam(req.params.orderId));

  if (!currentOrder) {
    return res.status(404).json({ message: "Colheita nao encontrada." });
  }

  if (currentOrder.status === "ACTIVE") {
    return res.json({ order: currentOrder });
  }

  const validation = validateOrderReopen(currentOrder);

  if (validation) {
    return res.status(validation.status).json({ message: validation.message });
  }

  const order = reopenOrder(currentOrder.id);

  return res.json({ order });
});

ordersRouter.delete("/:orderId", manageOrdersOnly, async (req, res) => {
  const currentOrder = findOrderById(routeParam(req.params.orderId));

  if (!currentOrder) {
    return res.status(404).json({ message: "Colheita nao encontrada." });
  }

  deleteOrder(currentOrder.id);

  return res.status(204).send();
});

ordersRouter.delete("/:orderId/farms/:farmId", manageOrdersOnly, async (req, res) => {
  const orderId = routeParam(req.params.orderId);
  const farmId = routeParam(req.params.farmId);
  const currentOrder = findOrderById(orderId);

  if (!currentOrder) {
    return res.status(404).json({ message: "Colheita nao encontrada." });
  }

  if (currentOrder.status !== "ACTIVE") {
    return res.status(409).json({ message: "Colheita finalizada nao pode ser editada." });
  }

  const orderFarms = getOrderFarms(currentOrder);
  const targetFarm = orderFarms.find((farm) => farm.id === farmId);

  if (!targetFarm) {
    return res.status(404).json({ message: "Fazenda nao esta vinculada a esta OS." });
  }

  if (orderFarms.length <= 1) {
    return res.status(409).json({
      message: "A OS precisa manter pelo menos uma fazenda. Para remover a ultima, exclua a colheita inteira."
    });
  }

  const targetFieldCount = currentOrder.fields.filter((item) => item.field.farmId === farmId).length;

  if (targetFieldCount === 0) {
    return res.status(409).json({ message: "Fazenda nao possui talhoes vinculados nesta OS." });
  }

  const result = removeOrderFarm(currentOrder.id, farmId);

  if (!result) {
    return res.status(404).json({ message: "Colheita nao encontrada." });
  }

  return res.json({
    order: result.order,
    removedFarm: {
      id: targetFarm.id,
      code: targetFarm.code ?? null,
      name: targetFarm.name,
      fieldCount: result.removedFieldCount
    },
    unlinkedDocumentCount: result.unlinkedDocumentCount,
    reclassifiedEntryCount: result.reclassifiedEntryCount
  });
});

function validateOrderInput(input: CreateOrderInput, ignoredOrderId?: string) {
  const frontNumbers = normalizeOrderFrontNumbers(input.frontNumbers, input.frontNumber);

  const existingOrder = listOrders().find((order) => {
    if (order.status !== "ACTIVE") return false;
    if (order.id === ignoredOrderId) return false;
    if (normalizeOrderNumber(order.number) !== normalizeOrderNumber(input.number)) return false;

    const orderFronts = getOrderFrontNumbers(order);

    if (frontNumbers.length === 0 && orderFronts.length === 0) {
      return true;
    }
    if (frontNumbers.length > 0 && orderFronts.length > 0) {
      return frontNumbers.some((front) => orderFronts.includes(front));
    }
    return false;
  });

  if (existingOrder) {
    const existingFronts = getOrderFrontNumbers(existingOrder);
    const frontText = existingFronts.length > 0 ? ` para a ${formatFrontNumbers(existingFronts)}` : " sem frente";
    return {
      status: 409,
      message: `OS ${input.number} ja esta cadastrada${frontText}. Edite a OS existente para alterar fazendas, talhoes ou frentes.`
    };
  }

  const fieldCount = countExistingFields(input.fieldIds);

  if (fieldCount !== input.fieldIds.length) {
    return {
      status: 400,
      message: "A OS tem talhoes que nao foram encontrados no cadastro."
    };
  }

  for (const frontNumber of frontNumbers) {
    const activeFrontOrder = findActiveOrderForFront(frontNumber, ignoredOrderId);

    if (activeFrontOrder) {
      return {
        status: 409,
        message: `Frente ${frontNumber} ja esta em colheita na OS ${activeFrontOrder.number}. Finalize ou edite essa colheita antes de cadastrar outra.`
      };
    }
  }

  return null;
}

function validateOrderReopen(order: HarvestOrder) {
  const orderFronts = getOrderFrontNumbers(order);

  const existingOrder = listOrders().find((item) => {
    if (item.status !== "ACTIVE") return false;
    if (item.id === order.id) return false;
    if (normalizeOrderNumber(item.number) !== normalizeOrderNumber(order.number)) return false;

    const itemFronts = getOrderFrontNumbers(item);

    if (orderFronts.length === 0 && itemFronts.length === 0) {
      return true;
    }
    if (orderFronts.length > 0 && itemFronts.length > 0) {
      return orderFronts.some((front) => itemFronts.includes(front));
    }
    return false;
  });

  if (existingOrder) {
    const existingFronts = getOrderFrontNumbers(existingOrder);
    const frontText = existingFronts.length > 0 ? ` para a ${formatFrontNumbers(existingFronts)}` : " sem frente";
    return {
      status: 409,
      message: `OS ${order.number} ja esta aberta em outro registro${frontText}. Edite ou finalize a OS ativa antes de reabrir esta.`
    };
  }

  for (const frontNumber of orderFronts) {
    const activeFrontOrder = findActiveOrderForFront(frontNumber, order.id);

    if (activeFrontOrder) {
      return {
        status: 409,
        message: `Frente ${frontNumber} ja esta em colheita na OS ${activeFrontOrder.number}. Finalize ou edite essa colheita antes de reabrir esta OS.`
      };
    }
  }

  return null;
}

function normalizeOrderFrontNumbers(frontNumbers?: number[], frontNumber?: number | null) {
  return Array.from(new Set([...(frontNumbers ?? []), ...(frontNumber ? [frontNumber] : [])])).sort(
    (left, right) => left - right
  );
}

function normalizeOrderNumber(value: string) {
  return value
    .normalize("NFD")
    .replace(/\p{Diacritic}/gu, "")
    .trim()
    .toUpperCase();
}

function normalizeBulkOrderNumbers(numbers: string[]) {
  const seen = new Set<string>();
  const normalizedNumbers: string[] = [];

  for (const number of numbers) {
    const trimmed = number.trim();
    const normalized = normalizeOrderNumber(trimmed);

    if (!trimmed || seen.has(normalized)) {
      continue;
    }

    seen.add(normalized);
    normalizedNumbers.push(trimmed);
  }

  return normalizedNumbers;
}

function routeParam(value: string | string[]) {
  return Array.isArray(value) ? value[0] : value;
}

type HarvestOrder = ReturnType<typeof listOrders>[number];
type FarmFieldGroup = {
  farm: HarvestOrder["farm"];
  fields: string[];
  fieldIds: string[];
};
type CurrentFarmReportRow = {
  order: HarvestOrder;
  fronts: number[];
  group: FarmFieldGroup;
};
type ClosedFarmReportRow = {
  farm: HarvestOrder["farm"];
  orders: HarvestOrder[];
  fields: string[];
  fieldIds: string[];
  metrics: ClosedFarmHarvestMetrics;
};
type ClosedFarmHarvestMetrics = {
  fields: ClosedFarmHarvestFieldMetric[];
  areaHa: number;
  areaAlq: number;
  caneTons: number;
  tch: number | null;
  tca: number | null;
};
type ClosedFarmHarvestFieldMetric = {
  fieldCode: string;
  areaHa: number;
  areaAlq: number;
  caneTons: number;
  tch: number | null;
  tca: number | null;
};
type CurrentFarmSummaryReportRow = {
  farm: HarvestOrder["farm"];
  fronts: number[];
};
type RowOptions = {
  repeatHeader?: () => void;
  shaded?: boolean;
  pageBreakValues?: string[];
};

const harvestFronts = new Set(Array.from({ length: 14 }, (_, index) => index + 1));

const reportColors = {
  text: "#17202a",
  muted: "#647183",
  border: "#dce2e8",
  header: "#f3f6f8",
  green: "#26734d",
  danger: "#9b1c1c"
};

async function buildHarvestReportPdf(orders: HarvestOrder[]) {
  const doc = new PDFDocument({
    size: "A4",
    layout: "landscape",
    margin: 30,
    bufferPages: true,
    info: {
      Title: "Relatório de Fazendas da Colheita",
      Author: systemIdentity.currentName
    }
  });
  const chunks: Buffer[] = [];
  const done = new Promise<Buffer>((resolve, reject) => {
    doc.on("data", (chunk: Buffer) => chunks.push(Buffer.from(chunk)));
    doc.on("end", () => resolve(Buffer.concat(chunks)));
    doc.on("error", reject);
  });

  const generatedAt = formatDateTime(new Date().toISOString());
  const activeOrders = orders.filter((order) => order.status === "ACTIVE").sort(compareOrdersByFront);
  const currentFarmRows = buildCurrentFarmRows(activeOrders);
  const activeFarmIds = new Set(activeOrders.flatMap((order) => getOrderFarms(order).map((farm) => farm.id)));
  const closedOrders = orders.filter((order) => order.status === "CLOSED").sort(compareOrdersByClosedDate);
  const closedFarmRows = buildClosedFarmRows(closedOrders, activeFarmIds);

  drawHarvestReportHeader(doc, activeOrders, currentFarmRows, closedFarmRows, generatedAt);
  drawCurrentFarmsSection(doc, currentFarmRows);
  if (closedFarmRows.length > 0) {
    startNewReportPage(doc);
  }
  drawClosedFarmsSummarySection(doc, closedFarmRows);
  if (closedFarmRows.length > 0) {
    startNewReportPage(doc);
  }
  drawClosedFarmsSection(doc, closedFarmRows);
  addPageFooters(doc, generatedAt);
  doc.end();

  return done;
}

async function buildHarvestSummaryReportPdf(orders: HarvestOrder[]) {
  const doc = new PDFDocument({
    size: "A4",
    layout: "landscape",
    margin: 30,
    bufferPages: true,
    info: {
      Title: "Relatorio Resumido de Fazendas",
      Author: systemIdentity.currentName
    }
  });
  const chunks: Buffer[] = [];
  const done = new Promise<Buffer>((resolve, reject) => {
    doc.on("data", (chunk: Buffer) => chunks.push(Buffer.from(chunk)));
    doc.on("end", () => resolve(Buffer.concat(chunks)));
    doc.on("error", reject);
  });

  const generatedAt = formatDateTime(new Date().toISOString());
  const activeOrders = orders
    .filter((order) => order.status === "ACTIVE")
    .sort(compareOrdersByFront);
  const currentRows = buildCurrentFarmSummaryRows(activeOrders);

  doc.font("Helvetica-Bold").fontSize(17).fillColor(reportColors.text).text("Relatorio resumido de fazendas", 30, 28);
  doc.y = 64;

  drawCurrentFarmSummarySection(doc, currentRows);
  addPageFooters(doc, generatedAt);
  doc.end();

  return done;
}

function drawHarvestReportHeader(
  doc: PDFKit.PDFDocument,
  activeOrders: HarvestOrder[],
  currentFarmRows: CurrentFarmReportRow[],
  closedFarmRows: ClosedFarmReportRow[],
  _generatedAt: string
) {
  const activeFrontCount = activeOrders.reduce((total, order) => total + getOrderFrontNumbers(order).length, 0);
  const activeFarmCount = new Set(currentFarmRows.map((row) => row.group.farm.id)).size;

  doc.font("Helvetica-Bold").fontSize(17).fillColor(reportColors.text).text("Relatório de fazendas da colheita", 30, 28);
  const cards = [
    ["Frentes em colheita", activeFrontCount],
    ["OS em colheita", activeOrders.length],
    ["Fazendas atuais", activeFarmCount],
    ["Fazendas encerradas", closedFarmRows.length]
  ] as const;

  cards.forEach(([label, value], index) => {
    const x = 30 + index * 156;
    doc.roundedRect(x, 76, 146, 44, 5).fillAndStroke("#f8fafb", reportColors.border);
    doc.font("Helvetica").fontSize(8).fillColor(reportColors.muted).text(label, x + 10, 85, { width: 126 });
    doc.font("Helvetica-Bold").fontSize(14).fillColor(index === 3 ? reportColors.danger : reportColors.text).text(String(value), x + 10, 100, {
      width: 126
    });
  });

  doc.y = 142;
}

function drawCurrentFarmSummarySection(doc: PDFKit.PDFDocument, rows: CurrentFarmSummaryReportRow[]) {
  const title = "Fazendas atuais";
  ensureSpace(doc, 64);
  drawSectionTitle(doc, title);

  const labels = ["FRENTE", "COD. FAZENDA", "NOME DA FAZENDA", "MUNICIPIO FICTICIO"];
  const widths = [72, 112, 340, 256];
  const repeatHeader = () => {
    drawSectionTitle(doc, title, "continuacao");
    drawTableHeader(doc, labels, widths);
  };

  drawTableHeader(doc, labels, widths);

  if (rows.length === 0) {
    drawSimpleRow(doc, ["-", "-", "Nenhuma fazenda ativa para listar.", ""], widths);
    doc.y += 12;
    return;
  }

  rows.forEach((row, index) => {
    drawSimpleRow(
      doc,
      [
        formatFrontNumberValues(row.fronts),
        formatFarmCode(row.farm),
        row.farm.name.toLocaleUpperCase("pt-BR"),
        formatFarmLocation(row.farm)
      ],
      widths,
      {
        repeatHeader,
        shaded: index % 2 === 1
      }
    );
  });

  doc.y += 12;
}

function drawCurrentFarmsSection(doc: PDFKit.PDFDocument, rows: CurrentFarmReportRow[]) {
  ensureSpace(doc, 64);
  drawSectionTitle(doc, "Fazendas atuais");

  const labels = ["Frentes", "OS", "Fazenda", "Talhões colhendo"];
  const widths = [92, 64, 270, 354];
  const repeatHeader = () => {
    drawSectionTitle(doc, "Fazendas atuais", "continuação");
    drawTableHeader(doc, labels, widths);
  };

  drawTableHeader(doc, labels, widths);

  if (rows.length === 0) {
    drawSimpleRow(doc, ["Nenhuma OS ativa no momento."], [780]);
    doc.y += 12;
    return;
  }

  rows.forEach(({ order, fronts, group }, index) => {
    drawSimpleRow(doc, [formatFrontNumbers(fronts), order.number, formatFarmLabel(group.farm), group.fields.join(", ") || "-"], widths, {
      repeatHeader,
      shaded: index % 2 === 1
    });
  });

  doc.y += 12;
}

function drawClosedFarmsSummarySection(doc: PDFKit.PDFDocument, rows: ClosedFarmReportRow[]) {
  ensureSpace(doc, 64);
  drawSectionTitle(doc, "Fazendas encerradas - resumo por OS e fazenda", "ordenadas por data de fechamento");

  if (rows.length > 0) {
    drawClosedTotalsCards(doc, rows);
  }

  const labels = ["Fazenda", "OS", "Fechamento", "Talhoes", "Cana entregue", "Hectare", "Alqueire", "TCH / TCA"];
  const widths = [210, 95, 90, 110, 85, 65, 60, 65];
  const repeatHeader = () => {
    drawSectionTitle(doc, "Fazendas encerradas - resumo por OS e fazenda", "continuacao por data de fechamento");
    drawTableHeader(doc, labels, widths);
  };

  drawTableHeader(doc, labels, widths);

  if (rows.length === 0) {
    drawSimpleRow(doc, ["Nenhuma fazenda encerrada registrada."], [780]);
    doc.y += 12;
    return;
  }

  rows.forEach(({ farm, orders, fields, metrics }, index) => {
    drawSimpleRow(
      doc,
      [
        formatFarmLabel(farm),
        formatOrderList(orders),
        formatClosedDateList(orders),
        formatFieldList(fields),
        formatNumber(metrics.caneTons),
        formatNumber(metrics.areaHa),
        formatNumber(metrics.areaAlq),
        formatAverageMetrics(metrics)
      ],
      widths,
      {
        repeatHeader,
        shaded: index % 2 === 1
      }
    );
  });

  doc.y += 12;
}

function drawClosedFarmsSection(doc: PDFKit.PDFDocument, rows: ClosedFarmReportRow[]) {
  ensureSpace(doc, 64);
  drawSectionTitle(doc, "Fazendas encerradas - detalhado por talhao", "ordenadas por data de fechamento");

  const labels = ["Fazenda", "Talhao", "OS", "Fechamento", "Cana entregue", "Hectare", "Alqueire", "TCH / TCA"];
  const widths = [220, 50, 85, 90, 85, 70, 65, 115];
  const repeatHeader = () => {
    drawSectionTitle(doc, "Fazendas encerradas - detalhado por talhao", "continuacao por data de fechamento");
    drawTableHeader(doc, labels, widths);
  };

  drawTableHeader(doc, labels, widths);

  if (rows.length === 0) {
    drawSimpleRow(doc, ["Nenhuma fazenda encerrada registrada."], [780]);
    return;
  }

  rows.forEach(({ farm, orders, metrics }, index) => {
    const fields = metrics.fields.length > 0 ? metrics.fields : [emptyFieldMetric("-")];

    fields.forEach((field, fieldIndex) => {
      const rowValues = [
        fieldIndex === 0 ? formatFarmLabel(farm) : "",
        field.fieldCode,
        fieldIndex === 0 ? formatOrderList(orders) : "",
        fieldIndex === 0 ? formatClosedDateList(orders) : "",
        formatNumber(field.caneTons),
        formatNumber(field.areaHa),
        formatNumber(field.areaAlq),
        formatAverageMetrics(field)
      ];
      const pageBreakValues = [
        formatFarmLabel(farm),
        field.fieldCode,
        formatOrderList(orders),
        formatClosedDateList(orders),
        formatNumber(field.caneTons),
        formatNumber(field.areaHa),
        formatNumber(field.areaAlq),
        formatAverageMetrics(field)
      ];

      drawSimpleRow(
        doc,
        rowValues,
        widths,
        {
          repeatHeader,
          shaded: index % 2 === 1,
          pageBreakValues
        }
      );
    });
  });
}

function drawClosedTotalsCards(doc: PDFKit.PDFDocument, rows: ClosedFarmReportRow[]) {
  const totals = summarizeClosedFarmRows(rows);
  const cards = [
    ["Cana total", `${formatNumber(totals.caneTons)} t`],
    ["Hectares", formatNumber(totals.areaHa)],
    ["Alqueires", formatNumber(totals.areaAlq)],
    ["TCH medio", formatNumber(totals.tch)],
    ["TCA medio", formatNumber(totals.tca)]
  ] as const;
  const gap = 8;
  const width = (780 - gap * (cards.length - 1)) / cards.length;
  const y = doc.y + 6;

  ensureSpace(doc, 54);

  cards.forEach(([label, value], index) => {
    const x = 30 + index * (width + gap);
    doc.roundedRect(x, y, width, 38, 5).fillAndStroke("#f8fafb", reportColors.border);
    doc.font("Helvetica").fontSize(7.4).fillColor(reportColors.muted).text(label, x + 8, y + 8, { width: width - 16 });
    doc.font("Helvetica-Bold").fontSize(11).fillColor(reportColors.text).text(value, x + 8, y + 20, { width: width - 16 });
  });

  doc.y = y + 48;
}

function summarizeClosedFarmRows(rows: ClosedFarmReportRow[]) {
  const areaHa = rows.reduce((total, row) => total + row.metrics.areaHa, 0);
  const areaAlq = rows.reduce((total, row) => total + row.metrics.areaAlq, 0);
  const caneTons = rows.reduce((total, row) => total + row.metrics.caneTons, 0);

  return {
    areaHa,
    areaAlq,
    caneTons,
    tch: areaHa > 0 ? caneTons / areaHa : null,
    tca: areaAlq > 0 ? caneTons / areaAlq : null
  };
}

function emptyFieldMetric(fieldCode: string): ClosedFarmHarvestFieldMetric {
  return {
    fieldCode,
    areaHa: 0,
    areaAlq: 0,
    caneTons: 0,
    tch: null,
    tca: null
  };
}

function buildClosedFarmRows(closedOrders: HarvestOrder[], activeFarmIds: Set<string>): ClosedFarmReportRow[] {
  const rows: Array<{
    farm: HarvestOrder["farm"];
    orders: HarvestOrder[];
    fields: string[];
    fieldIds: string[];
  }> = [];

  for (const order of closedOrders) {
    for (const group of getOrderFarmFieldGroups(order)) {
      if (activeFarmIds.has(group.farm.id)) {
        continue;
      }

      rows.push({
        farm: group.farm,
        orders: [order],
        fields: [...group.fields],
        fieldIds: [...group.fieldIds]
      });
    }
  }

  return rows
    .map((row) => ({
      ...row,
      orders: row.orders.sort(compareOrdersByClosedDate),
      metrics: getClosedFarmHarvestMetrics(row)
    }))
    .sort(compareClosedFarmRowsByClosedDate);
}

function getClosedFarmHarvestMetrics(group: Pick<ClosedFarmReportRow, "farm" | "fieldIds" | "orders">): ClosedFarmHarvestMetrics {
  if (group.fieldIds.length === 0 || group.orders.length === 0) {
    return {
      fields: [],
      areaHa: 0,
      areaAlq: 0,
      caneTons: 0,
      tch: null,
      tca: null
    };
  }

  const placeholders = group.fieldIds.map(() => "?").join(", ");
  const orderIds = group.orders.map((order) => order.id);
  const orderIdPlaceholders = orderIds.map(() => "?").join(", ");
  const orderNumbers = Array.from(new Set(group.orders.map((order) => normalizeOrderNumber(order.number))));
  const orderNumberPlaceholders = orderNumbers.map(() => "?").join(", ");
  const harvestParams: unknown[] = [group.farm.id, ...group.fieldIds, ...orderIds, ...orderNumbers];

  const fieldRows = db
    .prepare(
      `
        SELECT
          f.id,
          f.code,
          COALESCE(f.area_ha, 0) AS area_ha,
          COALESCE(f.area_alq, 0) AS area_alq,
          COALESCE(harvest.cane_tons, 0) AS cane_tons
        FROM fields f
        LEFT JOIN (
          SELECT
            ce.field_id,
            COALESCE(SUM(ce.net_weight), 0) AS cane_tons
          FROM cane_entries ce
          JOIN import_batches b ON b.id = ce.batch_id
          WHERE ce.farm_id = ?
            AND ce.field_id IN (${placeholders})
            AND (b.source_type = 'SCS0110P_PDF' OR lower(b.file_name) LIKE '%.pdf')
            AND ce.field_id IS NOT NULL
            AND (
              ce.order_id IN (${orderIdPlaceholders})
              OR (
                ce.order_id IS NULL
                AND UPPER(TRIM(COALESCE(ce.order_number_raw, ''))) IN (${orderNumberPlaceholders})
              )
            )
          GROUP BY ce.field_id
        ) harvest ON harvest.field_id = f.id
        WHERE f.id IN (${placeholders})
        ORDER BY CAST(f.code AS INTEGER), f.code
      `
    )
    .all(...harvestParams, ...group.fieldIds) as Array<{
    id: string;
    code: string;
    area_ha: number;
    area_alq: number;
    cane_tons: number;
  }>;
  const fields = fieldRows.map((row) => {
    const areaHa = Number(row.area_ha ?? 0);
    const areaAlq = Number(row.area_alq ?? 0);
    const caneTons = Number(row.cane_tons ?? 0);

    return {
      fieldCode: row.code,
      areaHa,
      areaAlq,
      caneTons,
      tch: areaHa > 0 && caneTons > 0 ? caneTons / areaHa : null,
      tca: areaAlq > 0 && caneTons > 0 ? caneTons / areaAlq : null
    };
  });
  const areaHa = fieldRows.reduce((total, row) => total + Number(row.area_ha ?? 0), 0);
  const areaAlq = fieldRows.reduce((total, row) => total + Number(row.area_alq ?? 0), 0);
  const caneTons = fieldRows.reduce((total, row) => total + Number(row.cane_tons ?? 0), 0);

  return {
    fields,
    areaHa,
    areaAlq,
    caneTons,
    tch: areaHa > 0 ? caneTons / areaHa : null,
    tca: areaAlq > 0 ? caneTons / areaAlq : null
  };
}

function drawSectionTitle(doc: PDFKit.PDFDocument, title: string, note?: string) {
  doc.font("Helvetica-Bold").fontSize(11).fillColor(reportColors.text).text(title, 30, doc.y);

  if (note) {
    doc.font("Helvetica").fontSize(7.5).fillColor(reportColors.muted).text(note, 30, doc.y + 2);
  }

  doc.y += 8;
}

function drawTableHeader(doc: PDFKit.PDFDocument, labels: string[], widths: number[]) {
  ensureSpace(doc, 24);
  const x = 30;
  const y = doc.y;
  const height = 24;
  let cursor = x;

  doc.rect(x, y, widths.reduce((total, width) => total + width, 0), height).fillAndStroke(reportColors.header, reportColors.border);
  doc.font("Helvetica-Bold").fontSize(7.5).fillColor(reportColors.text);

  labels.forEach((label, index) => {
    doc.text(label, cursor + 4, y + 5, { width: widths[index] - 8, height: height - 6 });
    cursor += widths[index];
  });

  doc.y = y + height;
}

function drawSimpleRow(doc: PDFKit.PDFDocument, values: string[], widths: number[], options: RowOptions = {}) {
  doc.font("Helvetica").fontSize(7.2);
  const heightValues = options.pageBreakValues ? [...values, ...options.pageBreakValues] : values;
  const rowHeight = Math.max(
    18,
    ...heightValues.map((value, index) => {
      const width = widths[index % widths.length];

      return doc.heightOfString(value, { width: width - 8 }) + 8;
    })
  );

  const addedPage = ensureSpace(doc, rowHeight + 4);

  if (addedPage && options.repeatHeader) {
    options.repeatHeader();
  }

  const finalValues = addedPage && options.pageBreakValues ? options.pageBreakValues : values;
  const cells = finalValues.map((value, index) => ({ value, width: widths[index] }));
  const x = 30;
  const y = doc.y;
  let cursor = x;

  if (options.shaded) {
    doc.rect(x, y, widths.reduce((total, width) => total + width, 0), rowHeight).fill("#fbfcfd");
  }

  doc.rect(x, y, widths.reduce((total, width) => total + width, 0), rowHeight).stroke(reportColors.border);
  doc.font("Helvetica").fontSize(7.2).fillColor(reportColors.text);

  for (const cell of cells) {
    doc.text(cell.value, cursor + 4, y + 5, { width: cell.width - 8, height: rowHeight - 6, ellipsis: true });
    cursor += cell.width;
  }

  doc.y = y + rowHeight;
}

function ensureSpace(doc: PDFKit.PDFDocument, height: number) {
  if (doc.y + height <= doc.page.height - 56) {
    return false;
  }

  startNewReportPage(doc);
  return true;
}

function startNewReportPage(doc: PDFKit.PDFDocument) {
  doc.addPage();
  doc.y = 30;
}

function addPageFooters(doc: PDFKit.PDFDocument, _generatedAt: string) {
  const range = doc.bufferedPageRange();

  for (let index = range.start; index < range.start + range.count; index += 1) {
    const pageNumber = index - range.start + 1;
    doc.switchToPage(index);
    doc.font("Helvetica").fontSize(7).fillColor(reportColors.muted);
    doc.text(`Página ${pageNumber} de ${range.count}`, 30, doc.page.height - 42, { width: doc.page.width - 60, align: "right" });
  }
}

function buildCurrentFarmRows(orders: HarvestOrder[]): CurrentFarmReportRow[] {
  return orders
    .flatMap((order) => {
      const fronts = getOrderFrontNumbers(order);

      return getOrderFarmFieldGroups(order).map((group) => ({ order, fronts, group }));
    })
    .sort((left, right) => {
      const frontDiff = (left.fronts[0] ?? Number.MAX_SAFE_INTEGER) - (right.fronts[0] ?? Number.MAX_SAFE_INTEGER);

      if (frontDiff !== 0) {
        return frontDiff;
      }

      return formatFarmLabel(left.group.farm).localeCompare(formatFarmLabel(right.group.farm), "pt-BR");
    });
}

function buildCurrentFarmSummaryRows(orders: HarvestOrder[]): CurrentFarmSummaryReportRow[] {
  const grouped = new Map<string, { farm: HarvestOrder["farm"]; fronts: Set<number> }>();

  for (const order of orders) {
    const fronts = getOrderFrontNumbers(order);

    for (const group of getOrderFarmFieldGroups(order)) {
      const current = grouped.get(group.farm.id) ?? {
        farm: group.farm,
        fronts: new Set<number>()
      };

      fronts.forEach((front) => current.fronts.add(front));
      grouped.set(group.farm.id, current);
    }
  }

  return [...grouped.values()]
    .map((row) => ({
      farm: row.farm,
      fronts: [...row.fronts].sort((left, right) => left - right)
    }))
    .sort((left, right) => {
      const frontDiff = (left.fronts[0] ?? Number.MAX_SAFE_INTEGER) - (right.fronts[0] ?? Number.MAX_SAFE_INTEGER);

      if (frontDiff !== 0) {
        return frontDiff;
      }

      return formatFarmLabel(left.farm).localeCompare(formatFarmLabel(right.farm), "pt-BR");
    });
}

function getOrderFarmFieldGroups(order: HarvestOrder): FarmFieldGroup[] {
  return getOrderFarms(order).map((farm) => {
    const fields = order.fields.filter((item) => item.field.farmId === farm.id);

    return {
      farm,
      fields: fields.map((item) => item.field.code),
      fieldIds: fields.map((item) => item.fieldId)
    };
  });
}

function getOrderFarms(order: HarvestOrder) {
  return order.farms?.length ? order.farms : [order.farm].filter(Boolean);
}

function getOrderFrontNumbers(order: HarvestOrder) {
  return order.frontNumbers?.length ? order.frontNumbers : order.frontNumber ? [order.frontNumber] : [];
}

function getHarvestFrontNumbers(order: HarvestOrder) {
  return getOrderFrontNumbers(order).filter((frontNumber) => harvestFronts.has(frontNumber));
}

function formatFrontNumbers(frontNumbers: number[]) {
  if (frontNumbers.length === 0) {
    return "Sem frente";
  }

  if (frontNumbers.length === 1) {
    return `Frente ${frontNumbers[0]}`;
  }

  return `Frentes ${frontNumbers.join(", ")}`;
}

function formatFrontNumberValues(frontNumbers: number[]) {
  return frontNumbers.length > 0 ? frontNumbers.join(", ") : "-";
}

function formatFarmCode(farm: HarvestOrder["farm"]) {
  return farm.code?.trim() || "-";
}

function formatFarmLocation(farm: HarvestOrder["farm"]) {
  return (farm.municipality?.trim() || farm.city?.trim() || "").toLocaleUpperCase("pt-BR");
}

function formatFarmLabel(farm: HarvestOrder["farm"]) {
  const label = farm.code ? `${farm.code} - ${farm.name}` : farm.name;

  return label.toLocaleUpperCase("pt-BR");
}

function formatFieldList(fields: string[]) {
  return fields.length > 0 ? fields.join(", ") : "-";
}

function formatOrderList(orders: HarvestOrder[]) {
  const numbers = Array.from(new Set(orders.map((order) => order.number)));

  return numbers.length > 0 ? numbers.join(", ") : "-";
}

function formatClosedDateList(orders: HarvestOrder[]) {
  const dates = Array.from(new Set(orders.map((order) => formatDateOnly(order.endDate))));

  return dates.length > 0 ? dates.join(", ") : "-";
}

function compareOrdersByFront(left: HarvestOrder, right: HarvestOrder) {
  return (getOrderFrontNumbers(left)[0] ?? Number.MAX_SAFE_INTEGER) - (getOrderFrontNumbers(right)[0] ?? Number.MAX_SAFE_INTEGER);
}

function compareOrdersByClosedDate(left: HarvestOrder, right: HarvestOrder) {
  return parseDateTime(left.endDate) - parseDateTime(right.endDate) || left.number.localeCompare(right.number, "pt-BR", { numeric: true });
}

function compareClosedFarmRowsByClosedDate(left: ClosedFarmReportRow, right: ClosedFarmReportRow) {
  const leftDate = parseDateTime(left.orders[0]?.endDate);
  const rightDate = parseDateTime(right.orders[0]?.endDate);

  return leftDate - rightDate || formatFarmLabel(left.farm).localeCompare(formatFarmLabel(right.farm), "pt-BR");
}

function parseDateTime(value: string | null | undefined) {
  const timestamp = value ? new Date(value).getTime() : Number.MAX_SAFE_INTEGER;
  return Number.isNaN(timestamp) ? Number.MAX_SAFE_INTEGER : timestamp;
}

function formatDateTime(value: string) {
  const date = new Date(value);

  if (Number.isNaN(date.getTime())) {
    return value || "-";
  }

  return new Intl.DateTimeFormat("pt-BR", {
    dateStyle: "short",
    timeStyle: "short"
  }).format(date);
}

function formatDateOnly(value: string | null | undefined) {
  if (!value) {
    return "-";
  }

  const date = new Date(value);

  if (Number.isNaN(date.getTime())) {
    return value;
  }

  return new Intl.DateTimeFormat("pt-BR", {
    dateStyle: "short"
  }).format(date);
}

function formatAverageMetrics(metrics: { tch: number | null; tca: number | null }) {
  if (metrics.tch === null && metrics.tca === null) {
    return "-";
  }

  return `TCH ${formatNumber(metrics.tch)}\nTCA ${formatNumber(metrics.tca)}`;
}

function formatNumber(value: number | null | undefined) {
  if (value === null || value === undefined || !Number.isFinite(value)) {
    return "-";
  }

  return new Intl.NumberFormat("pt-BR", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2
  }).format(value);
}

function compareFieldCodes(left: string, right: string) {
  return left.localeCompare(right, "pt-BR", { numeric: true });
}
