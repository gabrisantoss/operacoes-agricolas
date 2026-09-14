import type { Request } from "express";

export type Pagination = {
  limit: number;
  offset: number;
  requested: boolean;
};

type PaginationOptions = {
  defaultLimit?: number;
  maxLimit?: number;
};

export function readPagination(query: Request["query"], options: PaginationOptions = {}): Pagination {
  const defaultLimit = options.defaultLimit ?? 200;
  const maxLimit = options.maxLimit ?? 2000;
  const requested = query.limit !== undefined || query.offset !== undefined || query.page !== undefined;
  const limit = parseBoundedInteger(readQueryValue(query, "limit"), defaultLimit, 1, maxLimit);
  const page = parseBoundedInteger(readQueryValue(query, "page"), 1, 1);
  const explicitOffset = query.offset !== undefined;
  const offset = explicitOffset
    ? parseBoundedInteger(readQueryValue(query, "offset"), 0, 0)
    : (page - 1) * limit;

  return { limit, offset, requested };
}

export function paginateList<T>(items: T[], pagination: Pagination) {
  return {
    items: items.slice(pagination.offset, pagination.offset + pagination.limit),
    total: items.length,
    limit: pagination.limit,
    offset: pagination.offset
  };
}

function readQueryValue(query: Request["query"], key: string) {
  const value = query[key];

  if (Array.isArray(value)) {
    return typeof value[0] === "string" ? value[0] : "";
  }

  return typeof value === "string" ? value : "";
}

function parseBoundedInteger(value: string, fallback: number, minimum: number, maximum?: number) {
  const parsed = Number.parseInt(value, 10);
  const safeValue = Number.isFinite(parsed) ? parsed : fallback;
  const withMinimum = Math.max(minimum, safeValue);
  return maximum === undefined ? withMinimum : Math.min(withMinimum, maximum);
}
