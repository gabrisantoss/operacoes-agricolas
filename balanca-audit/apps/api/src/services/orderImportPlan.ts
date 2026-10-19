import { createOrderSchema, updateOrderSchema, type CreateOrderInput, type UpdateOrderInput } from "@balanca/shared";
import type { FarmRecord, HarvestOrderRecord } from "../db.js";
import type { OrderImportAction } from "../repositories/ordersRepository.js";

export type OrderImportSourceRow = {
  rowNumber: number;
  orderNumber: string;
  farmReference: string;
  fieldReference: string;
  error?: string;
};

export type OrderImportPreviewItem = OrderImportSourceRow & {
  status: "CREATE" | "UPDATE" | "SKIP" | "DIVERGENCE" | "ERROR";
  message: string;
};

// Differences between the exported spreadsheet (official system) and the management view. They are reported,
// never applied automatically, and do not block the rest of the import.
export type OrderImportDivergenceKind =
  | "CLOSED_ORDER_NEW_FIELD"
  | "FIELD_IN_OTHER_ACTIVE_ORDER"
  | "FIELD_IN_TWO_SHEET_ORDERS"
  | "FIELD_MISSING_FROM_SHEET";

export type OrderImportDivergence = {
  kind: OrderImportDivergenceKind;
  rowNumber: number | null;
  orderNumber: string;
  farmName: string;
  fieldCode: string;
  message: string;
};

export type OrderImportSummary = {
  rowCount: number;
  successCount: number;
  createCount: number;
  updateCount: number;
  skippedCount: number;
  divergenceCount: number;
  errorsCount: number;
};

export type OrderImportPreview = {
  fileName: string;
  fileHash: string;
  summary: OrderImportSummary;
  items: OrderImportPreviewItem[];
  divergences: OrderImportDivergence[];
  errors: string[];
  // Set when this exact file (same SHA-256) was already imported.
  previousImport: { fileName: string; importedAt: string } | null;
};

export type OrderImportPlan = OrderImportPreview & {
  actions: OrderImportAction[];
};

type ValidatedRow = OrderImportSourceRow & {
  farm: FarmRecord;
  field: FarmRecord["fields"][number];
};

export function buildOrderImportPlan(
  rows: OrderImportSourceRow[],
  state: { farms: FarmRecord[]; orders: HarvestOrderRecord[]; previousImport?: OrderImportPreview["previousImport"] },
  fileName = "orders.xlsx",
  fileHash = ""
): OrderImportPlan {
  const items: OrderImportPreviewItem[] = [];
  const errors: string[] = [];
  const actions: OrderImportAction[] = [];
  const divergences: OrderImportDivergence[] = [];

  const addDivergence = (row: ValidatedRow | null, divergence: Omit<OrderImportDivergence, "rowNumber">) => {
    divergences.push({ ...divergence, rowNumber: row?.rowNumber ?? null });
    if (row) items.push({ ...row, status: "DIVERGENCE", message: divergence.message });
  };
  const groups = new Map<string, { number: string; rows: ValidatedRow[]; fieldIds: Set<string> }>();

  const addError = (row: OrderImportSourceRow, message: string) => {
    const fullMessage = `Linha ${row.rowNumber}: ${message}`;
    errors.push(fullMessage);
    items.push({ ...row, status: "ERROR", message: fullMessage });
  };

  for (const row of rows) {
    if (row.error) {
      addError(row, row.error);
      continue;
    }
    if (!row.orderNumber || !row.farmReference || !row.fieldReference) {
      const missing = [
        !row.orderNumber ? "Codigo da OS" : null,
        !row.farmReference ? "Propriedade" : null,
        !row.fieldReference ? "Setor" : null
      ].filter(Boolean);
      addError(row, `campos obrigatorios ausentes: ${missing.join(", ")}.`);
      continue;
    }

    const matchingFarms = resolveFarms(row.farmReference, state.farms);
    if (matchingFarms.length === 0) {
      addError(row, `propriedade '${row.farmReference}' nao encontrada; nenhuma fazenda foi criada automaticamente.`);
      continue;
    }
    if (matchingFarms.length > 1) {
      addError(row, `propriedade '${row.farmReference}' corresponde a mais de uma fazenda.`);
      continue;
    }

    const farm = matchingFarms[0]!;
    const matchingFields = farm.fields.filter((field) => sameReference(field.code, row.fieldReference));
    const activeFields = matchingFields.filter((field) => field.active !== false);
    if (activeFields.length === 0) {
      addError(
        row,
        matchingFields.length > 0
          ? `setor '${row.fieldReference}' esta inativo na fazenda '${farm.name}'.`
          : `setor '${row.fieldReference}' nao encontrado na fazenda '${farm.name}'.`
      );
      continue;
    }
    if (activeFields.length > 1) {
      addError(row, `setor '${row.fieldReference}' e ambiguo na fazenda '${farm.name}'.`);
      continue;
    }

    const normalizedOrderNumber = normalizeText(row.orderNumber);
    let group = groups.get(normalizedOrderNumber);
    if (!group) {
      group = { number: row.orderNumber, rows: [], fieldIds: new Set<string>() };
      groups.set(normalizedOrderNumber, group);
    }

    const field = activeFields[0]!;
    if (group.fieldIds.has(field.id)) {
      items.push({ ...row, status: "SKIP", message: "Linha duplicada na propria planilha." });
      continue;
    }

    group.fieldIds.add(field.id);
    group.rows.push({ ...row, farm, field });
  }

  const sheetFieldsByOrder = new Map([...groups].map(([key, group]) => [key, [...group.fieldIds]]));
  // Orders already closed here are history (a new harvest cycle may reuse their sectors); only the others can conflict.
  const isClosedHere = (normalizedOrderNumber: string) => {
    const matching = state.orders.filter((order) => normalizeText(order.number) === normalizedOrderNumber);
    return matching.length > 0 && matching.every((order) => order.status === "CLOSED");
  };
  const sheetOrdersByField = new Map<string, Set<string>>();
  for (const [normalizedOrderNumber, group] of groups) {
    if (isClosedHere(normalizedOrderNumber)) continue;
    for (const fieldId of group.fieldIds) {
      const orders = sheetOrdersByField.get(fieldId) ?? new Set<string>();
      orders.add(normalizedOrderNumber);
      sheetOrdersByField.set(fieldId, orders);
    }
  }

  for (const [normalizedOrderNumber, group] of groups) {
    const conflictingRows = group.rows.filter((row) => (sheetOrdersByField.get(row.field.id)?.size ?? 0) > 1);
    for (const row of conflictingRows) {
      addDivergence(row, {
        kind: "FIELD_IN_TWO_SHEET_ORDERS",
        orderNumber: group.number,
        farmName: row.farm.name,
        fieldCode: row.field.code,
        message: `Linha ${row.rowNumber}: o setor ${row.field.code} aparece em mais de uma OS na planilha; nao aplicado.`
      });
    }
    group.rows = group.rows.filter((row) => !conflictingRows.includes(row));

    const matchingOrders = state.orders.filter((order) => normalizeText(order.number) === normalizedOrderNumber);
    const activeOrders = matchingOrders.filter((order) => order.status === "ACTIVE");

    if (activeOrders.length > 1) {
      for (const row of group.rows) {
        addError(row, `a OS '${group.number}' possui mais de um registro ativo e precisa ser corrigida manualmente.`);
      }
      continue;
    }

    if (activeOrders.length === 0 && matchingOrders.length > 0) {
      // Exports of the official system keep listing closed orders; the closed record here is preserved.
      const linkedFieldIds = new Set(matchingOrders.flatMap((order) => order.fields.map((field) => field.fieldId)));
      for (const row of group.rows) {
        if (linkedFieldIds.has(row.field.id)) {
          items.push({ ...row, status: "SKIP", message: `OS ${group.number} encerrada no Balanca; sem alteracao.` });
        } else {
          addDivergence(row, {
            kind: "CLOSED_ORDER_NEW_FIELD",
            orderNumber: group.number,
            farmName: row.farm.name,
            fieldCode: row.field.code,
            message: `Linha ${row.rowNumber}: a OS ${group.number} esta encerrada no Balanca e a planilha traz o setor ${row.field.code}, que nao esta vinculado; nao aplicado.`
          });
        }
      }
      continue;
    }

    const activeOrderId = activeOrders[0]?.id;
    const otherActiveOrder = (row: ValidatedRow) =>
      state.orders.find(
        (order) =>
          order.status === "ACTIVE" && order.id !== activeOrderId && order.fields.some((field) => field.fieldId === row.field.id)
      );
    const rowsInOtherOrders = group.rows.filter((row) => otherActiveOrder(row));
    for (const row of rowsInOtherOrders) {
      addDivergence(row, {
        kind: "FIELD_IN_OTHER_ACTIVE_ORDER",
        orderNumber: group.number,
        farmName: row.farm.name,
        fieldCode: row.field.code,
        message: `Linha ${row.rowNumber}: o setor ${row.field.code} ja esta na OS ativa ${otherActiveOrder(row)!.number} no Balanca; nao aplicado para evitar setor em duas OS ativas.`
      });
    }
    group.rows = group.rows.filter((row) => !rowsInOtherOrders.includes(row));
    if (group.rows.length === 0) {
      continue;
    }

    if (activeOrders.length === 0) {
      const firstRow = group.rows[0]!;
      const input: CreateOrderInput = {
        number: group.number.replace(/\s+/g, " ").trim(),
        farmId: firstRow.farm.id,
        fieldIds: group.rows.map((row) => row.field.id),
        frontNumbers: [],
        origin: "EXCEL"
      };
      const validation = createOrderSchema.safeParse(input);
      if (!validation.success) {
        for (const row of group.rows) {
          addError(row, `dados invalidos para criar a OS '${group.number}'.`);
        }
        continue;
      }

      actions.push({ type: "CREATE", input: validation.data });
      for (const row of group.rows) {
        items.push({ ...row, status: "CREATE", message: `Criar OS ${group.number}.` });
      }
      continue;
    }

    const existingOrder = activeOrders[0]!;
    const existingFieldIds = existingOrder.fields.map((field) => field.fieldId);
    const existingFieldIdSet = new Set(existingFieldIds);
    const rowsToAdd = group.rows.filter((row) => !existingFieldIdSet.has(row.field.id));
    const rowsAlreadyPresent = group.rows.filter((row) => existingFieldIdSet.has(row.field.id));

    for (const row of rowsAlreadyPresent) {
      items.push({ ...row, status: "SKIP", message: `Setor ja vinculado a OS ${group.number}.` });
    }
    const sheetFieldIds = new Set(sheetFieldsByOrder.get(normalizedOrderNumber) ?? []);
    for (const link of existingOrder.fields.filter((field) => !sheetFieldIds.has(field.fieldId))) {
      addDivergence(null, {
        kind: "FIELD_MISSING_FROM_SHEET",
        orderNumber: existingOrder.number,
        farmName: farmNameFor(link.field.farmId, existingOrder),
        fieldCode: link.field.code,
        message: `OS ${existingOrder.number}: o setor ${link.field.code} esta vinculado no Balanca e nao aparece na planilha; mantido, sem remocao automatica.`
      });
    }
    if (rowsToAdd.length === 0) {
      continue;
    }

    const input: UpdateOrderInput = {
      number: existingOrder.number,
      farmId: existingOrder.farmId,
      fieldIds: Array.from(new Set([...existingFieldIds, ...rowsToAdd.map((row) => row.field.id)])),
      frontNumbers: existingOrder.frontNumbers,
      startDate: existingOrder.startDate ?? undefined,
      endDate: existingOrder.endDate ?? undefined,
      origin: "EXCEL"
    };
    const validation = updateOrderSchema.safeParse(input);
    if (!validation.success) {
      for (const row of rowsToAdd) {
        addError(row, `dados invalidos para atualizar a OS '${group.number}'.`);
      }
      continue;
    }

    actions.push({
      type: "UPDATE",
      orderId: existingOrder.id,
      input: validation.data,
      expectedFieldIds: existingFieldIds
    });
    for (const row of rowsToAdd) {
      items.push({ ...row, status: "UPDATE", message: `Adicionar setor a OS ${group.number}.` });
    }
  }

  items.sort((left, right) => left.rowNumber - right.rowNumber);
  const createCount = actions.filter((action) => action.type === "CREATE").length;
  const updateCount = actions.filter((action) => action.type === "UPDATE").length;

  return {
    fileName,
    fileHash,
    summary: {
      rowCount: rows.length,
      successCount: createCount + updateCount,
      createCount,
      updateCount,
      skippedCount: items.filter((item) => item.status === "SKIP").length,
      divergenceCount: divergences.length,
      errorsCount: errors.length
    },
    items,
    divergences,
    errors,
    previousImport: state.previousImport ?? null,
    actions
  };
}

function farmNameFor(farmId: string, order: HarvestOrderRecord) {
  return (order.farms ?? [order.farm]).find((farm) => farm?.id === farmId)?.name ?? order.farm?.name ?? "";
}

function resolveFarms(reference: string, farms: FarmRecord[]) {
  return farms.filter(
    (farm) => sameReference(farm.propertyNumber, reference) || sameReference(farm.code, reference)
  );
}

function sameReference(left: string | null | undefined, right: string | null | undefined) {
  const leftKey = referenceKey(left);
  const rightKey = referenceKey(right);
  return Boolean(leftKey && rightKey && leftKey === rightKey);
}

function referenceKey(value: string | null | undefined) {
  const normalized = normalizeText(value);
  if (!normalized) return "";
  if (/^[\d\s./-]+$/.test(normalized)) {
    const digits = normalized.replace(/\D/g, "").replace(/^0+(?=\d)/, "");
    return `n:${digits}`;
  }
  return `t:${normalized}`;
}

function normalizeText(value: string | null | undefined) {
  return String(value ?? "")
    .normalize("NFD")
    .replace(/\p{Diacritic}/gu, "")
    .replace(/\s+/g, " ")
    .trim()
    .toLocaleLowerCase("pt-BR");
}
