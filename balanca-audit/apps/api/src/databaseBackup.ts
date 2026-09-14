import { spawn } from "node:child_process";
import fs from "node:fs/promises";
import path from "node:path";
import { env } from "./env.js";
import { buildPgDumpProcessConfig } from "./postgresBackupProcess.js";
import { resolvePostgresTool } from "./postgresTools.js";

export async function backupCurrentDatabase(prefix: string) {
  await fs.mkdir(env.backupDir, { recursive: true });
  const stamp = new Date().toISOString().replace(/[:.]/g, "-");

  const backupPath = path.join(env.backupDir, `${prefix}-${stamp}.dump`);
  try {
    await runPgDump(backupPath);
  } catch (error) {
    await fs.rm(backupPath, { force: true }).catch(() => undefined);
    throw error;
  }
  return backupPath;
}

async function runPgDump(backupPath: string) {
  const databaseUrl = process.env.DATABASE_URL?.trim() ?? process.env.POSTGRES_DATABASE_URL?.trim();

  if (!databaseUrl) {
    throw new Error("DATABASE_URL nao configurada para backup PostgreSQL.");
  }

  await new Promise<void>((resolve, reject) => {
    const pgDump = resolvePostgresTool("pg_dump");
    const processConfig = buildPgDumpProcessConfig(databaseUrl, backupPath);
    const child = spawn(pgDump, processConfig.args, {
      env: processConfig.env,
      windowsHide: true,
      stdio: ["ignore", "ignore", "pipe"]
    });
    let stderr = "";

    child.stderr.on("data", (chunk) => {
      stderr += String(chunk);
    });
    child.on("error", reject);
    child.on("close", (code) => {
      if (code === 0) {
        resolve();
        return;
      }

      reject(new Error(stderr.trim() || `pg_dump falhou com codigo ${code}.`));
    });
  });

  await validatePgDumpArchive(backupPath);
}

async function validatePgDumpArchive(backupPath: string) {
  const stat = await fs.stat(backupPath);

  if (stat.size <= 0) {
    throw new Error(`Backup PostgreSQL gerado vazio: ${backupPath}`);
  }

  await new Promise<void>((resolve, reject) => {
    const pgRestore = resolvePostgresTool("pg_restore");
    const child = spawn(pgRestore, ["--list", backupPath], {
      windowsHide: true,
      stdio: ["ignore", "pipe", "pipe"]
    });
    let stdout = "";
    let stderr = "";

    child.stdout.on("data", (chunk) => {
      stdout += String(chunk);
    });
    child.stderr.on("data", (chunk) => {
      stderr += String(chunk);
    });
    child.on("error", reject);
    child.on("close", (code) => {
      if (code === 0 && stdout.trim()) {
        resolve();
        return;
      }

      reject(new Error(stderr.trim() || `pg_restore --list falhou com codigo ${code}.`));
    });
  });
}
