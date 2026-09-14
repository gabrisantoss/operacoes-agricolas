import cors from "cors";
import express from "express";
import { randomUUID } from "node:crypto";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { ZodError } from "zod";
import { db, listAvailableYears } from "./db.js";
import { authRouter } from "./routes/auth.js";
import { dashboardRouter } from "./routes/dashboard.js";
import { farmsRouter } from "./routes/farms.js";
import { fleetReportsRouter } from "./routes/fleet-reports.js";
import { importsRouter } from "./routes/imports.js";
import { ordersRouter } from "./routes/orders.js";
import { postHarvestIntegrationsRouter } from "./routes/post-harvest-integrations.js";
import { apportionmentRouter } from "./routes/apportionment.js";
import { requireAuth, requireRoles } from "./middleware/requireAuth.js";
import { HttpError } from "./errors.js";
import { env } from "./env.js";
import { internalHealthResponse, publicHealthResponse, type HealthCheck } from "./services/healthResponse.js";
import { exportAdmissionGate, exportRequestIdentity, isGeneratedExportPath } from "./services/exportControl.js";
import {
  readOperationalQueueHealth,
  unavailableOperationalQueueHealth
} from "./services/operationalQueueHealth.js";
import { hasRequiredPostHarvestDeliveryConfig } from "./services/postHarvestConnection.js";

export function createApp() {
  const app = express();

  app.disable("x-powered-by");
  app.use(requestContext);
  app.use(exportAdmission);
  app.use(securityHeaders);
  app.use(globalRateLimit);
  app.use(rejectUntrustedOrigin);
  app.use(
    cors({
      origin(origin, callback) {
        if (!origin || isAllowedOrigin(origin)) {
          callback(null, true);
          return;
        }

        callback(null, false);
      },
      credentials: true
    })
  );
  app.use(express.json({ limit: "50mb" }));
  app.use(auditMutatingRequests);

  const adminOnly = requireRoles(["ADMIN"]);
  const fullAccessOnly = requireRoles(["ADMIN", "ANALYST"]);

  app.get("/health", async (_req, res) => {
    const health = await readHealth();
    res.status(health.ok ? 200 : 503).json(publicHealthResponse(health));
  });

  app.get("/health/details", requireAuth, adminOnly, async (_req, res) => {
    const health = await readHealth({ includeOperationalQueues: true });
    res.status(health.ok ? 200 : 503).json(health);
  });

  app.use("/auth", authRouter);
  app.use("/dashboard", requireAuth, dashboardRouter);
  app.use("/farms", requireAuth, farmsRouter);
  app.use("/fleet-reports", requireAuth, fullAccessOnly, fleetReportsRouter);
  app.use("/orders", requireAuth, ordersRouter);
  app.use("/post-harvest-integrations", requireAuth, postHarvestIntegrationsRouter);
  app.use("/imports", requireAuth, importsRouter);
  app.use("/apportionment", requireAuth, apportionmentRouter);

  app.get("/safras", requireAuth, (_req, res) => {
    const years = listAvailableYears();
    res.json({ years });
  });

  app.use((error: Error, _req: express.Request, res: express.Response, _next: express.NextFunction) => {
    if (error instanceof HttpError) {
      return res.status(error.statusCode).json({ message: error.message });
    }

    if (error instanceof ZodError) {
      return res.status(400).json({ message: "Dados invalidos." });
    }

    if (isJsonSyntaxError(error)) {
      return res.status(400).json({ message: "JSON invalido." });
    }

    if ((error as Error & { code?: string }).code === "LIMIT_FILE_SIZE") {
      return res.status(400).json({ message: "Arquivo muito grande." });
    }

    const postgresError = mapPostgresError(error);

    if (postgresError) {
      return res.status(postgresError.statusCode).json({ message: postgresError.message });
    }

    console.error(error);
    res.status(500).json({ message: "Erro interno no servidor." });
  });

  return app;
}

function exportAdmission(req: express.Request, res: express.Response, next: express.NextFunction) {
  if (!isGeneratedExportPath(req.originalUrl, req.method)) {
    return next();
  }

  try {
    const release = exportAdmissionGate.enter(exportRequestIdentity({ userId: req.user?.id, ip: req.ip }));
    res.once("finish", release);
    res.once("close", release);
    return next();
  } catch (error) {
    return next(error);
  }
}

async function readHealth(options: { includeOperationalQueues?: boolean } = {}) {
  const coreChecks: Record<string, HealthCheck> = {
    database: readDatabaseHealth(),
    disk: await readDiskHealth()
  };
  const deliveryConfigured = hasRequiredPostHarvestDeliveryConfig({
    url: env.postHarvestWebhookUrl,
    token: env.postHarvestWebhookToken
  });
  const advisoryChecks = options.includeOperationalQueues
    ? {
        persistentQueues: coreChecks.database.ok
          ? readOperationalQueueHealth(db, deliveryConfigured)
          : unavailableOperationalQueueHealth(deliveryConfigured)
      }
    : undefined;

  return internalHealthResponse({
    service: "balanca-api",
    timestamp: new Date().toISOString(),
    uptimeSeconds: Math.round(process.uptime()),
    coreChecks,
    advisoryChecks
  });
}

function readDatabaseHealth(): HealthCheck {
  try {
    const row = db.prepare("SELECT 1 AS ok").get() as { ok: number } | undefined;
    return {
      ok: row?.ok === 1,
      provider: "postgres",
      schemaVersion: readDatabaseSchemaVersion(),
      ...databaseHealthTarget()
    };
  } catch (error) {
    return {
      ok: false,
      message: error instanceof Error ? error.message : "Falha ao consultar o banco.",
      provider: "postgres",
      schemaVersion: readDatabaseSchemaVersion(),
      ...databaseHealthTarget()
    };
  }
}

function readDatabaseSchemaVersion() {
  try {
    const row = db.prepare("SELECT MAX(version) AS version FROM balanca_schema_migrations").get() as { version?: string } | undefined;
    return row?.version ?? null;
  } catch {
    return null;
  }
}

function databaseHealthTarget() {
  return {
    target: redactDatabaseUrl(process.env.DATABASE_URL?.trim() ?? process.env.POSTGRES_DATABASE_URL?.trim() ?? "")
  };
}

function redactDatabaseUrl(value: string) {
  if (!value || !value.includes("@")) {
    return value;
  }

  const [prefix, suffix] = value.split("@", 2);
  const schemeIndex = prefix.indexOf("://");
  if (schemeIndex === -1) {
    return value;
  }

  const scheme = prefix.slice(0, schemeIndex);
  const auth = prefix.slice(schemeIndex + 3);
  const user = auth.split(":", 1)[0];
  return `${scheme}://${user}:***@${suffix}`;
}

async function readDiskHealth(): Promise<HealthCheck> {
  const minFreeBytes = 500 * 1024 * 1024;

  try {
    const diskPath = env.uploadDir;
    const [diskStat] = await Promise.all([
      fs.statfs(diskPath)
    ]);
    const freeBytes = Number(diskStat.bavail) * Number(diskStat.bsize);

    return {
      ok: freeBytes >= minFreeBytes,
      freeBytes,
      minFreeBytes,
      message: freeBytes >= minFreeBytes ? undefined : "Espaco livre baixo no disco do banco."
    };
  } catch (error) {
    return {
      ok: false,
      message: error instanceof Error ? error.message : "Falha ao consultar disco do banco."
    };
  }
}

function requestContext(req: express.Request, res: express.Response, next: express.NextFunction) {
  const startedAt = Date.now();
  const requestIdHeader = req.headers["x-request-id"];
  const requestId = Array.isArray(requestIdHeader) ? requestIdHeader[0] : requestIdHeader || randomUUID();

  res.setHeader("X-Request-Id", requestId);
  res.on("finish", () => {
    const durationMs = Date.now() - startedAt;

    if (durationMs < 2000 && res.statusCode < 500) {
      return;
    }

    const logLine = {
      requestId,
      method: req.method,
      path: req.originalUrl,
      statusCode: res.statusCode,
      durationMs,
      ip: req.ip || req.socket.remoteAddress
    };
    const text = JSON.stringify(logLine);
    void appendOperationalLog(res.statusCode >= 500 ? "server-errors" : "slow-requests", logLine);

    if (res.statusCode >= 500) {
      console.error(text);
      return;
    }

    console.warn(text);
  });

  return next();
}

async function appendOperationalLog(fileName: string, payload: Record<string, unknown>) {
  const logDir = path.resolve(process.cwd(), process.env.BALANCA_LOG_DIR ?? "./logs");
  const logPath = path.join(logDir, `${fileName}.jsonl`);

  try {
    await fs.mkdir(logDir, { recursive: true });
    await fs.appendFile(logPath, `${JSON.stringify({ timestamp: new Date().toISOString(), ...payload })}\n`, "utf8");
  } catch {
    // Logging cannot block the operational system.
  }
}

function securityHeaders(_req: express.Request, res: express.Response, next: express.NextFunction) {
  res.setHeader("X-Content-Type-Options", "nosniff");
  res.setHeader("X-Frame-Options", "SAMEORIGIN");
  res.setHeader("Referrer-Policy", "strict-origin-when-cross-origin");
  res.setHeader("Permissions-Policy", "camera=(), microphone=()");
  res.setHeader("Cross-Origin-Resource-Policy", "same-site");
  next();
}

type RateBucket = {
  count: number;
  resetAt: number;
};

const rateBuckets = new Map<string, RateBucket>();
const rateLimitWindowMs = 60_000;
const defaultRateLimitPerMinute = 1200;

function globalRateLimit(req: express.Request, res: express.Response, next: express.NextFunction) {
  if (req.method === "OPTIONS" || req.path === "/health") {
    return next();
  }

  const limit = readPositiveInteger(process.env.BALANCA_RATE_LIMIT_PER_MINUTE, defaultRateLimitPerMinute);

  if (limit <= 0) {
    return next();
  }

  const now = Date.now();
  const key = clientRateKey(req);
  const current = rateBuckets.get(key);
  const bucket = current && current.resetAt > now ? current : { count: 0, resetAt: now + rateLimitWindowMs };

  bucket.count += 1;
  rateBuckets.set(key, bucket);

  if (rateBuckets.size > 2000) {
    cleanupRateBuckets(now);
  }

  if (bucket.count <= limit) {
    return next();
  }

  const retryAfterSeconds = Math.max(1, Math.ceil((bucket.resetAt - now) / 1000));
  res.setHeader("Retry-After", String(retryAfterSeconds));
  return res.status(429).json({ message: "Muitas requisicoes em pouco tempo. Aguarde alguns segundos e tente novamente." });
}

function readPositiveInteger(value: string | undefined, fallback: number) {
  const parsed = Number(value);
  return Number.isInteger(parsed) && parsed >= 0 ? parsed : fallback;
}

function cleanupRateBuckets(now = Date.now()) {
  for (const [key, bucket] of rateBuckets) {
    if (bucket.resetAt <= now) {
      rateBuckets.delete(key);
    }
  }
}

function clientRateKey(req: express.Request) {
  return req.ip || req.socket.remoteAddress || "unknown";
}

function rejectUntrustedOrigin(req: express.Request, res: express.Response, next: express.NextFunction) {
  if (["GET", "HEAD", "OPTIONS"].includes(req.method)) {
    return next();
  }

  const fetchSite = req.headers["sec-fetch-site"];
  if (fetchSite === "cross-site") {
    return res.status(403).json({ message: "Origem da requisicao nao autorizada." });
  }

  const origin = req.headers.origin;
  if (origin && !isAllowedOrigin(origin)) {
    return res.status(403).json({ message: "Origem da requisicao nao autorizada." });
  }

  return next();
}

function auditMutatingRequests(req: express.Request, res: express.Response, next: express.NextFunction) {
  const methods = new Set(["POST", "PUT", "PATCH", "DELETE"]);
  if (!methods.has(req.method)) {
    return next();
  }

  res.on("finish", () => {
    if (res.statusCode >= 400) {
      return;
    }
    const cookie = req.headers.cookie;
    if (!cookie) {
      return;
    }

    const user = (req as express.Request & { user?: { id?: string; name?: string; email?: string; role?: string } }).user;
    void sendPortalAudit(cookie, {
      module: "balanca",
      eventType: `api.${req.method.toLowerCase()}`,
      entityType: routeEntity(req.originalUrl),
      entityId: req.params?.id || "",
      summary: `${methodLabel(req.method)} ${routeEntityLabel(req.originalUrl)}`,
      details: {
        path: req.originalUrl,
        method: req.method,
        statusCode: res.statusCode,
        balancaUser: user
          ? { id: user.id, name: user.name, email: user.email, role: user.role }
          : null
      }
    });
  });

  return next();
}

const defaultAllowedPorts = new Set(["8833", "8873", "8890"]);

function isAllowedOrigin(origin: string) {
  if (env.allowedOrigins.includes(origin)) {
    return true;
  }

  try {
    const parsed = new URL(origin);
    const host = parsed.hostname.toLowerCase();
    const port = parsed.port || (parsed.protocol === "https:" ? "443" : "80");

    if (!["http:", "https:"].includes(parsed.protocol)) {
      return false;
    }

    return localOriginHosts().has(host) && defaultAllowedPorts.has(port);
  } catch {
    return false;
  }
}

function localOriginHosts() {
  const hosts = new Set(["localhost", "127.0.0.1", "::1", "localhost", os.hostname().toLowerCase()]);

  for (const addresses of Object.values(os.networkInterfaces())) {
    for (const item of addresses ?? []) {
      if (item.family === "IPv4") {
        hosts.add(item.address.toLowerCase());
      }
    }
  }

  return hosts;
}

async function sendPortalAudit(cookie: string, payload: Record<string, unknown>) {
  const auditUrl = process.env.AGRICOLA_AUDIT_URL || "http://127.0.0.1:8890/api/audit/event";
  try {
    await fetch(auditUrl, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Cookie: cookie
      },
      body: JSON.stringify(payload)
    });
  } catch {
    // Audit cannot block the operational system.
  }
}

function methodLabel(method: string) {
  return {
    POST: "Criou/registrou",
    PUT: "Atualizou",
    PATCH: "Atualizou",
    DELETE: "Excluiu"
  }[method] ?? method;
}

function routeEntity(url: string) {
  const first = url.split("?")[0]?.split("/").filter(Boolean)[0] || "registro";
  return first.replace(/-/g, "_");
}

function routeEntityLabel(url: string) {
  const labels: Record<string, string> = {
    auth: "acesso",
    documents: "documento",
    farms: "fazenda/talhao",
    "fleet-reports": "relatorio de frota",
    imports: "importacao",
    orders: "ordem de colheita"
  };
  const first = url.split("?")[0]?.split("/").filter(Boolean)[0] || "registro";
  return labels[first] || first.replace(/-/g, " ");
}

function isJsonSyntaxError(error: Error) {
  return error instanceof SyntaxError && "body" in error;
}


function mapPostgresError(error: Error) {
  const maybePostgres = error as Error & { code?: string; constraint?: string; table?: string; detail?: string };

  if (!maybePostgres.code?.startsWith("23")) {
    return null;
  }

  const target = [maybePostgres.constraint, maybePostgres.table, maybePostgres.detail, maybePostgres.message]
    .filter(Boolean)
    .join(" ");

  if (target.includes("farms_code")) {
    return { statusCode: 409, message: "Ja existe uma fazenda com esse codigo." };
  }

  if (target.includes("fields_farm_id_code")) {
    return { statusCode: 409, message: "Ja existe um talhao com esse codigo nessa fazenda." };
  }

  if (maybePostgres.code === "23503") {
    return { statusCode: 400, message: "Registro relacionado nao encontrado." };
  }

  return { statusCode: 409, message: "Registro duplicado ou invalido." };
}
