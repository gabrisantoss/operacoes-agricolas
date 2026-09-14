import { HttpError } from "../errors.js";

type CachedExport = { expiresAt: number; value: unknown };

export class ExportController {
  private active = 0;
  private readonly cache = new Map<string, CachedExport>();
  private readonly requestTimes = new Map<string, number[]>();

  constructor(private readonly options: {
    maxConcurrent: number;
    maxRequestsPerWindow: number;
    rateWindowMs: number;
    cacheTtlMs: number;
    maxCacheEntries: number;
    now?: () => number;
  }) {}

  async run<T>(input: { requestKey: string; cacheKey: string; producer: () => Promise<T> | T }) {
    const now = this.options.now?.() ?? Date.now();
    this.enforceRateLimit(input.requestKey, now);
    const cached = this.cache.get(input.cacheKey);

    if (cached && cached.expiresAt > now) {
      return { value: cached.value as T, cache: "HIT" as const };
    }
    if (cached) this.cache.delete(input.cacheKey);

    if (this.active >= this.options.maxConcurrent) {
      throw new HttpError(429, "Ha exportacoes demais em processamento. Aguarde e tente novamente.");
    }

    this.active += 1;
    try {
      const value = await input.producer();
      this.cache.set(input.cacheKey, { value, expiresAt: now + this.options.cacheTtlMs });
      this.trimCache(now);
      return { value, cache: "MISS" as const };
    } finally {
      this.active -= 1;
    }
  }

  private enforceRateLimit(requestKey: string, now: number) {
    const cutoff = now - this.options.rateWindowMs;
    const recent = (this.requestTimes.get(requestKey) ?? []).filter((timestamp) => timestamp > cutoff);
    if (recent.length >= this.options.maxRequestsPerWindow) {
      throw new HttpError(429, "Limite temporario de exportacoes atingido. Aguarde antes de tentar novamente.");
    }
    recent.push(now);
    this.requestTimes.set(requestKey, recent);
  }

  private trimCache(now: number) {
    for (const [key, cached] of this.cache) {
      if (cached.expiresAt <= now) this.cache.delete(key);
    }
    while (this.cache.size > this.options.maxCacheEntries) {
      const oldestKey = this.cache.keys().next().value as string | undefined;
      if (!oldestKey) break;
      this.cache.delete(oldestKey);
    }
  }
}

export class ExportAdmissionGate {
  private active = 0;
  private readonly requestTimes = new Map<string, number[]>();

  constructor(private readonly options: {
    maxConcurrent: number;
    maxRequestsPerWindow: number;
    rateWindowMs: number;
    now?: () => number;
  }) {}

  enter(requestKey: string) {
    const now = this.options.now?.() ?? Date.now();
    const cutoff = now - this.options.rateWindowMs;
    const recent = (this.requestTimes.get(requestKey) ?? []).filter((timestamp) => timestamp > cutoff);
    if (recent.length >= this.options.maxRequestsPerWindow) {
      throw new HttpError(429, "Limite temporario de exportacoes atingido. Aguarde antes de tentar novamente.");
    }
    if (this.active >= this.options.maxConcurrent) {
      throw new HttpError(429, "Ha exportacoes demais em processamento. Aguarde e tente novamente.");
    }
    recent.push(now);
    this.requestTimes.set(requestKey, recent);
    this.active += 1;
    let released = false;
    return () => {
      if (released) return;
      released = true;
      this.active = Math.max(0, this.active - 1);
    };
  }
}

export const exportController = new ExportController({
  maxConcurrent: 2,
  maxRequestsPerWindow: 12,
  rateWindowMs: 60_000,
  cacheTtlMs: 30_000,
  maxCacheEntries: 32
});

export const exportAdmissionGate = new ExportAdmissionGate({
  maxConcurrent: 3,
  maxRequestsPerWindow: 20,
  rateWindowMs: 60_000
});

export const MAX_EXPORT_ROWS = 20_000;

export function assertExportRowLimit(rowCount: number, maximum = MAX_EXPORT_ROWS) {
  if (rowCount > maximum) {
    throw new HttpError(413, `Exportacao excede o limite de ${maximum} linhas. Reduza o periodo ou aplique filtros.`);
  }
}

export function exportRequestIdentity(input: { userId?: string | null; ip?: string | null }) {
  return `${input.userId || "anonymous"}:${input.ip || "unknown"}`;
}

export function exportCacheKey(namespace: string, filters: unknown, userId?: string | null) {
  return `${namespace}:${userId || "anonymous"}:${stableJson(filters)}`;
}

export function isGeneratedExportPath(requestPath: string, method = "GET") {
  const normalized = requestPath.split("?", 1)[0].toLowerCase();
  const normalizedMethod = method.toUpperCase();
  if (/\/fleet-reports\/(?:base\/)?pdf$/.test(normalized)) return true;
  if (normalizedMethod === "POST" && /\/imports\/highlight-divergences$/.test(normalized)) return true;
  if (/\/imports\/batches\/[^/]+\/highlighted-file$/.test(normalized)) return true;
  if (/\/post-harvest-integrations\/export-summary$/.test(normalized)) return true;
  return /(?:\/export(?:[/.]|$)|(?:report|relatorio)[^/]*\.(?:pdf|xlsx|csv)$|\.(?:pdf|xlsx|csv)$)/.test(normalized);
}

function stableJson(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(stableJson).join(",")}]`;
  if (value && typeof value === "object") {
    return `{${Object.entries(value as Record<string, unknown>)
      .sort(([left], [right]) => left.localeCompare(right))
      .map(([key, item]) => `${JSON.stringify(key)}:${stableJson(item)}`)
      .join(",")}}`;
  }
  return JSON.stringify(value) ?? "null";
}
