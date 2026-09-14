import { createApp } from "./app.js";
import { db } from "./db.js";
import { env } from "./env.js";
import fs from "node:fs";
import type { Server } from "node:http";
import os from "node:os";
import path from "node:path";
import { startPostHarvestScheduler } from "./services/postHarvestIntegrationService.js";

let shuttingDown = false;
let server: Server | null = null;

process.on("uncaughtException", (error) => {
  console.error("Excecao nao tratada. O servidor sera encerrado com seguranca:", error);
  void shutdown(1);
});

process.on("unhandledRejection", (reason) => {
  console.error("Promessa rejeitada nao tratada. O servidor sera encerrado com seguranca:", reason);
  void shutdown(1);
});

/**
 * Remove arquivos temporários de IPC do banco (balanca-pg-*.json) com mais de 5 minutos.
 * Eles são criados pelo postgresSync.ts para cada query e devem ser apagados automaticamente.
 * Em caso de crash ou timeout, podem ficar acumulados no diretório temp do sistema.
 */
function cleanupStaleIpcFiles() {
  const tmpDir = process.env.OA_DEMO_TEMP_DIR;
  if (!tmpDir) return;
  const maxAgeMs = 5 * 60 * 1000; // 5 minutos
  const now = Date.now();
  let removed = 0;

  try {
    const files = fs.readdirSync(tmpDir);
    for (const file of files) {
      if (!file.startsWith("balanca-pg-")) continue;
      const filePath = path.join(tmpDir, file);
      try {
        const stat = fs.statSync(filePath);
        if (now - stat.mtimeMs > maxAgeMs) {
          fs.rmSync(filePath, { force: true });
          removed++;
        }
      } catch {
        // Arquivo pode ter sido removido entre readdir e stat — ignorar.
      }
    }
    if (removed > 0) {
      console.log(`[cleanup] ${removed} arquivo(s) temporário(s) de IPC removido(s).`);
    }
  } catch {
    // Limpeza não pode derrubar o servidor.
  }
}

// Executar limpeza imediatamente no startup e a cada hora
cleanupStaleIpcFiles();
setInterval(cleanupStaleIpcFiles, 60 * 60 * 1000).unref();

const app = createApp();

server = app.listen(env.port, env.host, () => {
  console.log(`API da balanca em http://${env.host}:${env.port}`);
  startPostHarvestScheduler();
});

process.on("SIGINT", () => void shutdown(0));
process.on("SIGTERM", () => void shutdown(0));

async function shutdown(exitCode: number) {
  if (shuttingDown) {
    return;
  }

  shuttingDown = true;
  const forceExit = setTimeout(() => process.exit(exitCode || 1), 10_000);
  forceExit.unref();

  if (server) {
    await new Promise<void>((resolve) => {
      server!.close(() => resolve());
    }).catch(() => undefined);
  }
  await Promise.resolve(db.close?.()).catch(() => undefined);
  process.exit(exitCode);
}
