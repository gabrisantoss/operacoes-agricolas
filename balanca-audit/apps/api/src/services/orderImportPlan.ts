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
  status: "CREATE" | "UPDATE" | "SKIP" | "ERROR";
  message: string;
};

export type OrderImportSummary = {
  rowCount: number;
  successCount: number;
  createCount: number;
  updateCount: number;
  skippedCount: number;
  errorsCount: number;
};

export type OrderImportPreview = {
  fileName: string;
  fileHash: string;
  summary: OrderImportSummary;
  items: OrderImportPreviewItem[];
  errors: string[];
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
  state: { farms: FarmRecord[]; orders: HarvestOrderRecord[] },
  fileName = "orders.xlsx",
  fileHash = ""
): OrderImportPlan {
  const items: OrderImportPreviewItem[] = [];
  const errors: string[] = [];
  const actions: OrderImportAction[] = [];
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

  for (const [normalizedOrderNumber, group] of groups) {
    const matchingOrders = state.orders.filter((order) => normalizeText(order.number) === normalizedOrderNumber);
    const activeOrders = matchingOrders.filter((order) => order.status === "ACTIVE");

    if (activeOrders.length > 1) {
      for (const row of group.rows) {
        addError(row, `a OS '${group.number}' possui mais de um registro ativo e precisa ser corrigida manualmente.`);
      }
      continue;
    }

    if (activeOrders.length === 0 && matchingOrders.length > 0) {
      for (const row of group.rows) {
        addError(row, `a OS '${group.number}' ja existe, mas esta fechada.`);
      }
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
      errorsCount: errors.length
    },
    items,
    errors,
    actions
  };
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
