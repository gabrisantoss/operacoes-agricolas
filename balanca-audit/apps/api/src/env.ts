import { randomBytes } from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { localAccessIsConfiguredForDevelopment, resolveApiHost } from "./runtimeSecurity.js";

const workspaceRoot = path.resolve(process.cwd(), "../..");

function resolveFromCwd(value: string) {
  return path.resolve(process.cwd(), value);
}

const generatedSecretFile = resolveFromCwd("./data/.jwt-secret");
const apiHost = resolveApiHost(process.env.API_HOST);

function readNumberEnv(name: string, fallback: number) {
  const parsed = Number(process.env[name]);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback;
}

function readOrCreateLocalJwtSecret() {
  fs.mkdirSync(path.dirname(generatedSecretFile), { recursive: true });

  try {
    const current = fs.readFileSync(generatedSecretFile, "utf-8").trim();
    if (current.length >= 48) {
      return current;
    }
  } catch {
    // The file is created below on first secure startup.
  }

  const secret = randomBytes(48).toString("base64url");
  fs.writeFileSync(generatedSecretFile, `${secret}\n`, { encoding: "utf-8", flag: "w", mode: 0o600 });
  return secret;
}

function resolveJwtSecret() {
  const configured = process.env.JWT_SECRET?.trim();

  if (configured && configured !== "dev-secret-change-me" && configured !== "troque-este-segredo-antes-de-usar-na-operacao") {
    return configured;
  }

  return readOrCreateLocalJwtSecret();
}

export const env = {
  jwtSecret: resolveJwtSecret(),
  host: apiHost,
  port: Number(process.env.PORT ?? 8833),
  uploadDir: resolveFromCwd(process.env.UPLOAD_DIR ?? "./uploads"),
  analysisArchiveDir: resolveFromCwd(process.env.ANALYSIS_ARCHIVE_DIR ?? "./analysis-files"),
  fleetBaseFile: resolveFromCwd(process.env.FLEET_BASE_FILE ?? path.join(workspaceRoot, "Frotas_Relatorio_Automatico.xlsx")),
  backupDir: resolveFromCwd(process.env.BACKUP_DIR ?? "./backups"),
  launcherAuthDb: path.resolve(process.env.LAUNCHER_AUTH_DB ?? path.join(workspaceRoot, "..", "launcher_web", "launcher_auth.db")),
  portalSessionUrl: process.env.AGRICOLA_PORTAL_SESSION_URL ?? "http://127.0.0.1:8890",
  portalSessionCookie: process.env.AGRICOLA_SESSION_COOKIE ?? "oa_demo_session",
  allowedOrigins: (process.env.BALANCA_ALLOWED_ORIGINS ?? "")
    .split(",")
    .map((origin) => origin.trim())
    .filter(Boolean),
  postHarvestWebhookUrl: "",
  postHarvestWebhookToken: "",
  postHarvestWebhookTimeoutMs: readNumberEnv("POST_HARVEST_WEBHOOK_TIMEOUT_MS", 15000),
  portalAnalystEmails: (process.env.BALANCA_PORTAL_ANALYST_EMAILS ?? "analista@example.invalid")
    .split(",")
    .map((email) => email.trim().toLowerCase())
    .filter(Boolean),
  allowLocalAccess: localAccessIsConfiguredForDevelopment({
    requested: process.env.BALANCA_ALLOW_LOCAL_ACCESS === "1",
    nodeEnv: process.env.NODE_ENV,
    npmLifecycleEvent: process.env.npm_lifecycle_event
  })
};
