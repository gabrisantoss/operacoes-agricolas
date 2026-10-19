import { randomUUID } from "node:crypto";
import type { OrderImportPreview } from "../services/orderImportPlan.js";

type Statement = {
  all(...params: unknown[]): unknown[];
  get(...params: unknown[]): unknown;
  run(...params: unknown[]): unknown;
};

type DatabaseAdapter = {
  prepare(sql: string): Statement;
};

export const ORDER_IMPORT_FILE_HASH_UNIQUE_INDEX = "idx_order_import_batches_file_hash";

export type OrderImportBatchSummary = {
  id: string;
  fileName: string;
  fileHash: string;
  sourceLabel: string;
  importedAt: string;
  importedByName: string | null;
  rowCount: number;
  createCount: number;
  updateCount: number;
  skippedCount: number;
  divergenceCount: number;
};

export type OrderImportBatchDetail = OrderImportBatchSummary & {
  items: OrderImportPreview["items"];
  divergences: OrderImportPreview["divergences"];
};

type BatchRow = {
  id: string;
  file_name: string;
  file_hash: string;
  source_label: string;
  imported_at: string | Date;
  imported_by_name: string | null;
  row_count: number | string;
  create_count: number | string;
  update_count: number | string;
  skipped_count: number | string;
  divergence_count: number | string;
  items_json?: unknown;
  divergences_json?: unknown;
};

const summaryColumns = `
  b.id, b.file_name, b.file_hash, b.source_label, b.imported_at, u.name AS imported_by_name,
  b.row_count, b.create_count, b.update_count, b.skipped_count, b.divergence_count
`;

/** Read-only history of spreadsheets exported from the official system and imported here. */
export class OrderImportHistoryRepository {
  constructor(private readonly db: DatabaseAdapter) {}

  findByFileHash(fileHash: string) {
    const row = this.db
      .prepare(`SELECT ${summaryColumns} FROM order_import_batches b LEFT JOIN users u ON u.id = b.imported_by_id WHERE b.file_hash = ?`)
      .get(fileHash) as BatchRow | undefined;
    return row ? toSummary(row) : null;
  }

  insert(preview: OrderImportPreview, importedById: string | null) {
    const id = randomUUID();
    this.db
      .prepare(`
        INSERT INTO order_import_batches (
          id, file_name, file_hash, source_label, imported_by_id, row_count, create_count, update_count,
          skipped_count, divergence_count, items_json, divergences_json
        )
        VALUES (?, ?, ?, 'EXCEL', ?, ?, ?, ?, ?, ?, ?::jsonb, ?::jsonb)
      `)
      .run(
        id,
        preview.fileName,
        preview.fileHash,
        importedById,
        preview.summary.rowCount,
        preview.summary.createCount,
        preview.summary.updateCount,
        preview.summary.skippedCount,
        preview.summary.divergenceCount,
        JSON.stringify(preview.items),
        JSON.stringify(preview.divergences)
      );
    return id;
  }

  list(limit = 50) {
    const rows = this.db
      .prepare(`
        SELECT ${summaryColumns}
        FROM order_import_batches b
        LEFT JOIN users u ON u.id = b.imported_by_id
        ORDER BY b.imported_at DESC
        LIMIT ?
      `)
      .all(Math.min(Math.max(Math.trunc(limit), 1), 500)) as BatchRow[];
    return rows.map(toSummary);
  }

  find(id: string): OrderImportBatchDetail | null {
    const row = this.db
      .prepare(`
        SELECT ${summaryColumns}, b.items_json, b.divergences_json
        FROM order_import_batches b
        LEFT JOIN users u ON u.id = b.imported_by_id
        WHERE b.id = ?
      `)
      .get(id) as BatchRow | undefined;
    if (!row) return null;

    return {
      ...toSummary(row),
      items: parseJsonArray(row.items_json) as OrderImportBatchDetail["items"],
      divergences: parseJsonArray(row.divergences_json) as OrderImportBatchDetail["divergences"]
    };
  }
}

export function isDuplicateOrderImportFileError(error: unknown) {
  if (!error || typeof error !== "object") return false;
  const postgresError = error as { code?: string; constraint?: string; message?: string; detail?: string };
  if (postgresError.code !== "23505") return false;
  return [postgresError.constraint, postgresError.message, postgresError.detail]
    .filter((value): value is string => typeof value === "string")
    .some((value) => value.includes(ORDER_IMPORT_FILE_HASH_UNIQUE_INDEX));
}

function toSummary(row: BatchRow): OrderImportBatchSummary {
  return {
    id: row.id,
    fileName: row.file_name,
    fileHash: row.file_hash,
    sourceLabel: row.source_label,
    importedAt: row.imported_at instanceof Date ? row.imported_at.toISOString() : String(row.imported_at),
    importedByName: row.imported_by_name,
    rowCount: Number(row.row_count),
    createCount: Number(row.create_count),
    updateCount: Number(row.update_count),
    skippedCount: Number(row.skipped_count),
    divergenceCount: Number(row.divergence_count)
  };
}

function parseJsonArray(value: unknown) {
  if (Array.isArray(value)) return value;
  if (typeof value !== "string") return [];
  try {
    const parsed = JSON.parse(value);
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}
