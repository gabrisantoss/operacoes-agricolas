import "dotenv/config";
import { randomUUID } from "node:crypto";
import { createRequire } from "node:module";
import { PostgresSyncDatabase } from "./postgresSync.js";
import { formatFarmCode as formatStoredFarmCode, normalizeFarmText } from "@balanca/shared";
import { FarmsRepository } from "./repositories/farmsRepository.js";




import { OrdersRepository } from "./repositories/ordersRepository.js";
import {
  BackgroundJobRepository,
  type BackgroundJobKind,
  type BackgroundJobRecord
} from "./repositories/backgroundJobRepository.js";

import {
  PostHarvestIntegrationRepository,
  type CreatePostHarvestIntegrationEventInput,
  type PostHarvestIntegrationEventRecord,
  type PostHarvestIntegrationEventStatus
} from "./repositories/postHarvestIntegrationRepository.js";


import {
  calculateHarvestAreaCoverage,
  classifyHarvestFarmOwnership,
  consolidateFieldProductionRows,
  harvestFarmIdentity,
  harvestFieldIdentity,
  harvestYearRange,
  hasCompleteHarvestArea,
  rankHarvestPeriods,
  summarizeUniqueHarvestAreaByDate
} from "./services/harvestMetrics.js";
import type {
  CreateFarmInput,
  CreateOrderInput,
  DashboardFilterInput,
  EntryStatus,
  FleetEquipmentType,
  FleetMovementInput,
  FleetMovementStatus,
  FleetMovementType,
  UpdateOrderInput,
  UpdateFarmInput,
  UpdateFieldInput,
  UserRole
} from "@balanca/shared";

export type { PostHarvestIntegrationEventRecord, PostHarvestIntegrationEventStatus };
export type { BackgroundJobRecord };


function resolveDatabaseProvider() {
  const provider = (process.env.DATABASE_PROVIDER ?? "postgres").trim().toLowerCase();

  if (provider === "postgres" || provider === "postgresql") {
    return "postgres" as const;
  }

  throw new Error(`DATABASE_PROVIDER invalido: ${provider}. O runtime oficial usa postgres.`);
}

function resolveDatabaseUrl() {
  const databaseUrl = process.env.DATABASE_URL?.trim() ?? process.env.POSTGRES_DATABASE_URL?.trim();

  if (!databaseUrl) {
    throw new Error(
      [
        "DATABASE_PROVIDER=postgres exige DATABASE_URL.",
        "Configure DATABASE_URL com uma URL PostgreSQL valida."
      ].join("\n")
    );
  }

  return databaseUrl;
}

type AppDatabaseStatement = {
  all(...params: unknown[]): unknown[];
  get(...params: unknown[]): unknown;
  run(...params: unknown[]): { changes: number };
  runMany(paramsList: any[]): { changes: number };
};

type AppDatabase = {
  prepare(sql: string): AppDatabaseStatement;
  exec(sql: string): unknown;
  transaction<TArgs extends unknown[], TResult>(fn: (...args: TArgs) => TResult): (...args: TArgs) => TResult;
  backup?: (target: string) => Promise<unknown>;
  close?: () => unknown;
};

function createDatabase(): AppDatabase {
  resolveDatabaseProvider();
  return new PostgresSyncDatabase(resolveDatabaseUrl()) as unknown as AppDatabase;
}

export const db: AppDatabase = createDatabase();

const farmsRepository = new FarmsRepository(db);
const ordersRepository = new OrdersRepository(db);
const backgroundJobRepository = new BackgroundJobRepository(db);

const postHarvestIntegrationRepository = new PostHarvestIntegrationRepository(db);





export type UserRecord = {
  id: string;
  name: string;
  email: string;
  passwordHash: string;
  role: UserRole;
  active: boolean;
};

export type FieldRecord = {
  id: string;
  code: string;
  name?: string | null;
  areaHa?: number | null;
  areaAlq?: number | null;
  plantedAreaHa?: number | null;
  cropYear?: string | null;
  areaType?: string | null;
  active?: boolean;
  farmId: string;
};

export type FarmRecord = {
  id: string;
  code?: string | null;
  name: string;
  propertyNumber?: string | null;
  sequenceNumber?: string | null;
  areaHa?: number | null;
  areaAlq?: number | null;
  street?: string | null;
  city?: string | null;
  postalCode?: string | null;
  sectionName?: string | null;
  ownerName?: string | null;
  municipality?: string | null;
  cropYear?: string | null;
  totalAreaAlq?: number | null;
  totalAreaHa?: number | null;
  metadataUpdatedAt?: string | null;
  fields: FieldRecord[];
};

export type HarvestOrderRecord = {
  id: string;
  number: string;
  frontNumber?: number | null;
  frontNumbers: number[];
  farmId: string;
  farmIds: string[];
  status: "ACTIVE" | "CLOSED";
  startDate?: string | null;
  endDate?: string | null;
  farm: FarmRecord;
  farms: FarmRecord[];
  fields: Array<{
    id: string;
    fieldId: string;
    field: FieldRecord;
  }>;
};

export type HarvestOrderHistoryEventType = "STARTED" | "RELEASED" | "FRONTS_CHANGED" | "CLOSED" | "REOPENED";

export type HarvestOrderHistoryRecord = {
  id: string;
  orderId?: string | null;
  orderNumber: string;
  eventType: HarvestOrderHistoryEventType;
  frontNumbersBefore: number[];
  frontNumbersAfter: number[];
  occurredAt: string;
};

export type ImportBatchRecord = {
  id: string;
  fileName: string;
  storedFileName?: string | null;
  mimeType?: string | null;
  fileSize?: number | null;
  fileHash?: string | null;
  sourceType?: string | null;
  reportDate?: string | null;
  periodStart?: string | null;
  periodEnd?: string | null;
  totalNetWeight?: number | null;
  totalTrips?: number | null;
  importedById?: string | null;
  importedAt: string;
  rowCount: number;
  okCount: number;
  errorCount: number;
  entryDateFrom?: string | null;
  entryDateTo?: string | null;
};

export type ImportBatchEntryRecord = {
  id: string;
  ticketNumber?: string | null;
  entryDate?: string | null;
  farmNameRaw?: string | null;
  farmCodeRaw?: string | null;
  fieldCodeRaw?: string | null;
  orderNumberRaw?: string | null;
  vehiclePlate?: string | null;
  grossWeight?: number | null;
  netWeight?: number | null;
  status: EntryStatus;
  notes?: string | null;
};

export type CaneEntryInsertInput = {
  batchId: string;
  ticketNumber?: string;
  entryDate?: Date;
  farmId?: string;
  farmNameRaw?: string;
  farmCodeRaw?: string;
  fieldId?: string;
  fieldCodeRaw?: string;
  orderId?: string;
  orderNumberRaw?: string;
  vehiclePlate?: string;
  grossWeight?: number;
  netWeight?: number;
  status: EntryStatus;
  notes?: string;
};

export type CaneEntryImportInput = Omit<CaneEntryInsertInput, "batchId">;

export type ImportBatchMetadataInput = {
  fileHash?: string;
  sourceType?: string;
  reportDate?: Date;
  periodStart?: Date;
  periodEnd?: Date;
  totalNetWeight?: number;
  totalTrips?: number;
};

export type DivergenceExportRow = {
  fileName: string;
  importedAt: string;
  reportDate: string | null;
  periodStart: string | null;
  periodEnd: string | null;
  ticketNumber: string | null;
  entryDate: string | null;
  farmCode: string | null;
  farmNameRaw: string | null;
  fieldCodeRaw: string | null;
  orderNumberRaw: string | null;
  vehiclePlate: string | null;
  grossWeight: number | null;
  netWeight: number | null;
  fieldAreaHa: number | null;
  fieldAreaAlq: number | null;
  status: EntryStatus;
  notes: string | null;
};

export type FieldProductionRow = {
  farmId: string | null;
  farmCode: string | null;
  farmName: string;
  fieldId: string | null;
  fieldCode: string;
  fieldName: string | null;
  areaHa: number | null;
  areaAlq: number | null;
  entryCount: number;
  okCount: number;
  divergentCount: number;
  totalNetWeight: number;
  okNetWeight: number;
  divergentNetWeight: number;
  firstReportDate: string | null;
  lastReportDate: string | null;
  lastImportedAt: string | null;
};

export type ProductionPeriodRow = {
  periodStart: string | null;
  periodEnd: string | null;
  entryCount: number;
  farmCount: number;
  fieldCount: number;
  totalNetWeight: number;
  divergentNetWeight: number;
};

export type HarvestOwnershipType = "OWN" | "SUPPLIER" | "UNKNOWN";

export type HarvestOwnershipRow = {
  type: HarvestOwnershipType;
  label: string;
  farmCount: number;
  fieldCount: number;
  entryCount: number;
  totalNetWeight: number;
  areaHa: number;
  areaAlq: number;
  percentage: number;
  tch: number | null;
  tca: number | null;
};

export type HarvestRankingRow = {
  farmId: string | null;
  farmCode: string | null;
  farmName: string;
  ownershipType: HarvestOwnershipType;
  fieldCount: number;
  entryCount: number;
  totalNetWeight: number;
  areaHa: number;
  areaAlq: number;
  tch: number | null;
  percentage: number;
};

export type HarvestFieldRankingRow = {
  farmCode: string | null;
  farmName: string;
  fieldCode: string;
  ownershipType: HarvestOwnershipType;
  entryCount: number;
  totalNetWeight: number;
  areaHa: number | null;
  areaAlq: number | null;
  tch: number | null;
};

export type HarvestExecutiveDashboard = {
  generatedAt: string;
  rule: string;
  totals: {
    farms: number;
    fields: number;
    entries: number;
    totalNetWeight: number;
    divergentNetWeight: number;
    areaHa: number;
    areaAlq: number;
    tch: number | null;
    tca: number | null;
    netWeightWithArea: number;
    netWeightWithoutArea: number;
    areaCoveragePercentage: number;
    entriesWithoutArea: number;
    fieldsWithoutArea: number;
    ownNetWeight: number;
    supplierNetWeight: number;
    unknownNetWeight: number;
    ownPercentage: number;
    supplierPercentage: number;
  };
  periodStart: string | null;
  periodEnd: string | null;
  ownership: HarvestOwnershipRow[];
  topFarms: HarvestRankingRow[];
  topFields: HarvestFieldRankingRow[];
  periods: ProductionPeriodRow[];
};

































export type FleetMovementRecord = {
  id: string;
  movementType: FleetMovementType;
  equipmentCode: string;
  equipmentType: FleetEquipmentType;
  frontNumber?: number | null;
  reserveCode?: string | null;
  replacesCode?: string | null;
  reason?: string | null;
  status: FleetMovementStatus;
  occurredAt: string;
  createdAt: string;
  updatedAt: string;
};

type UserRow = {
  id: string;
  name: string;
  email: string;
  password_hash: string;
  role: UserRole;
  active: number;
};

type FarmRow = {
  id: string;
  code: string | null;
  name: string;
  property_number: string | null;
  sequence_number: string | null;
  area_ha: number | null;
  area_alq: number | null;
  street: string | null;
  city: string | null;
  postal_code: string | null;
  section_name: string | null;
  owner_name: string | null;
  municipality: string | null;
  crop_year: string | null;
  total_area_alq: number | null;
  total_area_ha: number | null;
  metadata_updated_at: string | null;
};

type HarvestOrderHistoryRow = {
  id: string;
  order_id: string | null;
  order_number: string;
  event_type: HarvestOrderHistoryEventType;
  front_numbers_before: string | unknown[];
  front_numbers_after: string | unknown[];
  occurred_at: string;
};

type ImportBatchRow = {
  id: string;
  file_name: string;
  stored_file_name?: string | null;
  mime_type?: string | null;
  file_size?: number | null;
  file_hash?: string | null;
  source_type?: string | null;
  report_date?: string | null;
  period_start?: string | null;
  period_end?: string | null;
  total_net_weight?: number | null;
  total_trips?: number | null;
  imported_by_id: string | null;
  imported_at: string;
  row_count: number;
  ok_count: number;
  error_count: number;
  entry_date_from?: string | null;
  entry_date_to?: string | null;
};



type FleetMovementRow = {
  id: string;
  movement_type: FleetMovementType;
  equipment_code: string;
  equipment_type: FleetEquipmentType;
  front_number: number | null;
  reserve_code: string | null;
  replaces_code: string | null;
  reason: string | null;
  status: FleetMovementStatus;
  occurred_at: string;
  created_at: string;
  updated_at: string;
};

export function createUser(input: {
  id?: string;
  name: string;
  email: string;
  passwordHash: string;
  role: UserRole;
  active: boolean;
  replace?: boolean;
}) {
  const id = input.id ?? randomUUID();
  const statement = input.replace
    ? db.prepare(`
        INSERT INTO users (id, name, email, password_hash, role, active)
        VALUES (@id, @name, @email, @passwordHash, @role, @active)
        ON CONFLICT(id) DO UPDATE SET
          name = excluded.name,
          email = excluded.email,
          password_hash = excluded.password_hash,
          role = excluded.role,
          active = excluded.active
      `)
    : db.prepare(`
        INSERT INTO users (id, name, email, password_hash, role, active)
        VALUES (@id, @name, @email, @passwordHash, @role, @active)
      `);

  statement.run({
    id,
    name: input.name,
    email: input.email,
    passwordHash: input.passwordHash,
    role: input.role,
    active: input.active ? 1 : 0
  });

  return findUserByEmail(input.email);
}

export function findUserByEmail(email: string) {
  const row = db
    .prepare("SELECT id, name, email, password_hash, role, active FROM users WHERE email = ?")
    .get(email) as UserRow | undefined;

  return row ? mapUser(row) : null;
}

export function listFarms(): FarmRecord[] {
  return farmsRepository.listFarms();
}

export function findFarmById(farmId: string): FarmRecord | null {
  return farmsRepository.findFarmById(farmId);
}

export function createFarm(input: CreateFarmInput) {
  return farmsRepository.createFarm(input);
}

export function updateFarm(farmId: string, input: UpdateFarmInput) {
  return farmsRepository.updateFarm(farmId, input);
}

















export function createField(farmId: string, code: string, name?: string | null, areaAlq?: number | null) {
  return farmsRepository.createField(farmId, code, name, areaAlq);
}

export function updateField(fieldId: string, input: UpdateFieldInput) {
  return farmsRepository.updateField(fieldId, input);
}

function roundArea(value: number) {
  return Math.round(value * 1000) / 1000;
}

export function listOrders(): HarvestOrderRecord[] {
  return ordersRepository.listOrders();
}

export function listOrdersByYear(year: number): HarvestOrderRecord[] {
  return ordersRepository.listOrdersByYear(year);
}

export function listAvailableYears(): number[] {
  return ordersRepository.listAvailableYears();
}

function parseFrontNumbersSnapshot(value: string | unknown[] | null) {
  if (!value) {
    return [];
  }

  if (Array.isArray(value)) {
    return value.map((item) => Number(item)).filter((item) => Number.isInteger(item));
  }

  try {
    const parsed = JSON.parse(value);

    if (!Array.isArray(parsed)) {
      return [];
    }

    return parsed.map((item) => Number(item)).filter((item) => Number.isInteger(item));
  } catch {
    return [];
  }
}

export function createOrder(input: CreateOrderInput) {
  return ordersRepository.createOrder(input);
}

export function updateOrder(orderId: string, input: UpdateOrderInput) {
  return ordersRepository.updateOrder(orderId, input);
}

export function closeOrder(orderId: string) {
  return ordersRepository.closeOrder(orderId);
}

export function closeOrderWithinExistingTransaction(orderId: string) {
  return ordersRepository.closeOrderWithinExistingTransaction(orderId);
}

export function updateOrderWithinExistingTransaction(orderId: string, input: UpdateOrderInput) {
  return ordersRepository.updateOrderWithinExistingTransaction(orderId, input);
}

export function reopenOrder(orderId: string) {
  return ordersRepository.reopenOrder(orderId);
}

export function deleteOrder(orderId: string) {
  return ordersRepository.deleteOrder(orderId);
}

export function removeOrderFarm(orderId: string, farmId: string) {
  return ordersRepository.removeOrderFarm(orderId, farmId);
}

export function findActiveOrderForFront(frontNumber: number, ignoredOrderId?: string) {
  return ordersRepository.findActiveOrderForFront(frontNumber, ignoredOrderId);
}

export function listOrderHistory(limit = 200, offset = 0): HarvestOrderHistoryRecord[] {
  const safeLimit = Math.min(Math.max(Math.trunc(limit), 1), 2000);
  const safeOffset = Math.max(Math.trunc(offset), 0);
  const rows = db
    .prepare(`
      SELECT
        id,
        order_id,
        order_number,
        event_type,
        front_numbers_before,
        front_numbers_after,
        occurred_at
      FROM harvest_order_history
      ORDER BY occurred_at DESC, id DESC
      LIMIT ?
      OFFSET ?
    `)
    .all(safeLimit, safeOffset) as HarvestOrderHistoryRow[];

  return rows.map((row) => ({
    id: row.id,
    orderId: row.order_id,
    orderNumber: row.order_number,
    eventType: row.event_type,
    frontNumbersBefore: parseFrontNumbersSnapshot(row.front_numbers_before),
    frontNumbersAfter: parseFrontNumbersSnapshot(row.front_numbers_after),
    occurredAt: row.occurred_at
  }));
}

export function countOrderHistory() {
  const row = db.prepare("SELECT COUNT(*) as count FROM harvest_order_history").get() as { count: number | string };
  return Number(row.count ?? 0);
}

export function countExistingFields(fieldIds: string[]) {
  if (fieldIds.length === 0) {
    return 0;
  }

  const placeholders = fieldIds.map(() => "?").join(", ");
  const row = db
    .prepare(`SELECT COUNT(*) as count FROM fields WHERE id IN (${placeholders})`)
    .get(...fieldIds) as { count: number | string };

  return Number(row.count ?? 0);
}

export function countFieldsForFarm(farmId: string, fieldIds: string[]) {
  if (fieldIds.length === 0) {
    return 0;
  }

  const placeholders = fieldIds.map(() => "?").join(", ");
  const row = db
    .prepare(`SELECT COUNT(*) as count FROM fields WHERE farm_id = ? AND id IN (${placeholders})`)
    .get(farmId, ...fieldIds) as { count: number | string };

  return Number(row.count ?? 0);
}

export function getDashboardSummary(filters: DashboardFilterInput = {}) {
  const where = buildEntryWhere(filters);
  const divergentWhere = appendWhere(where, "ce.status != 'OK'");

  const totalEntries = (
    db
      .prepare(`
        SELECT COUNT(*) as count
        FROM cane_entries ce
        JOIN import_batches b ON b.id = ce.batch_id
        ${where.sql}
      `)
      .get(...where.params) as { count: number }
  ).count;
  const divergentEntries = (
    db
      .prepare(`
        SELECT COUNT(*) as count
        FROM cane_entries ce
        JOIN import_batches b ON b.id = ce.batch_id
        ${divergentWhere.sql}
      `)
      .get(...divergentWhere.params) as { count: number }
  ).count;
  const byStatus = db
    .prepare(`
      SELECT ce.status, COUNT(*) as count
      FROM cane_entries ce
      JOIN import_batches b ON b.id = ce.batch_id
      ${where.sql}
      GROUP BY ce.status
      ORDER BY count DESC
    `)
    .all(...where.params) as Array<{ status: EntryStatus; count: number }>;
  const areaByDate = listHarvestAreaByDate(where);
  const totalArea = areaByDate.reduce(
    (total, item) => ({
      areaHa: total.areaHa + item.areaHa,
      areaAlq: total.areaAlq + item.areaAlq
    }),
    { areaHa: 0, areaAlq: 0 }
  );
  const recentDivergences = db
    .prepare(`
      SELECT ce.id, ce.ticket_number, ce.farm_name_raw, farm.name AS farm_name,
             ce.field_code_raw, ce.order_number_raw,
             ce.status, ce.notes, b.file_name, b.imported_at
      FROM cane_entries ce
      JOIN import_batches b ON b.id = ce.batch_id
      LEFT JOIN fields field ON field.id = ce.field_id
      LEFT JOIN farms farm ON farm.id = COALESCE(ce.farm_id, field.farm_id)
      ${divergentWhere.sql}
      ORDER BY ce.created_at DESC
      LIMIT 25
    `)
    .all(...divergentWhere.params) as Array<{
      id: string;
      ticket_number: string | null;
      farm_name_raw: string | null;
      farm_name: string | null;
      field_code_raw: string | null;
      order_number_raw: string | null;
      status: EntryStatus;
      notes: string | null;
      file_name: string;
      imported_at: string;
    }>;
  const recentBatches = listImportBatches(8);

  return {
    totalEntries,
    okEntries: totalEntries - divergentEntries,
    divergentEntries,
    byStatus,
    areaHa: totalArea.areaHa,
    areaAlq: totalArea.areaAlq,
    areaByDate,
    recentDivergences: recentDivergences.map((entry) => ({
      id: entry.id,
      ticketNumber: entry.ticket_number,
      farmNameRaw: farmNameForDisplay(entry.farm_name_raw, entry.farm_name),
      fieldCodeRaw: entry.field_code_raw,
      orderNumberRaw: entry.order_number_raw,
      status: entry.status,
      notes: entry.notes,
      batch: {
        fileName: entry.file_name,
        importedAt: entry.imported_at
      }
    })),
    recentBatches
  };
}

function listHarvestAreaByDate(where: SqlWhere) {
  const areaWhere = appendWhere(appendWhere(where, "ce.field_id IS NOT NULL"), "ce.entry_date IS NOT NULL");
  const rows = db
    .prepare(`
      WITH dated_fields AS (
        SELECT
          substr(CAST(ce.entry_date AS TEXT), 1, 10) AS entry_day,
          ce.field_id,
          MAX(CASE WHEN ce.status != 'OK' THEN 1 ELSE 0 END) AS has_divergence
        FROM cane_entries ce
        JOIN import_batches b ON b.id = ce.batch_id
        ${areaWhere.sql}
        GROUP BY entry_day, ce.field_id
      )
      SELECT
        df.entry_day,
        df.field_id,
        f.area_ha,
        f.area_alq,
        df.has_divergence
      FROM dated_fields df
      JOIN fields f ON f.id = df.field_id
      ORDER BY df.entry_day ASC, df.field_id ASC
    `)
    .all(...areaWhere.params) as Array<{
    entry_day: string;
    field_id: string;
    area_ha: number | null;
    area_alq: number | null;
    has_divergence: number;
  }>;

  return summarizeUniqueHarvestAreaByDate(
    rows.map((row) => ({
      date: row.entry_day,
      fieldId: row.field_id,
      areaHa: row.area_ha,
      areaAlq: row.area_alq,
      hasDivergence: row.has_divergence === 1
    }))
  );
}

export function listDivergencesForExport(filters: DashboardFilterInput = {}, limit = 20_001): DivergenceExportRow[] {
  const where = appendWhere(buildEntryWhere(filters), "ce.status != 'OK'");
  const boundedLimit = Math.min(Math.max(Math.trunc(limit), 1), 100_001);

  const rows = db
    .prepare(`
      SELECT b.file_name, b.imported_at, b.report_date, b.period_start, b.period_end,
             ce.ticket_number, ce.entry_date, ce.farm_name_raw, farm.name AS farm_name,
             ce.field_code_raw, ce.order_number_raw, ce.vehicle_plate, ce.gross_weight,
             ce.net_weight, ce.status, ce.notes, farm.code AS farm_code,
             field.area_ha AS field_area_ha, field.area_alq AS field_area_alq
      FROM cane_entries ce
      JOIN import_batches b ON b.id = ce.batch_id
      LEFT JOIN fields field ON field.id = ce.field_id
      LEFT JOIN farms farm ON farm.id = COALESCE(ce.farm_id, field.farm_id)
      ${where.sql}
      ORDER BY COALESCE(CAST(b.period_start AS TEXT), substr(CAST(ce.entry_date AS TEXT), 1, 10)) ASC,
               COALESCE(CAST(b.period_end AS TEXT), substr(CAST(ce.entry_date AS TEXT), 1, 10)) ASC,
               ce.status ASC, farm.code ASC, ce.farm_name_raw ASC, ce.field_code_raw ASC, ce.created_at DESC
      LIMIT ?
    `)
    .all(...where.params, boundedLimit) as Array<{
      file_name: string;
      imported_at: string;
      report_date: string | null;
      period_start: string | null;
      period_end: string | null;
      ticket_number: string | null;
      entry_date: string | null;
      farm_code: string | null;
      farm_name_raw: string | null;
      farm_name: string | null;
      field_code_raw: string | null;
      order_number_raw: string | null;
      vehicle_plate: string | null;
      gross_weight: number | null;
      net_weight: number | null;
      field_area_ha: number | null;
      field_area_alq: number | null;
      status: EntryStatus;
      notes: string | null;
    }>;

  return rows.map((row) => ({
    fileName: row.file_name,
    importedAt: row.imported_at,
    reportDate: row.report_date,
    periodStart: row.period_start,
    periodEnd: row.period_end,
    ticketNumber: row.ticket_number,
    entryDate: row.entry_date,
    farmCode: row.farm_code,
    farmNameRaw: farmNameForDisplay(row.farm_name_raw, row.farm_name),
    fieldCodeRaw: row.field_code_raw,
    orderNumberRaw: row.order_number_raw,
    vehiclePlate: row.vehicle_plate,
    grossWeight: row.gross_weight,
    netWeight: row.net_weight,
    fieldAreaHa: row.field_area_ha,
    fieldAreaAlq: row.field_area_alq,
    status: row.status,
    notes: row.notes
  }));
}

export function getFieldProductionDashboard(filters: DashboardFilterInput = {}) {
  const where = buildEntryWhere(filters);
  const rows = db
    .prepare(
      `
      SELECT
        farm.id AS farm_id,
        COALESCE(farm.code, ce.farm_code_raw) AS farm_code,
        CASE WHEN farm.id IS NOT NULL THEN farm.name ELSE COALESCE(ce.farm_name_raw, '-') END AS farm_name,
        f.id AS field_id,
        CASE WHEN f.id IS NOT NULL THEN f.code ELSE COALESCE(ce.field_code_raw, '-') END AS field_code,
        f.name AS field_name,
        f.area_ha,
        f.area_alq,
        COUNT(*) AS entry_count,
        SUM(CASE WHEN ce.status = 'OK' THEN 1 ELSE 0 END) AS ok_count,
        SUM(CASE WHEN ce.status != 'OK' THEN 1 ELSE 0 END) AS divergent_count,
        COALESCE(SUM(ce.net_weight), 0) AS total_net_weight,
        COALESCE(SUM(CASE WHEN ce.status = 'OK' THEN ce.net_weight ELSE 0 END), 0) AS ok_net_weight,
        COALESCE(SUM(CASE WHEN ce.status != 'OK' THEN ce.net_weight ELSE 0 END), 0) AS divergent_net_weight,
        MIN(COALESCE(CAST(b.period_start AS TEXT), CAST(b.report_date AS TEXT), substr(CAST(ce.entry_date AS TEXT), 1, 10))) AS first_report_date,
        MAX(COALESCE(CAST(b.period_end AS TEXT), CAST(b.report_date AS TEXT), CAST(b.period_start AS TEXT), substr(CAST(ce.entry_date AS TEXT), 1, 10))) AS last_report_date,
        MAX(b.imported_at) AS last_imported_at
      FROM cane_entries ce
      JOIN import_batches b ON b.id = ce.batch_id
      LEFT JOIN fields f ON f.id = ce.field_id
      LEFT JOIN farms farm ON farm.id = COALESCE(ce.farm_id, f.farm_id)
      ${where.sql}
      GROUP BY
        farm.id,
        COALESCE(farm.code, ce.farm_code_raw),
        CASE WHEN farm.id IS NOT NULL THEN farm.name ELSE COALESCE(ce.farm_name_raw, '-') END,
        f.id,
        CASE WHEN f.id IS NOT NULL THEN f.code ELSE COALESCE(ce.field_code_raw, '-') END,
        f.name,
        f.area_ha,
        f.area_alq
      ORDER BY farm_name ASC, field_code ASC
      `
    )
    .all(...where.params) as Array<{
    farm_id: string | null;
    farm_code: string | null;
    farm_name: string;
    field_id: string | null;
    field_code: string;
    field_name: string | null;
    area_ha: number | null;
    area_alq: number | null;
    entry_count: number;
    ok_count: number;
    divergent_count: number;
    total_net_weight: number;
    ok_net_weight: number;
    divergent_net_weight: number;
    first_report_date: string | null;
    last_report_date: string | null;
    last_imported_at: string | null;
  }>;
  const periods = db
    .prepare(
      `
      SELECT
        COALESCE(CAST(b.period_start AS TEXT), CAST(b.report_date AS TEXT), substr(CAST(ce.entry_date AS TEXT), 1, 10)) AS period_start,
        COALESCE(CAST(b.period_end AS TEXT), CAST(b.report_date AS TEXT), CAST(b.period_start AS TEXT), substr(CAST(ce.entry_date AS TEXT), 1, 10)) AS period_end,
        COUNT(*) AS entry_count,
        COUNT(DISTINCT COALESCE(
          farm.id,
          NULLIF(regexp_replace(lower(trim(COALESCE(ce.farm_code_raw, ''))), '[^a-z0-9]', '', 'g'), ''),
          ce.farm_name_raw
        )) AS farm_count,
        COUNT(DISTINCT (
          COALESCE(
            farm.id,
            NULLIF(regexp_replace(lower(trim(COALESCE(ce.farm_code_raw, ''))), '[^a-z0-9]', '', 'g'), ''),
            ce.farm_name_raw,
            ''
          ) || '::' || COALESCE(f.id, ce.field_code_raw, '')
        )) AS field_count,
        COALESCE(SUM(ce.net_weight), 0) AS total_net_weight,
        COALESCE(SUM(CASE WHEN ce.status != 'OK' THEN ce.net_weight ELSE 0 END), 0) AS divergent_net_weight
      FROM cane_entries ce
      JOIN import_batches b ON b.id = ce.batch_id
      LEFT JOIN fields f ON f.id = ce.field_id
      LEFT JOIN farms farm ON farm.id = COALESCE(ce.farm_id, f.farm_id)
      ${where.sql}
      GROUP BY 1, 2
      ORDER BY 1 ASC, 2 ASC
      `
    )
    .all(...where.params) as Array<{
    period_start: string | null;
    period_end: string | null;
    entry_count: number;
    farm_count: number;
    field_count: number;
    total_net_weight: number;
    divergent_net_weight: number;
  }>;
  const fieldRows = consolidateFieldProductionRows(rows.map((row): FieldProductionRow => ({
    farmId: row.farm_id,
    farmCode: row.farm_code,
    farmName: row.farm_name,
    fieldId: row.field_id,
    fieldCode: row.field_code,
    fieldName: row.field_name,
    areaHa: row.area_ha,
    areaAlq: row.area_alq,
    entryCount: row.entry_count,
    okCount: row.ok_count,
    divergentCount: row.divergent_count,
    totalNetWeight: row.total_net_weight,
    okNetWeight: row.ok_net_weight,
    divergentNetWeight: row.divergent_net_weight,
    firstReportDate: row.first_report_date,
    lastReportDate: row.last_report_date,
    lastImportedAt: row.last_imported_at
  })));
  const periodRows: ProductionPeriodRow[] = periods.map((row) => ({
    periodStart: row.period_start,
    periodEnd: row.period_end,
    entryCount: row.entry_count,
    farmCount: row.farm_count,
    fieldCount: row.field_count,
    totalNetWeight: row.total_net_weight,
    divergentNetWeight: row.divergent_net_weight
  }));
  const farmIds = new Set(fieldRows.map(harvestFarmIdentity));

  return {
    totals: {
      farms: farmIds.size,
      fields: fieldRows.length,
      entries: fieldRows.reduce((total, row) => total + row.entryCount, 0),
      totalNetWeight: fieldRows.reduce((total, row) => total + row.totalNetWeight, 0),
      divergentNetWeight: fieldRows.reduce((total, row) => total + row.divergentNetWeight, 0)
    },
    periods: periodRows,
    rows: fieldRows
  };
}

export function getHarvestExecutiveDashboard(
  filters: DashboardFilterInput = {},
  production: ReturnType<typeof getFieldProductionDashboard> = getFieldProductionDashboard(filters)
): HarvestExecutiveDashboard {
  const farmGroups = new Map<
    string,
    {
      farmId: string | null;
      farmCode: string | null;
      farmName: string;
      ownershipType: HarvestOwnershipType;
      fieldIds: Set<string>;
      entryCount: number;
      totalNetWeight: number;
      areaHa: number;
      areaAlq: number;
    }
  >();
  const ownershipGroups = new Map<
    HarvestOwnershipType,
    {
      type: HarvestOwnershipType;
      label: string;
      farmIds: Set<string>;
      fieldIds: Set<string>;
      entryCount: number;
      totalNetWeight: number;
      areaHa: number;
      areaAlq: number;
    }
  >();

  let totalAreaHa = 0;
  let totalAreaAlq = 0;
  const areaCoverage = calculateHarvestAreaCoverage(production.rows);

  for (const row of production.rows) {
    const ownershipType = classifyHarvestFarmOwnership(row.farmCode);
    const farmKey = harvestFarmIdentity(row);
    const fieldKey = harvestFieldIdentity(row);
    const farmGroup =
      farmGroups.get(farmKey) ??
      {
        farmId: row.farmId,
        farmCode: row.farmCode,
        farmName: row.farmName,
        ownershipType,
        fieldIds: new Set<string>(),
        entryCount: 0,
        totalNetWeight: 0,
        areaHa: 0,
        areaAlq: 0
      };
    const ownershipGroup =
      ownershipGroups.get(ownershipType) ??
      {
        type: ownershipType,
        label: harvestOwnershipLabel(ownershipType),
        farmIds: new Set<string>(),
        fieldIds: new Set<string>(),
        entryCount: 0,
        totalNetWeight: 0,
        areaHa: 0,
        areaAlq: 0
      };

    const hasArea = hasCompleteHarvestArea(row);
    const areaHa = hasArea ? row.areaHa! : 0;
    const areaAlq = hasArea ? row.areaAlq! : 0;

    farmGroup.fieldIds.add(fieldKey);
    farmGroup.entryCount += row.entryCount;
    farmGroup.totalNetWeight += row.totalNetWeight;
    farmGroup.areaHa += areaHa;
    farmGroup.areaAlq += areaAlq;
    farmGroups.set(farmKey, farmGroup);

    ownershipGroup.farmIds.add(farmKey);
    ownershipGroup.fieldIds.add(fieldKey);
    ownershipGroup.entryCount += row.entryCount;
    ownershipGroup.totalNetWeight += row.totalNetWeight;
    ownershipGroup.areaHa += areaHa;
    ownershipGroup.areaAlq += areaAlq;
    ownershipGroups.set(ownershipType, ownershipGroup);

    totalAreaHa += areaHa;
    totalAreaAlq += areaAlq;
  }

  const totalNetWeight = production.totals.totalNetWeight;
  const ownership = (["OWN", "SUPPLIER", "UNKNOWN"] as const).map((type) => {
    const group =
      ownershipGroups.get(type) ??
      {
        type,
        label: harvestOwnershipLabel(type),
        farmIds: new Set<string>(),
        fieldIds: new Set<string>(),
        entryCount: 0,
        totalNetWeight: 0,
        areaHa: 0,
        areaAlq: 0
      };

    return {
      type,
      label: group.label,
      farmCount: group.farmIds.size,
      fieldCount: group.fieldIds.size,
      entryCount: group.entryCount,
      totalNetWeight: roundMetric(group.totalNetWeight),
      areaHa: roundMetric(group.areaHa),
      areaAlq: roundMetric(group.areaAlq),
      percentage: percentageOf(group.totalNetWeight, totalNetWeight),
      tch: ratioOrNull(group.totalNetWeight, group.areaHa),
      tca: ratioOrNull(group.totalNetWeight, group.areaAlq)
    };
  });
  const topFarms = Array.from(farmGroups.values())
    .map((group) => ({
      farmId: group.farmId,
      farmCode: group.farmCode,
      farmName: group.farmName,
      ownershipType: group.ownershipType,
      fieldCount: group.fieldIds.size,
      entryCount: group.entryCount,
      totalNetWeight: roundMetric(group.totalNetWeight),
      areaHa: roundMetric(group.areaHa),
      areaAlq: roundMetric(group.areaAlq),
      tch: ratioOrNull(group.totalNetWeight, group.areaHa),
      percentage: percentageOf(group.totalNetWeight, totalNetWeight)
    }))
    .sort((left, right) => right.totalNetWeight - left.totalNetWeight)
    .slice(0, 10);
  const topFields = production.rows
    .map((row) => {
      const hasArea = hasCompleteHarvestArea(row);
      return {
        farmCode: row.farmCode,
        farmName: row.farmName,
        fieldCode: row.fieldCode,
        ownershipType: classifyHarvestFarmOwnership(row.farmCode),
        entryCount: row.entryCount,
        totalNetWeight: roundMetric(row.totalNetWeight),
        areaHa: hasArea ? roundMetric(row.areaHa!) : null,
        areaAlq: hasArea ? roundMetric(row.areaAlq!) : null,
        tch: hasArea ? ratioOrNull(row.totalNetWeight, row.areaHa!) : null
      };
    })
    .sort((left, right) => right.totalNetWeight - left.totalNetWeight)
    .slice(0, 10);
  const periodStart =
    production.periods.find((period) => period.periodStart)?.periodStart ??
    production.rows.reduce<string | null>((current, row) => earliestDate(current, row.firstReportDate), null);
  const periodEnd =
    [...production.periods].reverse().find((period) => period.periodEnd ?? period.periodStart)?.periodEnd ??
    production.rows.reduce<string | null>((current, row) => latestDate(current, row.lastReportDate), null);

  return {
    generatedAt: new Date().toISOString(),
    rule: "Fazendas com codigo 1xx sao classificadas como cana propria; 2xx como fornecedor.",
    totals: {
      farms: production.totals.farms,
      fields: production.totals.fields,
      entries: production.totals.entries,
      totalNetWeight: roundMetric(totalNetWeight),
      divergentNetWeight: roundMetric(production.totals.divergentNetWeight),
      areaHa: roundMetric(totalAreaHa),
      areaAlq: roundMetric(totalAreaAlq),
      tch: ratioOrNull(totalNetWeight, totalAreaHa),
      tca: ratioOrNull(totalNetWeight, totalAreaAlq),
      netWeightWithArea: roundMetric(areaCoverage.netWeightWithArea),
      netWeightWithoutArea: roundMetric(areaCoverage.netWeightWithoutArea),
      areaCoveragePercentage: roundMetric(areaCoverage.areaCoveragePercentage),
      entriesWithoutArea: areaCoverage.entriesWithoutArea,
      fieldsWithoutArea: areaCoverage.fieldsWithoutArea,
      ownNetWeight: ownership.find((item) => item.type === "OWN")?.totalNetWeight ?? 0,
      supplierNetWeight: ownership.find((item) => item.type === "SUPPLIER")?.totalNetWeight ?? 0,
      unknownNetWeight: ownership.find((item) => item.type === "UNKNOWN")?.totalNetWeight ?? 0,
      ownPercentage: ownership.find((item) => item.type === "OWN")?.percentage ?? 0,
      supplierPercentage: ownership.find((item) => item.type === "SUPPLIER")?.percentage ?? 0
    },
    periodStart,
    periodEnd,
    ownership,
    topFarms,
    topFields,
    periods: rankHarvestPeriods(production.periods)
  };
}

export function listImportBatches(limit = 25) {
  const safeLimit = Math.max(1, Math.min(limit, 250));
  const rows = db
    .prepare(`
      SELECT
        b.id,
        b.file_name,
        b.stored_file_name,
        b.mime_type,
        b.file_size,
        b.file_hash,
        b.source_type,
        b.report_date,
        b.period_start,
        b.period_end,
        b.total_net_weight,
        b.total_trips,
        b.imported_by_id,
        b.imported_at,
        b.row_count,
        b.ok_count,
        b.error_count,
        COALESCE(CAST(b.period_start AS TEXT), MIN(substr(CAST(ce.entry_date AS TEXT), 1, 10))) AS entry_date_from,
        COALESCE(CAST(b.period_end AS TEXT), MAX(substr(CAST(ce.entry_date AS TEXT), 1, 10))) AS entry_date_to
      FROM import_batches b
      LEFT JOIN cane_entries ce ON ce.batch_id = b.id
      GROUP BY b.id
      ORDER BY b.imported_at DESC
      LIMIT ?
    `)
    .all(safeLimit) as ImportBatchRow[];

  return rows.map(mapImportBatch);
}

export function listImportBatchEntries(batchId: string): ImportBatchEntryRecord[] {
  const rows = db
    .prepare(`
      SELECT
        ce.id,
        ce.ticket_number,
        ce.entry_date,
        ce.farm_name_raw,
        farm.name AS farm_name,
        ce.field_code_raw,
        ce.order_number_raw,
        ce.vehicle_plate,
        ce.gross_weight,
        ce.net_weight,
        ce.status,
        ce.notes
      FROM cane_entries ce
      LEFT JOIN fields field ON field.id = ce.field_id
      LEFT JOIN farms farm ON farm.id = COALESCE(ce.farm_id, field.farm_id)
      WHERE ce.batch_id = ?
      ORDER BY ce.entry_date ASC, COALESCE(farm.name, ce.farm_name_raw) ASC, ce.field_code_raw ASC, ce.id ASC
    `)
    .all(batchId) as Array<{
    id: string;
    ticket_number: string | null;
    entry_date: string | null;
    farm_name_raw: string | null;
    farm_name: string | null;
    field_code_raw: string | null;
    order_number_raw: string | null;
    vehicle_plate: string | null;
    gross_weight: number | null;
    net_weight: number | null;
    status: EntryStatus;
    notes: string | null;
  }>;

  return rows.map((row) => ({
    id: row.id,
    ticketNumber: row.ticket_number,
    entryDate: row.entry_date,
    farmNameRaw: farmNameForDisplay(row.farm_name_raw, row.farm_name),
    fieldCodeRaw: row.field_code_raw,
    orderNumberRaw: row.order_number_raw,
    vehiclePlate: row.vehicle_plate,
    grossWeight: row.gross_weight,
    netWeight: row.net_weight,
    status: row.status,
    notes: row.notes
  }));
}

export function createImportBatch(input: {
  fileName: string;
  importedById?: string;
  rowCount: number;
  metadata?: ImportBatchMetadataInput;
}) {
  const id = randomUUID();

  db.prepare(`
    INSERT INTO import_batches (
      id,
      file_name,
      file_hash,
      source_type,
      report_date,
      period_start,
      period_end,
      total_net_weight,
      total_trips,
      imported_by_id,
      row_count
    )
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
  `).run(
    id,
    input.fileName,
    input.metadata?.fileHash ?? null,
    input.metadata?.sourceType ?? null,
    input.metadata?.reportDate?.toISOString().slice(0, 10) ?? null,
    input.metadata?.periodStart?.toISOString().slice(0, 10) ?? null,
    input.metadata?.periodEnd?.toISOString().slice(0, 10) ?? null,
    input.metadata?.totalNetWeight ?? null,
    input.metadata?.totalTrips ?? null,
    input.importedById ?? null,
    input.rowCount
  );

  return findImportBatch(id);
}

export function saveImportResult(input: {
  fileName: string;
  importedById?: string;
  entries: CaneEntryImportInput[];
  metadata?: ImportBatchMetadataInput;
}) {
  const save = db.transaction(() => {
    const batch = createImportBatch({
      fileName: input.fileName,
      importedById: input.importedById,
      rowCount: input.entries.length,
      metadata: input.metadata
    });

    if (!batch) {
      throw new Error("Nao foi possivel criar o lote de importacao.");
    }

    let okCount = 0;
    let errorCount = 0;

    const entriesToInsert = input.entries.map(entry => {
      if (entry.status === "OK") {
        okCount += 1;
      } else {
        errorCount += 1;
      }
      return { ...entry, batchId: batch.id };
    });

    createCaneEntries(entriesToInsert);

    return updateImportBatchCounts(batch.id, okCount, errorCount);
  });

  return save();
}

export function updateImportBatchCounts(id: string, okCount: number, errorCount: number) {
  db.prepare("UPDATE import_batches SET ok_count = ?, error_count = ? WHERE id = ?").run(okCount, errorCount, id);
  return findImportBatch(id);
}

export function findOrphanedCaneEntriesByFarm(farmId: string) {
  return db.prepare(`
    SELECT id, batch_id, field_code_raw, entry_date, notes
    FROM cane_entries
    WHERE farm_id = ? AND status IN ('FIELD_NOT_RELEASED', 'FIELD_NOT_FOUND')
  `).all(farmId) as {
    id: string;
    batch_id: string;
    field_code_raw: string | null;
    entry_date: string | null;
    notes: string | null;
  }[];
}

export function updateCaneEntryReconciliation(id: string, status: string, notes: string | null, fieldId: string | null, orderId: string | null) {
  db.prepare(`
    UPDATE cane_entries
    SET status = ?, notes = ?, field_id = ?, order_id = ?
    WHERE id = ?
  `).run(status, notes, fieldId, orderId, id);
}

export function updateCaneEntryReconciliations(updates: Array<{id: string, status: string, notes: string | null, fieldId: string | null, orderId: string | null}>) {
  if (updates.length === 0) return;
  const paramsList = updates.map(u => [u.status, u.notes, u.fieldId, u.orderId, u.id]);
  db.prepare(`
    UPDATE cane_entries
    SET status = ?, notes = ?, field_id = ?, order_id = ?
    WHERE id = ?
  `).runMany(paramsList);
}

export function recalculateImportBatchCounts(batchId: string) {
  const rows = db.prepare(`
    SELECT status, COUNT(*) as count
    FROM cane_entries
    WHERE batch_id = ?
    GROUP BY status
  `).all(batchId) as { status: string; count: number }[];

  let okCount = 0;
  let errorCount = 0;

  for (const row of rows) {
    if (row.status === "OK") {
      okCount += row.count;
    } else {
      errorCount += row.count;
    }
  }

  db.prepare("UPDATE import_batches SET ok_count = ?, error_count = ? WHERE id = ?").run(okCount, errorCount, batchId);
}

export function findImportBatchByFileHash(fileHash: string) {
  const row = db
    .prepare(`
      SELECT
        id,
        file_name,
        stored_file_name,
        mime_type,
        file_size,
        file_hash,
        source_type,
        report_date,
        period_start,
        period_end,
        total_net_weight,
        total_trips,
        imported_by_id,
        imported_at,
        row_count,
        ok_count,
        error_count,
        period_start AS entry_date_from,
        period_end AS entry_date_to
      FROM import_batches
      WHERE file_hash = ?
      ORDER BY imported_at DESC
      LIMIT 1
    `)
    .get(fileHash) as ImportBatchRow | undefined;

  return row ? mapImportBatch(row) : null;
}

export function findPdfImportBatchByPeriod(periodStart: Date, periodEnd: Date) {
  const start = periodStart.toISOString().slice(0, 10);
  const end = periodEnd.toISOString().slice(0, 10);
  const row = db
    .prepare(`
      SELECT
        id,
        file_name,
        stored_file_name,
        mime_type,
        file_size,
        file_hash,
        source_type,
        report_date,
        period_start,
        period_end,
        total_net_weight,
        total_trips,
        imported_by_id,
        imported_at,
        row_count,
        ok_count,
        error_count,
        period_start AS entry_date_from,
        period_end AS entry_date_to
      FROM import_batches
      WHERE
        (source_type = 'SCS0110P_PDF' OR lower(file_name) LIKE '%.pdf')
        AND COALESCE(period_start, report_date) = ?
        AND COALESCE(period_end, period_start, report_date) = ?
      ORDER BY imported_at DESC, id DESC
      LIMIT 1
    `)
    .get(start, end) as ImportBatchRow | undefined;

  return row ? mapImportBatch(row) : null;
}

export function updateImportBatchFile(input: {
  id: string;
  storedFileName: string;
  mimeType?: string;
  fileSize?: number;
}) {
  db.prepare("UPDATE import_batches SET stored_file_name = ?, mime_type = ?, file_size = ? WHERE id = ?").run(
    input.storedFileName,
    input.mimeType ?? null,
    input.fileSize ?? null,
    input.id
  );
  return findImportBatch(input.id);
}

export function deleteImportBatch(batchId: string) {
  db.prepare("DELETE FROM import_batches WHERE id = ?").run(batchId);
}

export function deletePdfImportBatchGroupByPeriod(from: string, to: string) {
  const rows = db
    .prepare(
      `
      SELECT
        b.id,
        b.file_name,
        b.stored_file_name,
        b.mime_type,
        b.file_size,
        b.file_hash,
        b.source_type,
        b.report_date,
        b.period_start,
        b.period_end,
        b.total_net_weight,
        b.total_trips,
        b.imported_by_id,
        b.imported_at,
        b.row_count,
        b.ok_count,
        b.error_count,
        COALESCE(CAST(b.period_start AS TEXT), MIN(substr(CAST(ce.entry_date AS TEXT), 1, 10))) AS entry_date_from,
        COALESCE(CAST(b.period_end AS TEXT), MAX(substr(CAST(ce.entry_date AS TEXT), 1, 10))) AS entry_date_to
      FROM import_batches b
      LEFT JOIN cane_entries ce ON ce.batch_id = b.id
      WHERE b.source_type = 'SCS0110P_PDF' OR lower(b.file_name) LIKE '%.pdf'
      GROUP BY b.id
      HAVING COALESCE(CAST(b.period_start AS TEXT), CAST(b.report_date AS TEXT)) = ?
         AND COALESCE(CAST(b.period_end AS TEXT), CAST(b.report_date AS TEXT), CAST(b.period_start AS TEXT)) = ?
      ORDER BY imported_at DESC
      `
    )
    .all(from, to) as ImportBatchRow[];

  const batches = rows.map(mapImportBatch);

  if (batches.length === 0) {
    return [];
  }

  const remove = db.transaction((batchIds: string[]) => {
    const statement = db.prepare("DELETE FROM import_batches WHERE id = ?");

    for (const batchId of batchIds) {
      statement.run(batchId);
    }
  });

  remove(batches.map((batch) => batch.id));
  return batches;
}

export function deleteAllPdfImportBatches() {
  const rows = db
    .prepare(
      `
      SELECT
        b.id,
        b.file_name,
        b.stored_file_name,
        b.mime_type,
        b.file_size,
        b.file_hash,
        b.source_type,
        b.report_date,
        b.period_start,
        b.period_end,
        b.total_net_weight,
        b.total_trips,
        b.imported_by_id,
        b.imported_at,
        b.row_count,
        b.ok_count,
        b.error_count,
        COALESCE(CAST(b.period_start AS TEXT), CAST(b.report_date AS TEXT), MIN(substr(CAST(ce.entry_date AS TEXT), 1, 10))) AS entry_date_from,
        COALESCE(CAST(b.period_end AS TEXT), CAST(b.report_date AS TEXT), MAX(substr(CAST(ce.entry_date AS TEXT), 1, 10))) AS entry_date_to
      FROM import_batches b
      LEFT JOIN cane_entries ce ON ce.batch_id = b.id
      WHERE b.source_type = 'SCS0110P_PDF' OR lower(b.file_name) LIKE '%.pdf'
      GROUP BY b.id
      ORDER BY b.imported_at DESC
      `
    )
    .all() as ImportBatchRow[];

  const batches = rows.map(mapImportBatch);

  if (batches.length === 0) {
    return [];
  }

  const remove = db.transaction((batchIds: string[]) => {
    const statement = db.prepare("DELETE FROM import_batches WHERE id = ?");

    for (const batchId of batchIds) {
      statement.run(batchId);
    }
  });

  remove(batches.map((batch) => batch.id));
  return batches;
}

export function createCaneEntry(input: CaneEntryInsertInput) {
  db.prepare(`
    INSERT INTO cane_entries (
      id, batch_id, ticket_number, entry_date, farm_id, farm_name_raw, farm_code_raw, field_id,
      field_code_raw, order_id, order_number_raw, vehicle_plate, gross_weight,
      net_weight, status, notes
    )
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
  `).run(
    randomUUID(),
    input.batchId,
    input.ticketNumber ?? null,
    input.entryDate?.toISOString() ?? null,
    input.farmId ?? null,
    input.farmNameRaw ?? null,
    input.farmCodeRaw ?? null,
    input.fieldId ?? null,
    input.fieldCodeRaw ?? null,
    input.orderId ?? null,
    input.orderNumberRaw ?? null,
    input.vehiclePlate ?? null,
    input.grossWeight ?? null,
    input.netWeight ?? null,
    input.status,
    input.notes ?? null
  );
}

export function createCaneEntries(inputs: CaneEntryInsertInput[]) {
  if (inputs.length === 0) return;

  const paramsList = inputs.map(input => [
    randomUUID(),
    input.batchId,
    input.ticketNumber ?? null,
    input.entryDate?.toISOString() ?? null,
    input.farmId ?? null,
    input.farmNameRaw ?? null,
    input.farmCodeRaw ?? null,
    input.fieldId ?? null,
    input.fieldCodeRaw ?? null,
    input.orderId ?? null,
    input.orderNumberRaw ?? null,
    input.vehiclePlate ?? null,
    input.grossWeight ?? null,
    input.netWeight ?? null,
    input.status,
    input.notes ?? null
  ]);

  db.prepare(`
    INSERT INTO cane_entries (
      id, batch_id, ticket_number, entry_date, farm_id, farm_name_raw, farm_code_raw, field_id,
      field_code_raw, order_id, order_number_raw, vehicle_plate, gross_weight,
      net_weight, status, notes
    )
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
  `).runMany(paramsList);
}

export function findOrderWithFields(number: string) {
  return listOrdersWithNumber(number)[0] ?? null;
}

export function listOrdersWithNumber(number: string) {
  return ordersRepository.listOrdersWithNumber(number);
}

export function findOrderById(id: string) {
  return ordersRepository.findOrderById(id);
}

export function findActiveOrderForField(farmId: string, fieldId: string) {
  return (
    listOrders().find(
      (order) =>
        order.status === "ACTIVE" &&
        order.fields.some((orderField) => orderField.fieldId === fieldId && orderField.field.farmId === farmId)
    ) ?? null
  );
}

export function findOrderForField(farmId: string, fieldId: string) {
  return (
    findActiveOrderForField(farmId, fieldId) ??
    listOrders().find((order) => order.fields.some((orderField) => orderField.fieldId === fieldId && orderField.field.farmId === farmId)) ??
    null
  );
}











export function createPostHarvestIntegrationEvents(input: CreatePostHarvestIntegrationEventInput[]) {
  return postHarvestIntegrationRepository.createEvents(input);
}













export function enqueueBackgroundJob<TPayload>(input: {
  kind: BackgroundJobKind;
  dedupeKey: string;
  payload: TPayload;
  maxAttempts?: number;
}) {
  return backgroundJobRepository.enqueue(input);
}

export function claimNextBackgroundJob<TPayload>(input: {
  kind: BackgroundJobKind;
  workerId: string;
  leaseMs?: number;
}) {
  return backgroundJobRepository.claimNext<TPayload>(input);
}

export function updateBackgroundJobProgress(
  id: string,
  workerId: string,
  input: { percent: number; stage: string; message: string; leaseMs?: number }
) {
  return backgroundJobRepository.updateProgress(id, workerId, input);
}

export function completeBackgroundJob<TPayload = unknown>(id: string, workerId: string) {
  return backgroundJobRepository.complete<TPayload>(id, workerId);
}

export function failBackgroundJob<TPayload>(job: BackgroundJobRecord<TPayload>, workerId: string, error: unknown) {
  return backgroundJobRepository.fail(job, workerId, error);
}

export function findBackgroundJobById<TPayload>(id: string) {
  return backgroundJobRepository.findById<TPayload>(id);
}

export function findLatestBackgroundJob<TPayload>(kind: BackgroundJobKind, dedupeKey: string) {
  return backgroundJobRepository.findLatest<TPayload>(kind, dedupeKey);
}

export function countBackgroundJobsQueuedBefore(kind: BackgroundJobKind, job: BackgroundJobRecord) {
  return backgroundJobRepository.countQueuedBefore(kind, job);
}

export function listPostHarvestIntegrationEvents(input?: {
  status?: PostHarvestIntegrationEventStatus;
  limit?: number;
  offset?: number;
}) {
  return postHarvestIntegrationRepository.listEvents(input);
}

export function countPostHarvestIntegrationEvents(status?: PostHarvestIntegrationEventStatus) {
  return postHarvestIntegrationRepository.countEvents(status);
}

export function summarizePostHarvestIntegrationEvents() {
  return postHarvestIntegrationRepository.summarizeEvents();
}

export function claimPostHarvestDispatchableIntegrationEvents(input: {
  workerId: string;
  limit?: number;
  leaseMs?: number;
}) {
  return postHarvestIntegrationRepository.claimDispatchableEvents(input);
}

export function claimPostHarvestIntegrationEventById(id: string, workerId: string, leaseMs?: number) {
  return postHarvestIntegrationRepository.claimEventById(id, workerId, leaseMs);
}

export function findPostHarvestIntegrationEventById(id: string) {
  return postHarvestIntegrationRepository.findEventById(id);
}

export function markPostHarvestIntegrationEventSent(
  id: string,
  workerId: string,
  input: {
    httpStatus: number;
    responseBody?: string | null;
  }
) {
  return postHarvestIntegrationRepository.markSent(id, workerId, input);
}

export function markPostHarvestIntegrationEventError(
  event: PostHarvestIntegrationEventRecord,
  workerId: string,
  input: {
    httpStatus?: number | null;
    responseBody?: string | null;
    error: string;
  }
) {
  return postHarvestIntegrationRepository.markError(event, workerId, input);
}















































export function listFleetMovements(limit = 200): FleetMovementRecord[] {
  const safeLimit = Math.max(1, Math.min(limit, 500));
  const rows = db
    .prepare(`
      SELECT id, movement_type, equipment_code, equipment_type, front_number, reserve_code,
             replaces_code, reason, status, occurred_at, created_at, updated_at
      FROM fleet_movements
      ORDER BY CASE status WHEN 'OPEN' THEN 0 ELSE 1 END, occurred_at DESC, created_at DESC
      LIMIT ?
    `)
    .all(safeLimit) as FleetMovementRow[];

  return rows.map(mapFleetMovement);
}

export function createFleetMovement(input: FleetMovementInput): FleetMovementRecord | null {
  const id = randomUUID();
  const parsedOccurredAt = input.occurredAt ? new Date(input.occurredAt) : new Date();
  const occurredAt = Number.isNaN(parsedOccurredAt.getTime()) ? new Date().toISOString() : parsedOccurredAt.toISOString();

  db.prepare(`
    INSERT INTO fleet_movements (
      id, movement_type, equipment_code, equipment_type, front_number, reserve_code,
      replaces_code, reason, status, occurred_at
    )
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
  `).run(
    id,
    input.movementType,
    input.equipmentCode,
    input.equipmentType,
    input.frontNumber ?? null,
    input.reserveCode || null,
    input.replacesCode || null,
    input.reason || null,
    input.status,
    occurredAt
  );

  return findFleetMovementById(id);
}

export function findFleetMovementById(id: string): FleetMovementRecord | null {
  const row = db
    .prepare(`
      SELECT id, movement_type, equipment_code, equipment_type, front_number, reserve_code,
             replaces_code, reason, status, occurred_at, created_at, updated_at
      FROM fleet_movements
      WHERE id = ?
    `)
    .get(id) as FleetMovementRow | undefined;

  return row ? mapFleetMovement(row) : null;
}

export function updateFleetMovementStatus(id: string, status: FleetMovementStatus): FleetMovementRecord | null {
  db.prepare("UPDATE fleet_movements SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?").run(status, id);
  return findFleetMovementById(id);
}

export function deleteFleetMovement(id: string) {
  const result = db.prepare("DELETE FROM fleet_movements WHERE id = ?").run(id);
  return result.changes > 0;
}

export function findFarmByRaw(raw: string, code?: string | null): FarmRecord | null {
  let normalizedRaw = normalize(raw);

  const customAliases: Record<string, string> = {
    "200-2362 - faz sao marcos. 45 - km": "200-2362 - fazenda sao marcos",
    "104-2203 - sitio lagoa do mamoneiro - canevari": "104-2203 - sitio lagoa do mamoneiro",
  };

  if (customAliases[normalizedRaw]) {
    normalizedRaw = customAliases[normalizedRaw];
  }

  // Expande abreviações comuns e corrige erros de digitação da balança
  normalizedRaw = normalizedRaw.replace("crisciuma", "cresciuma");

  if (normalizedRaw.startsWith("faz ")) {
    normalizedRaw = "fazenda " + normalizedRaw.slice(4);
  } else if (normalizedRaw === "faz") {
    normalizedRaw = "fazenda";
  } else if (normalizedRaw.startsWith("sit ")) {
    normalizedRaw = "sitio " + normalizedRaw.slice(4);
  } else if (normalizedRaw === "sit") {
    normalizedRaw = "sitio";
  } else if (normalizedRaw.startsWith("est ")) {
    normalizedRaw = "estancia " + normalizedRaw.slice(4);
  }

  const normalizedRawCode = normalizeFarmCode(normalizedRaw);
  const explicitCode = code?.trim();
  const normalizedCode = explicitCode ? normalizeFarmCode(explicitCode) : "";
  const canonicalCode = explicitCode ? normalizeExplicitFarmCode(explicitCode) : "";

  // Busca rápida na memória apenas com campos essenciais para evitar Memory Leak (Server Freeze)
  const allFarms = db.prepare("SELECT id, code, name FROM farms").all() as Array<{ id: string; code: string | null; name: string | null }>;

  if (explicitCode) {
    const codeMatches = allFarms.filter((farm) => {
      const farmCode = farm.code ?? "";
      return (
        normalizeFarmCode(farmCode) === normalizedCode ||
        (canonicalCode !== "" && normalizeExplicitFarmCode(farmCode) === canonicalCode)
      );
    });

    // When the source carries a code, only that code (including harmless zero
    // padding) may resolve the farm. A name fallback can join distinct suppliers.
    return codeMatches.length === 1 ? (farmsRepository.findFarmById(codeMatches[0].id) ?? null) : null;
  }

  const exactMatchId = allFarms.find(
    (farm) =>
      normalize(farm.name ?? "") === normalizedRaw ||
      normalize(farm.code ?? "") === normalizedRaw ||
      normalizeFarmCode(farm.name ?? "") === normalizedRawCode ||
      normalizeFarmCode(farm.code ?? "") === normalizedRawCode
  )?.id;

  if (exactMatchId) {
    return farmsRepository.findFarmById(exactMatchId) ?? null;
  }

  const prefixMatches = allFarms.filter((farm) => {
    const normalizedNameCode = normalizeFarmCode(farm.name ?? "");

    return (
      normalizedRawCode.length >= 12 &&
      normalizedNameCode.length >= 12 &&
      (normalizedRawCode.startsWith(normalizedNameCode) || normalizedNameCode.startsWith(normalizedRawCode))
    );
  });

  return prefixMatches.length === 1 ? (farmsRepository.findFarmById(prefixMatches[0].id) ?? null) : null;
}

export function findFieldByFarmAndCode(farmId: string, code: string) {
  const normalizedCode = normalizeFieldCode(code);

  return (
    farmsRepository.findFarmById(farmId)
      ?.fields.find((field) => normalizeFieldCode(field.code) === normalizedCode) ?? null
  );
}

function normalizeFieldCode(value: string) {
  const normalized = normalize(value).replace(/[^a-z0-9]/g, "");

  if (/^\d+$/.test(normalized)) {
    return normalized.replace(/^0+(?=\d)/, "");
  }

  return normalized;
}

export function findImportBatch(id: string) {
  const row = db
    .prepare(`
      SELECT
        id,
        file_name,
        stored_file_name,
        mime_type,
        file_size,
        file_hash,
        source_type,
        report_date,
        period_start,
        period_end,
        total_net_weight,
        total_trips,
        imported_by_id,
        imported_at,
        row_count,
        ok_count,
        error_count,
        period_start AS entry_date_from,
        period_end AS entry_date_to
      FROM import_batches
      WHERE id = ?
    `)
    .get(id) as ImportBatchRow | undefined;
  return row ? mapImportBatch(row) : null;
}

type SqlWhere = {
  sql: string;
  params: Array<string | number>;
};

function buildEntryWhere(filters: DashboardFilterInput): SqlWhere {
  const clauses: string[] = [];
  const params: Array<string | number> = [];

  if (filters.batchId) {
    clauses.push("ce.batch_id = ?");
    params.push(filters.batchId);
  }

  if (filters.status) {
    clauses.push("ce.status = ?");
    params.push(filters.status);
  }

  if (filters.farmId) {
    clauses.push("ce.farm_id = ?");
    params.push(filters.farmId);
  }

  const yearRange = harvestYearRange(filters.year);
  if (yearRange) {
    clauses.push("COALESCE(CAST(b.period_end AS TEXT), CAST(b.report_date AS TEXT), substr(CAST(ce.entry_date AS TEXT), 1, 10)) >= ?");
    params.push(yearRange.start);
    clauses.push("COALESCE(CAST(b.period_start AS TEXT), CAST(b.report_date AS TEXT), substr(CAST(ce.entry_date AS TEXT), 1, 10)) <= ?");
    params.push(yearRange.end);
  }

  const from = dateFilterValue(filters.from);
  if (from) {
    clauses.push("COALESCE(CAST(b.period_end AS TEXT), CAST(b.report_date AS TEXT), substr(CAST(ce.entry_date AS TEXT), 1, 10)) >= ?");
    params.push(from);
  }

  const to = dateFilterValue(filters.to);
  if (to) {
    clauses.push("COALESCE(CAST(b.period_start AS TEXT), CAST(b.report_date AS TEXT), substr(CAST(ce.entry_date AS TEXT), 1, 10)) <= ?");
    params.push(to);
  }

  if (filters.order) {
    clauses.push("ce.order_number_raw LIKE ?");
    params.push(`%${filters.order}%`);
  }

  if (filters.fileName) {
    clauses.push("b.file_name LIKE ?");
    params.push(`%${filters.fileName}%`);
  }

  return {
    sql: clauses.length ? `WHERE ${clauses.join(" AND ")}` : "",
    params
  };
}

function appendWhere(where: SqlWhere, clause: string): SqlWhere {
  return {
    sql: where.sql ? `${where.sql} AND ${clause}` : `WHERE ${clause}`,
    params: where.params
  };
}

function dateFilterValue(value: string | undefined) {
  if (!value) {
    return undefined;
  }

  const trimmed = value.trim();
  const dateOnly = /^(\d{4})-(\d{2})-(\d{2})$/.exec(trimmed);

  if (dateOnly) {
    const [, year, month, day] = dateOnly;
    return `${year}-${month}-${day}`;
  }

  const parsed = new Date(trimmed);
  return Number.isNaN(parsed.getTime()) ? undefined : parsed.toISOString().slice(0, 10);
}

function harvestOwnershipLabel(type: HarvestOwnershipType) {
  switch (type) {
    case "OWN":
      return "Cana propria";
    case "SUPPLIER":
      return "Fornecedor";
    default:
      return "Sem classificacao";
  }
}

function ratioOrNull(numerator: number, denominator: number) {
  return denominator > 0 ? roundMetric(numerator / denominator) : null;
}

function percentageOf(value: number, total: number) {
  return total > 0 ? roundMetric((value / total) * 100) : 0;
}

function roundMetric(value: number) {
  return Math.round(value * 1000) / 1000;
}

function earliestDate(current: string | null, next: string | null | undefined) {
  if (!next) {
    return current;
  }

  return !current || next < current ? next : current;
}

function latestDate(current: string | null, next: string | null | undefined) {
  if (!next) {
    return current;
  }

  return !current || next > current ? next : current;
}

function farmNameForDisplay(rawName: string | null | undefined, registeredName: string | null | undefined) {
  const registered = registeredName?.trim();

  if (registered) {
    return registered;
  }

  if (!rawName) {
    return null;
  }

  const cleaned = rawName
    .replace(/\bra[ií]zen\b/giu, "")
    .replace(/\s*[-/]\s*$/u, "")
    .replace(/\s{2,}/g, " ")
    .trim();

  return cleaned || null;
}

function mapUser(row: UserRow): UserRecord {
  return {
    id: row.id,
    name: row.name,
    email: row.email,
    passwordHash: row.password_hash,
    role: row.role,
    active: Boolean(row.active)
  };
}

function mapImportBatch(row: ImportBatchRow): ImportBatchRecord {
  return {
    id: row.id,
    fileName: row.file_name,
    storedFileName: row.stored_file_name ?? null,
    mimeType: row.mime_type ?? null,
    fileSize: row.file_size ?? null,
    fileHash: row.file_hash ?? null,
    sourceType: row.source_type ?? null,
    reportDate: row.report_date ?? null,
    periodStart: row.period_start ?? null,
    periodEnd: row.period_end ?? null,
    totalNetWeight: row.total_net_weight ?? null,
    totalTrips: row.total_trips ?? null,
    importedById: row.imported_by_id,
    importedAt: row.imported_at,
    rowCount: row.row_count,
    okCount: row.ok_count,
    errorCount: row.error_count,
    entryDateFrom: row.entry_date_from ?? null,
    entryDateTo: row.entry_date_to ?? null
  };
}



function mapFleetMovement(row: FleetMovementRow): FleetMovementRecord {
  return {
    id: row.id,
    movementType: row.movement_type,
    equipmentCode: row.equipment_code,
    equipmentType: row.equipment_type,
    frontNumber: row.front_number,
    reserveCode: row.reserve_code,
    replacesCode: row.replaces_code,
    reason: row.reason,
    status: row.status,
    occurredAt: row.occurred_at,
    createdAt: row.created_at,
    updatedAt: row.updated_at
  };
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

function normalizeFarmCode(value: string) {
  return normalize(value).replace(/[^a-z0-9]/g, "");
}

function normalizeExplicitFarmCode(value: string) {
  const match = /^\s*(\d{3})\D*(\d+)\s*$/.exec(value);

  if (!match) {
    return "";
  }

  const origin = match[1].replace(/^0+(?=\d)/, "");
  const supplier = match[2].replace(/^0+(?=\d)/, "");
  return `${origin}:${supplier}`;
}
