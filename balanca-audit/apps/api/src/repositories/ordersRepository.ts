import { randomUUID } from "node:crypto";
import type { CreateOrderInput, UpdateOrderInput } from "@balanca/shared";
import type { FarmRecord, FieldRecord, HarvestOrderRecord } from "../db.js";
import type { HarvestOrderHistoryEventType } from "../db.js";

type Statement = {
  all(...params: unknown[]): unknown[];
  get(...params: unknown[]): unknown;
  run(...params: unknown[]): RunResult;
  runMany(paramsList: any[]): RunResult;
};

type DatabaseAdapter = {
  prepare(sql: string): Statement;
  transaction<T>(fn: () => T): () => T;
};

type RunResult = {
  changes: number;
};

export type OrderImportAction =
  | { type: "CREATE"; input: CreateOrderInput }
  | { type: "UPDATE"; orderId: string; input: UpdateOrderInput; expectedFieldIds: string[] };

export class OrderImportConflictError extends Error {
  constructor() {
    super("Os dados das OS mudaram depois da previa.");
  }
}

type OrderRow = {
  id: string;
  number: string;
  front_number: number | null;
  farm_id: string;
  status: "ACTIVE" | "CLOSED";
  start_date: string | null;
  end_date: string | null;
};

type OrderFieldRow = {
  id: string;
  order_id: string;
  field_id: string;
  code: string;
  name: string | null;
  area_ha: number | null;
  area_alq: number | null;
  planted_area_ha: number | null;
  crop_year: string | null;
  area_type: string | null;
  active: number;
  farm_id: string;
};

type MappedOrderField = HarvestOrderRecord["fields"][number];
type RemovedOrderFarmResult = {
  order: HarvestOrderRecord;
  removedFieldCount: number;
  unlinkedDocumentCount: number;
  reclassifiedEntryCount: number;
};

export class OrdersRepository {
  constructor(
    private readonly db: DatabaseAdapter
  ) {}

  listOrders(): HarvestOrderRecord[] {
    const orders = this.db
      .prepare(
        `
        SELECT ho.id, ho.number, ho.front_number, ho.farm_id, ho.status, ho.start_date, ho.end_date
        FROM harvest_orders ho
        ORDER BY COALESCE(ho.end_date, ho.created_at) DESC
        `
      )
      .all() as OrderRow[];

    return this.mapHarvestOrderRows(orders);
  }

  listOrdersByYear(year: number): HarvestOrderRecord[] {
    const orders = this.db
      .prepare(
        `
        SELECT ho.id, ho.number, ho.front_number, ho.farm_id, ho.status, ho.start_date, ho.end_date
        FROM harvest_orders ho
        WHERE EXTRACT(YEAR FROM COALESCE(ho.start_date, ho.created_at)) = ?
        ORDER BY COALESCE(ho.end_date, ho.created_at) DESC
        `
      )
      .all(year) as OrderRow[];

    return this.mapHarvestOrderRows(orders);
  }

  listAvailableYears(): number[] {
    const rows = this.db
      .prepare(
        `
        SELECT DISTINCT EXTRACT(YEAR FROM COALESCE(ho.start_date, ho.created_at))::int AS year
        FROM harvest_orders ho
        ORDER BY year DESC
        `
      )
      .all() as { year: number }[];

    return rows.map((row) => row.year);
  }

  listOrdersWithNumber(number: string): HarvestOrderRecord[] {
    const normalizedNumber = normalize(number);
    const rows = this.db
      .prepare(
        `
        SELECT ho.id, ho.number, ho.front_number, ho.farm_id, ho.status, ho.start_date, ho.end_date
        FROM harvest_orders ho
        WHERE lower(trim(ho.number)) = ?
        ORDER BY COALESCE(ho.end_date, ho.created_at) DESC
        `
      )
      .all(normalizedNumber) as OrderRow[];

    return this.mapHarvestOrderRows(rows);
  }

  findOrderById(id: string) {
    const rows = this.db
      .prepare(
        `
        SELECT ho.id, ho.number, ho.front_number, ho.farm_id, ho.status, ho.start_date, ho.end_date
        FROM harvest_orders ho
        WHERE ho.id = ?
        LIMIT 1
        `
      )
      .all(id) as OrderRow[];

    return this.mapHarvestOrderRows(rows)[0] ?? null;
  }

  createOrder(input: CreateOrderInput) {
    const create = this.db.transaction(() => this.insertOrder(input));

    const orderId = create();
    return this.findOrderById(orderId);
  }

  updateOrder(orderId: string, input: UpdateOrderInput) {
    const update = this.db.transaction(() => this.updateOrderWithinTransaction(orderId, input));

    const updatedOrderId = update();
    return updatedOrderId ? this.findOrderById(updatedOrderId) : null;
  }

  updateOrderWithinExistingTransaction(orderId: string, input: UpdateOrderInput) {
    const updatedOrderId = this.updateOrderWithinTransaction(orderId, input);
    return updatedOrderId ? this.findOrderById(updatedOrderId) : null;
  }

  /** Applies a fully validated import plan in one database transaction. */
  applyImportActions(actions: OrderImportAction[]) {
    const apply = this.db.transaction(() => {
      this.assertImportPreconditions(actions);
      return actions.map((action) =>
        action.type === "CREATE"
          ? this.insertOrder(action.input)
          : this.updateOrderWithinTransaction(action.orderId, action.input)
      );
    });

    const orderIds = apply();
    return orderIds
      .filter((orderId): orderId is string => Boolean(orderId))
      .map((orderId) => this.findOrderById(orderId))
      .filter((order): order is HarvestOrderRecord => Boolean(order));
  }

  closeOrder(orderId: string) {
    const close = this.db.transaction(() => this.closeOrderWithinExistingTransaction(orderId));

    return close() ? this.findOrderById(orderId) : null;
  }

  closeOrderWithinExistingTransaction(orderId: string) {
    const current = this.db.prepare("SELECT number FROM harvest_orders WHERE id = ? FOR UPDATE").get(orderId) as
      | { number: string }
      | undefined;

    if (!current) {
      return false;
    }

    const frontNumbers = this.getOrderFrontNumbersById(orderId);
    const result = this.db.prepare(`
      UPDATE harvest_orders
      SET status = 'CLOSED', end_date = COALESCE(end_date, CURRENT_TIMESTAMP), updated_at = CURRENT_TIMESTAMP
      WHERE id = ? AND status <> 'CLOSED'
    `).run(orderId);

    if (result.changes > 0) {
      this.insertOrderHistoryEvent({
        orderId,
        orderNumber: current.number,
        eventType: "CLOSED",
        frontNumbersBefore: frontNumbers,
        frontNumbersAfter: frontNumbers
      });
    }

    return result.changes > 0;
  }

  reopenOrder(orderId: string) {
    const reopen = this.db.transaction(() => {
      const current = this.db.prepare("SELECT number FROM harvest_orders WHERE id = ?").get(orderId) as
        | { number: string }
        | undefined;

      if (!current) {
        return false;
      }

      const frontNumbers = this.getOrderFrontNumbersById(orderId);
      const result = this.db
        .prepare(`
          UPDATE harvest_orders
          SET status = 'ACTIVE', end_date = NULL, updated_at = CURRENT_TIMESTAMP
          WHERE id = ?
        `)
        .run(orderId);

      if (result.changes > 0) {
        this.insertOrderHistoryEvent({
          orderId,
          orderNumber: current.number,
          eventType: "REOPENED",
          frontNumbersBefore: frontNumbers,
          frontNumbersAfter: frontNumbers
        });
      }

      return result.changes > 0;
    });

    return reopen() ? this.findOrderById(orderId) : null;
  }

  deleteOrder(orderId: string) {
    const remove = this.db.transaction(() => {
      const order = this.db.prepare("SELECT status FROM harvest_orders WHERE id = ?").get(orderId) as { status: string } | undefined;

      if (order?.status === "ACTIVE") {
        throw new Error("Não é possível excluir uma OS Ativa.");
      }

      this.db.prepare("UPDATE cane_entries SET order_id = NULL WHERE order_id = ?").run(orderId);
      return this.db.prepare("DELETE FROM harvest_orders WHERE id = ?").run(orderId);
    });

    const result = remove();
    return result.changes > 0;
  }

  removeOrderFarm(orderId: string, farmId: string): RemovedOrderFarmResult | null {
    const remove = this.db.transaction(() => {
      const current = this.db.prepare("SELECT id, number, farm_id FROM harvest_orders WHERE id = ?").get(orderId) as
        | { id: string; number: string; farm_id: string }
        | undefined;

      if (!current) {
        return null;
      }

      const deleteResult = this.db.prepare(`
        DELETE FROM harvest_order_fields
        WHERE order_id = ?
          AND field_id IN (
            SELECT id
            FROM fields
            WHERE farm_id = ?
          )
      `).run(orderId, farmId);

      if (deleteResult.changes === 0) {
        return {
          removedFieldCount: 0,
          unlinkedDocumentCount: 0,
          reclassifiedEntryCount: 0
        };
      }

      const remainingFarm = this.db.prepare(`
        SELECT f.farm_id
        FROM harvest_order_fields hof
        JOIN fields f ON f.id = hof.field_id
        WHERE hof.order_id = ?
        ORDER BY f.code ASC
        LIMIT 1
      `).get(orderId) as { farm_id: string } | undefined;

      if (!remainingFarm) {
        throw new Error("A OS precisa manter pelo menos uma fazenda.");
      }

      const cleanup = this.cleanupRemovedOrderFarmLinks(orderId, farmId, current.number);

      const nextPrimaryFarmId = current.farm_id === farmId ? remainingFarm.farm_id : current.farm_id;
      this.db.prepare(`
        UPDATE harvest_orders
        SET farm_id = ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
      `).run(nextPrimaryFarmId, orderId);

      return {
        removedFieldCount: deleteResult.changes,
        unlinkedDocumentCount: cleanup.unlinkedDocumentCount,
        reclassifiedEntryCount: cleanup.reclassifiedEntryCount
      };
    });

    const result = remove();

    if (!result) {
      return null;
    }

    const order = this.findOrderById(orderId);

    if (!order) {
      return null;
    }

    return { order, ...result };
  }

  findActiveOrderForFront(frontNumber: number, ignoredOrderId?: string) {
    let query = `
      SELECT ho.id
      FROM harvest_orders ho
      JOIN harvest_order_fronts hof ON hof.order_id = ho.id
      WHERE ho.status = 'ACTIVE' AND hof.front_number = ?
    `;
    const params: any[] = [frontNumber];

    if (ignoredOrderId) {
      query += ` AND ho.id != ?`;
      params.push(ignoredOrderId);
    }

    query += ` LIMIT 1`;

    const row = this.db.prepare(query).get(...params) as { id: string } | undefined;

    return row ? this.findOrderById(row.id) : null;
  }

  private insertOrder(input: CreateOrderInput) {
    const orderId = randomUUID();
    const frontNumbers = normalizeOrderFrontNumbers(input.frontNumbers, input.frontNumber);
    const primaryFarmId = this.resolveOrderPrimaryFarmId(input.farmId, input.fieldIds);

    this.db.prepare(`
      INSERT INTO harvest_orders (id, number, front_number, farm_id, start_date, end_date, origin)
      VALUES (?, ?, ?, ?, ?, ?, ?)
    `).run(
      orderId,
      input.number,
      frontNumbers[0] ?? null,
      primaryFarmId,
      input.startDate ?? null,
      input.endDate ?? null,
      input.origin ?? "MANUAL"
    );

    this.insertOrderFronts(orderId, frontNumbers);
    this.insertOrderHistoryEvent({
      orderId,
      orderNumber: input.number,
      eventType: resolveFrontHistoryEventType([], frontNumbers),
      frontNumbersAfter: frontNumbers
    });

    for (const fieldId of input.fieldIds) {
      this.db.prepare("INSERT INTO harvest_order_fields (id, order_id, field_id) VALUES (?, ?, ?)").run(
        randomUUID(),
        orderId,
        fieldId
      );
    }

    return orderId;
  }

  private updateOrderWithinTransaction(orderId: string, input: UpdateOrderInput) {
    const previousFrontNumbers = this.getOrderFrontNumbersById(orderId);
    const previousFarmIds = this.getOrderFieldFarmIds(orderId);
    const frontNumbers = normalizeOrderFrontNumbers(input.frontNumbers, input.frontNumber);
    const primaryFarmId = this.resolveOrderPrimaryFarmId(input.farmId, input.fieldIds);
    const result = this.db
      .prepare(`
        UPDATE harvest_orders
        SET number = ?, front_number = ?, farm_id = ?,
            start_date = CASE WHEN ? = 1 THEN ? ELSE start_date END,
            end_date = CASE WHEN ? = 1 THEN ? ELSE end_date END,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
      `)
      .run(
        input.number,
        frontNumbers[0] ?? null,
        primaryFarmId,
        input.startDate !== undefined ? 1 : 0,
        input.startDate ?? null,
        input.endDate !== undefined ? 1 : 0,
        input.endDate ?? null,
        orderId
      );

    if (result.changes === 0) {
      return null;
    }

    this.db.prepare("DELETE FROM harvest_order_fronts WHERE order_id = ?").run(orderId);
    this.db.prepare("DELETE FROM harvest_order_fields WHERE order_id = ?").run(orderId);
    this.insertOrderFronts(orderId, frontNumbers);

    if (!haveSameFrontNumbers(previousFrontNumbers, frontNumbers)) {
      this.insertOrderHistoryEvent({
        orderId,
        orderNumber: input.number,
        eventType: resolveFrontHistoryEventType(previousFrontNumbers, frontNumbers),
        frontNumbersBefore: previousFrontNumbers,
        frontNumbersAfter: frontNumbers
      });
    }

    for (const fieldId of input.fieldIds) {
      this.db.prepare("INSERT INTO harvest_order_fields (id, order_id, field_id) VALUES (?, ?, ?)").run(
        randomUUID(),
        orderId,
        fieldId
      );
    }

    const nextFarmIds = new Set(this.getFarmIdsForFields(input.fieldIds));
    const removedFarmIds = previousFarmIds.filter((farmId) => !nextFarmIds.has(farmId));

    for (const removedFarmId of removedFarmIds) {
      this.cleanupRemovedOrderFarmLinks(orderId, removedFarmId, input.number);
    }

    return orderId;
  }

  private assertImportPreconditions(actions: OrderImportAction[]) {
    const normalizedNumbers = Array.from(new Set(actions.map((action) => normalize(action.input.number)))).sort();

    // Serializa importacoes concorrentes da mesma OS, inclusive quando a OS ainda nao existe.
    for (const normalizedNumber of normalizedNumbers) {
      this.db.prepare("SELECT pg_advisory_xact_lock(hashtextextended(?, 0))").get(normalizedNumber);
    }

    for (const action of actions) {
      const matchingOrders = this.db.prepare(`
        SELECT id, status
        FROM harvest_orders
        WHERE regexp_replace(lower(trim(number)), '[[:space:]]+', ' ', 'g') = ?
        ORDER BY id ASC
        FOR UPDATE
      `).all(normalize(action.input.number)) as Array<{ id: string; status: "ACTIVE" | "CLOSED" }>;

      if (action.type === "CREATE") {
        if (matchingOrders.length > 0) {
          throw new OrderImportConflictError();
        }
        continue;
      }

      const activeOrders = matchingOrders.filter((order) => order.status === "ACTIVE");
      if (activeOrders.length !== 1 || activeOrders[0]?.id !== action.orderId) {
        throw new OrderImportConflictError();
      }

      const currentFieldIds = this.db.prepare(`
        SELECT field_id
        FROM harvest_order_fields
        WHERE order_id = ?
        ORDER BY field_id ASC
      `).all(action.orderId) as Array<{ field_id: string }>;
      const actual = currentFieldIds.map((row) => row.field_id).sort();
      const expected = [...action.expectedFieldIds].sort();

      if (actual.length !== expected.length || actual.some((fieldId, index) => fieldId !== expected[index])) {
        throw new OrderImportConflictError();
      }
    }
  }

  private mapHarvestOrderRows(orders: OrderRow[]): HarvestOrderRecord[] {
    if (orders.length === 0) {
      return [];
    }

    const orderIds = orders.map((order) => order.id);

    // Busca apenas as fazendas necessárias para essas OS (evita carregar todo o banco)
    const allFarmIds = Array.from(new Set(orders.map((o) => o.farm_id)));
    const farmsById = new Map<string, FarmRecord>();
    this.fetchFarmsByIds(allFarmIds, farmsById);

    const orderFronts: Array<{ order_id: string; front_number: number }> = [];

    // Divide lotes grandes para manter as consultas dentro dos limites do driver.
    const chunkSize = 500;
    for (let i = 0; i < orderIds.length; i += chunkSize) {
      const chunk = orderIds.slice(i, i + chunkSize);
      const placeholders = chunk.map(() => "?").join(",");
      const chunkFronts = this.db
        .prepare(`
          SELECT order_id, front_number
          FROM harvest_order_fronts
          WHERE order_id IN (${placeholders})
          ORDER BY front_number ASC
        `)
        .all(...chunk) as Array<{ order_id: string; front_number: number }>;
      orderFronts.push(...chunkFronts);
    }

    const orderFields: OrderFieldRow[] = [];
    for (let i = 0; i < orderIds.length; i += chunkSize) {
      const chunk = orderIds.slice(i, i + chunkSize);
      const placeholders = chunk.map(() => "?").join(",");
      const chunkFields = this.db
        .prepare(`
          SELECT
            hof.id,
            hof.order_id,
            hof.field_id,
            f.code,
            f.name,
            f.area_ha,
            f.area_alq,
            f.planted_area_ha,
            f.crop_year,
            f.area_type,
            f.active,
            f.farm_id
          FROM harvest_order_fields hof
          JOIN fields f ON f.id = hof.field_id
          WHERE hof.order_id IN (${placeholders})
          ORDER BY f.code ASC
        `)
        .all(...chunk) as OrderFieldRow[];
      orderFields.push(...chunkFields);
    }

    const fieldFarmIds = Array.from(new Set(orderFields.map((f) => f.farm_id)));
    const missingFarmIds = fieldFarmIds.filter(id => !farmsById.has(id));
    this.fetchFarmsByIds(missingFarmIds, farmsById);

    const frontNumbersByOrderId = new Map<string, number[]>();
    for (const item of orderFronts) {
      const frontNumbers = frontNumbersByOrderId.get(item.order_id);
      if (frontNumbers) {
        frontNumbers.push(item.front_number);
      } else {
        frontNumbersByOrderId.set(item.order_id, [item.front_number]);
      }
    }

    const fieldsByOrderId = new Map<string, MappedOrderField[]>();
    for (const item of orderFields) {
      const mappedField = {
        id: item.id,
        fieldId: item.field_id,
        field: mapField(item)
      };
      const fields = fieldsByOrderId.get(item.order_id);
      if (fields) {
        fields.push(mappedField);
      } else {
        fieldsByOrderId.set(item.order_id, [mappedField]);
      }
    }

    for (const fields of fieldsByOrderId.values()) {
      fields.sort((left, right) => compareFieldCodes(left.field.code, right.field.code));
    }

    return orders.map((order) => {
      const fields = fieldsByOrderId.get(order.id) ?? [];
      const selectedFarmIds = Array.from(new Set(fields.map((item) => item.field.farmId)));
      const farmIds = selectedFarmIds.length > 0 ? selectedFarmIds : [order.farm_id];
      const orderFarms = farmIds.map((farmId) => farmsById.get(farmId) ?? removedFarm(farmId));
      const primaryFarm = farmsById.get(order.farm_id) ?? orderFarms[0] ?? removedFarm(order.farm_id);
      const frontNumbers = frontNumbersByOrderId.get(order.id) ?? [];
      const effectiveFrontNumbers = frontNumbers.length > 0 ? frontNumbers : order.front_number ? [order.front_number] : [];

      return {
        id: order.id,
        number: order.number,
        frontNumber: effectiveFrontNumbers[0] ?? null,
        frontNumbers: effectiveFrontNumbers,
        farmId: primaryFarm.id,
        farmIds,
        status: order.status,
        startDate: order.start_date,
        endDate: order.end_date,
        farm: primaryFarm,
        farms: orderFarms,
        fields
      };
    });
  }

  private insertOrderFronts(orderId: string, frontNumbers: number[]) {
    if (frontNumbers.length === 0) return;
    const insert = this.db.prepare("INSERT INTO harvest_order_fronts (id, order_id, front_number) VALUES (?, ?, ?)");

    const paramsList = frontNumbers.map(frontNumber => [randomUUID(), orderId, frontNumber]);
    insert.runMany(paramsList);
  }

  private insertOrderHistoryEvent(input: {
    orderId: string;
    orderNumber: string;
    eventType: HarvestOrderHistoryEventType;
    frontNumbersBefore?: number[];
    frontNumbersAfter?: number[];
  }) {
    this.db.prepare(`
      INSERT INTO harvest_order_history (
        id,
        order_id,
        order_number,
        event_type,
        front_numbers_before,
        front_numbers_after,
        occurred_at
      )
      VALUES (?, ?, ?, ?, ?, ?, ?)
    `).run(
      randomUUID(),
      input.orderId,
      input.orderNumber,
      input.eventType,
      serializeFrontNumbers(input.frontNumbersBefore ?? []),
      serializeFrontNumbers(input.frontNumbersAfter ?? []),
      nextMonotonicTimestamp()
    );
  }

  private getOrderFrontNumbersById(orderId: string) {
    const rows = this.db
      .prepare("SELECT front_number FROM harvest_order_fronts WHERE order_id = ? ORDER BY front_number ASC")
      .all(orderId) as Array<{ front_number: number }>;

    if (rows.length > 0) {
      return rows.map((row) => row.front_number);
    }

    const order = this.db.prepare("SELECT front_number FROM harvest_orders WHERE id = ?").get(orderId) as
      | { front_number: number | null }
      | undefined;

    return order?.front_number ? [order.front_number] : [];
  }

  private getOrderFieldFarmIds(orderId: string) {
    const rows = this.db.prepare(`
      SELECT DISTINCT f.farm_id
      FROM harvest_order_fields hof
      JOIN fields f ON f.id = hof.field_id
      WHERE hof.order_id = ?
      ORDER BY f.farm_id ASC
    `).all(orderId) as Array<{ farm_id: string }>;

    return rows.map((row) => row.farm_id);
  }

  private getFarmIdsForFields(fieldIds: string[]) {
    if (fieldIds.length === 0) {
      return [];
    }

    const placeholders = fieldIds.map(() => "?").join(",");
    const rows = this.db.prepare(`
      SELECT DISTINCT farm_id
      FROM fields
      WHERE id IN (${placeholders})
      ORDER BY farm_id ASC
    `).all(...fieldIds) as Array<{ farm_id: string }>;

    return rows.map((row) => row.farm_id);
  }

  private cleanupRemovedOrderFarmLinks(orderId: string, farmId: string, orderNumber: string) {
    const documentResult = this.db.prepare(`
      UPDATE harvest_order_documents
      SET farm_id = NULL,
          front_number = NULL
      WHERE order_id = ?
        AND farm_id = ?
    `).run(orderId, farmId);

    const entryResult = this.db.prepare(`
      UPDATE cane_entries
      SET status = 'FARM_MISMATCH',
          notes = ?
      WHERE order_id = ?
        AND farm_id = ?
    `).run(`Fazenda removida da OS ${orderNumber}.`, orderId, farmId);

    return {
      unlinkedDocumentCount: documentResult.changes,
      reclassifiedEntryCount: entryResult.changes
    };
  }

  private resolveOrderPrimaryFarmId(farmId: string | undefined, fieldIds: string[]) {
    if (farmId) {
      return farmId;
    }

    const firstFieldId = fieldIds[0];

    if (!firstFieldId) {
      throw new Error("A OS precisa ter pelo menos um talhao.");
    }

    const row = this.db.prepare("SELECT farm_id FROM fields WHERE id = ?").get(firstFieldId) as { farm_id: string } | undefined;

    if (!row) {
      throw new Error("Talhao da OS nao encontrado.");
    }

    return row.farm_id;
  }

  private fetchFarmsByIds(farmIds: string[], targetMap: Map<string, FarmRecord>): void {
    if (farmIds.length === 0) return;

    type FarmRow = {
      id: string; code: string | null; name: string; property_number: string | null;
      sequence_number: string | null; area_ha: number | null; area_alq: number | null;
      street: string | null; city: string | null; postal_code: string | null;
      section_name: string | null; owner_name: string | null; municipality: string | null;
      crop_year: string | null; metadata_updated_at: string | null;
      total_area_alq: number | null; total_area_ha: number | null;
    };
    type FieldRow2 = {
      id: string; code: string; name: string | null; area_ha: number | null;
      area_alq: number | null; planted_area_ha: number | null; crop_year: string | null;
      area_type: string | null; active: number; farm_id: string;
    };

    const chunkSize = 500;
    for (let i = 0; i < farmIds.length; i += chunkSize) {
      const chunk = farmIds.slice(i, i + chunkSize);
      const placeholders = chunk.map(() => "?").join(",");

      const farms = this.db.prepare(`
        SELECT id, code, name, property_number, sequence_number, area_ha, area_alq, street, city,
          postal_code, section_name, owner_name, municipality, crop_year,
          metadata_updated_at, total_area_alq, total_area_ha
        FROM farms WHERE id IN (${placeholders})
      `).all(...chunk) as FarmRow[];

      const fields = this.db.prepare(`
        SELECT id, code, name, area_ha, area_alq, planted_area_ha, crop_year, area_type, active, farm_id
        FROM fields WHERE farm_id IN (${placeholders}) ORDER BY code ASC
      `).all(...chunk) as FieldRow2[];

      const fieldsByFarmId = new Map<string, FieldRow2[]>();
      for (const f of fields) {
        let list = fieldsByFarmId.get(f.farm_id);
        if (!list) {
          list = [];
          fieldsByFarmId.set(f.farm_id, list);
        }
        list.push(f);
      }

      for (const farm of farms) {
        const farmFields = fieldsByFarmId.get(farm.id) || [];
        targetMap.set(farm.id, {
          id: farm.id,
          code: farm.code ?? undefined,
          name: farm.name,
          propertyNumber: farm.property_number ?? undefined,
          sequenceNumber: farm.sequence_number ?? undefined,
          areaHa: farm.area_ha ?? undefined,
          areaAlq: farm.area_alq ?? undefined,
          street: farm.street ?? undefined,
          city: farm.city ?? undefined,
          postalCode: farm.postal_code ?? undefined,
          sectionName: farm.section_name ?? undefined,
          ownerName: farm.owner_name ?? undefined,
          municipality: farm.municipality ?? undefined,
          cropYear: farm.crop_year ?? undefined,
          totalAreaAlq: farm.total_area_alq ?? undefined,
          totalAreaHa: farm.total_area_ha ?? undefined,
          metadataUpdatedAt: farm.metadata_updated_at ?? undefined,
          fields: farmFields.map((f) => ({
            id: f.id,
            code: f.code,
            name: f.name ?? undefined,
            areaHa: f.area_ha ?? undefined,
            areaAlq: f.area_alq ?? undefined,
            plantedAreaHa: f.planted_area_ha ?? undefined,
            cropYear: f.crop_year ?? undefined,
            areaType: f.area_type ?? null,
            active: Boolean(f.active),
            farmId: f.farm_id
          }))
        });
      }
    }
  }
}

function mapField(row: OrderFieldRow): FieldRecord {
  return {
    id: row.field_id,
    code: row.code,
    name: row.name,
    areaHa: row.area_ha,
    areaAlq: row.area_alq,
    plantedAreaHa: row.planted_area_ha,
    cropYear: row.crop_year,
    areaType: row.area_type,
    active: Boolean(row.active),
    farmId: row.farm_id
  };
}

function removedFarm(farmId: string): FarmRecord {
  return { id: farmId, name: "Fazenda removida", fields: [] };
}

function normalizeOrderFrontNumbers(frontNumbers?: number[], frontNumber?: number | null) {
  const values = [...(frontNumbers ?? []), ...(frontNumber ? [frontNumber] : [])];

  return Array.from(
    new Set(
      values
        .map((value) => Number(value))
        .filter((value) => Number.isInteger(value) && value >= 1 && value <= 99)
    )
  ).sort((left, right) => left - right);
}

function resolveFrontHistoryEventType(before: number[], after: number[]): HarvestOrderHistoryEventType {
  if (after.length > 0 && before.length === 0) {
    return "STARTED";
  }

  if (after.length === 0) {
    return "RELEASED";
  }

  return "FRONTS_CHANGED";
}

function haveSameFrontNumbers(left: number[], right: number[]) {
  return left.length === right.length && left.every((value, index) => value === right[index]);
}

function serializeFrontNumbers(frontNumbers: number[]) {
  return JSON.stringify(frontNumbers);
}

let lastHistoryTimestampMs = 0;

function nextMonotonicTimestamp() {
  const now = Date.now();
  lastHistoryTimestampMs = Math.max(now, lastHistoryTimestampMs + 1);
  return new Date(lastHistoryTimestampMs).toISOString();
}

const fieldCodeCollator = new Intl.Collator("pt-BR", {
  numeric: true,
  sensitivity: "base"
});

function compareFieldCodes(left: string, right: string) {
  const leftNumber = parseNumericFieldCode(left);
  const rightNumber = parseNumericFieldCode(right);

  if (leftNumber !== null && rightNumber !== null && leftNumber !== rightNumber) {
    return leftNumber - rightNumber;
  }

  return fieldCodeCollator.compare(left, right);
}

function parseNumericFieldCode(value: string) {
  const trimmed = value.trim();
  return /^\d+$/.test(trimmed) ? Number(trimmed) : null;
}

function normalize(value: string) {
  return value
    .normalize("NFD")
    .replace(/\p{Diacritic}/gu, "")
    .toLowerCase()
    .trim();
}
