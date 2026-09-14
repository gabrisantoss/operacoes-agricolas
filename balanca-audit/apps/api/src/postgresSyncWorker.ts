import fs from "node:fs";
import { parentPort, workerData } from "node:worker_threads";
import { Client, types } from "pg";

type WorkerRequest = {
  id: number;
  sql: string;
  params: unknown[];
  mode: "all" | "get" | "run" | "exec" | "runMany";
  manageBatchTransaction: boolean;
  resultPath: string;
  signal: SharedArrayBuffer;
};

types.setTypeParser(20, (value) => Number(value));
types.setTypeParser(1700, (value) => Number(value));

const client = new Client({
  connectionString: workerData.databaseUrl,
  application_name: "balanca-audit-sync-worker",
  connectionTimeoutMillis: 10_000,
  query_timeout: Number(workerData.statementTimeoutMs) + 5_000
});

const connected = client.connect().then(async () => {
  await setSessionTimeout("statement_timeout", workerData.statementTimeoutMs);
  await setSessionTimeout("lock_timeout", workerData.lockTimeoutMs);
  await setSessionTimeout("idle_in_transaction_session_timeout", workerData.idleTransactionTimeoutMs);
});

async function setSessionTimeout(name: string, value: unknown) {
  const milliseconds = Number(value);
  if (!Number.isInteger(milliseconds) || milliseconds <= 0) {
    throw new Error(`Timeout PostgreSQL invalido para ${name}.`);
  }
  await client.query("SELECT set_config($1, $2, false)", [name, `${milliseconds}ms`]);
}

parentPort?.on("message", async (request: WorkerRequest) => {
  const signal = new Int32Array(request.signal);

  try {
    await connected;
    let payload: any = null;

    if (request.mode === "runMany") {
      if (request.manageBatchTransaction) {
        await client.query("BEGIN");
      }
      try {
        let totalChanges = 0;
        const paramsList = request.params as unknown[][];
        for (const params of paramsList) {
          const res = await client.query(request.sql, params);
          totalChanges += res.rowCount ?? 0;
        }
        if (request.manageBatchTransaction) {
          await client.query("COMMIT");
        }
        payload = { changes: totalChanges };
      } catch (err) {
        if (request.manageBatchTransaction) {
          await client.query("ROLLBACK");
        }
        throw err;
      }
    } else {
      const result = await client.query(request.sql, request.params as unknown[]);
      payload =
        request.mode === "all"
          ? result.rows
          : request.mode === "get"
            ? result.rows[0] ?? null
            : request.mode === "run"
              ? { changes: result.rowCount ?? 0 }
              : null;
    }

    fs.writeFileSync(request.resultPath, JSON.stringify({ ok: true, result: payload }), "utf8");
  } catch (error) {
    const pgError = error as Error & { code?: string; constraint?: string; table?: string; detail?: string };
    fs.writeFileSync(
      request.resultPath,
      JSON.stringify({
        ok: false,
        error: {
          message: error instanceof Error ? error.message : String(error),
          stack: error instanceof Error ? error.stack : undefined,
          code: pgError.code,
          constraint: pgError.constraint,
          table: pgError.table,
          detail: pgError.detail
        }
      }),
      "utf8"
    );
  } finally {
    Atomics.store(signal, 0, 1);
    Atomics.notify(signal, 0);
  }
});
