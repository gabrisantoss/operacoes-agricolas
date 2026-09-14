import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { Worker } from "node:worker_threads";
import { getWorkerExecArgv } from "./workerExecArgv.js";
import { assertDemoDatabaseTarget } from "./demoSafety.js";

type QueryMode = "all" | "get" | "run" | "exec" | "runMany";

type WorkerPayload = {
  ok: true;
  result: unknown;
} | {
  ok: false;
  error: {
    message: string;
    stack?: string;
    code?: string;
    constraint?: string;
    table?: string;
    detail?: string;
  };
};

export type PostgresRunResult = {
  changes: number;
};

export class PostgresSyncDatabase {
  private readonly workers: Worker[];
  private readonly poolSize: number;
  private nextWorkerIndex = 0;
  private requestId = 0;
  private readonly queryTimeoutMs: number;
  private readonly statementTimeoutMs: number;
  private readonly lockTimeoutMs: number;
  private readonly idleTransactionTimeoutMs: number;
  private closing = false;

  // Worker pinned for the current transaction (single-connection guarantee)
  private pinnedWorkerIndex: number | null = null;

  constructor(private readonly databaseUrl: string) {
    assertDemoDatabaseTarget(databaseUrl);
    this.poolSize = readBoundedPositiveInteger("POSTGRES_WORKER_POOL_SIZE", 3, 1, 8);
    this.queryTimeoutMs = readBoundedPositiveInteger("POSTGRES_SYNC_QUERY_TIMEOUT_MS", 35_000, 5_000, 180_000);
    this.statementTimeoutMs = readBoundedPositiveInteger(
      "POSTGRES_STATEMENT_TIMEOUT_MS",
      Math.max(5_000, this.queryTimeoutMs - 5_000),
      1_000,
      this.queryTimeoutMs
    );
    this.lockTimeoutMs = readBoundedPositiveInteger("POSTGRES_LOCK_TIMEOUT_MS", 5_000, 500, this.statementTimeoutMs);
    this.idleTransactionTimeoutMs = readBoundedPositiveInteger(
      "POSTGRES_IDLE_TRANSACTION_TIMEOUT_MS",
      30_000,
      5_000,
      300_000
    );
    this.workers = Array.from({ length: this.poolSize }, (_unused, index) => this.createWorker(index));
  }

  prepare(sql: string) {
    return {
      all: (...params: unknown[]) => this.query("all", sql, params) as unknown[],
      get: (...params: unknown[]) => this.query("get", sql, params),
      run: (...params: unknown[]) => this.query("run", sql, params) as PostgresRunResult,
      runMany: (paramsList: any[]) => this.query("runMany", sql, paramsList) as PostgresRunResult
    };
  }

  exec(sql: string) {
    this.query("exec", sql, []);
  }

  transaction<TArgs extends unknown[], TResult>(fn: (...args: TArgs) => TResult) {
    return (...args: TArgs) => {
      if (this.pinnedWorkerIndex !== null) {
        throw new Error("Transacoes PostgreSQL aninhadas nao sao suportadas.");
      }

      // Pin a single worker for the entire transaction — a DB transaction
      // must run on the same connection from BEGIN to COMMIT/ROLLBACK.
      const workerIndex = this.nextWorkerIndex;
      this.pinnedWorkerIndex = workerIndex;
      this.nextWorkerIndex = (this.nextWorkerIndex + 1) % this.poolSize;

      this.execOnWorker("BEGIN", workerIndex);
      try {
        const result = fn(...args);
        this.execOnWorker("COMMIT", workerIndex);
        return result;
      } catch (error) {
        try {
          this.execOnWorker("ROLLBACK", workerIndex);
        } catch {
          // Preserve the original transaction error.
        }
        throw error;
      } finally {
        this.pinnedWorkerIndex = null;
      }
    };
  }

  async close() {
    this.closing = true;
    await Promise.all(this.workers.map((worker) => worker.terminate()));
  }

  private createWorker(workerIndex: number) {
    const worker = new Worker(resolveWorkerUrl(), {
      execArgv: getWorkerExecArgv(),
      workerData: {
        databaseUrl: this.databaseUrl,
        statementTimeoutMs: this.statementTimeoutMs,
        lockTimeoutMs: this.lockTimeoutMs,
        idleTransactionTimeoutMs: this.idleTransactionTimeoutMs
      }
    });

    this.attachWorkerLifecycle(worker, workerIndex);
    return worker;
  }

  private attachWorkerLifecycle(worker: Worker, workerIndex: number) {
    worker.on("error", (error) => {
      console.error(`Worker PostgreSQL ${workerIndex} falhou.`, error);
      this.replaceWorker(workerIndex, worker);
    });
    worker.on("exit", (code) => {
      if (code !== 0 && !this.closing) {
        console.error(`Worker PostgreSQL ${workerIndex} encerrou com codigo ${code}.`);
      }
      this.replaceWorker(workerIndex, worker);
    });
  }

  private replaceWorker(workerIndex: number, expectedWorker: Worker) {
    if (this.closing || this.workers[workerIndex] !== expectedWorker) {
      return;
    }

    this.workers[workerIndex] = this.createWorker(workerIndex);
    void expectedWorker.terminate().catch(() => undefined);
  }

  private execOnWorker(sql: string, workerIndex: number) {
    this.queryOnWorker("exec", sql, [], workerIndex);
  }

  private query(mode: QueryMode, sql: string, params: any) {
    // If inside a transaction, always use the pinned worker
    const workerIndex = this.pinnedWorkerIndex !== null
      ? this.pinnedWorkerIndex
      : this.pickWorker();

    return this.queryOnWorker(mode, sql, params, workerIndex);
  }

  private pickWorker(): number {
    const index = this.nextWorkerIndex;
    this.nextWorkerIndex = (this.nextWorkerIndex + 1) % this.poolSize;
    return index;
  }

  private queryOnWorker(mode: QueryMode, sql: string, params: any, workerIndex: number) {
    let finalSql = "";
    let finalParams: any[] = [];

    if (mode === "runMany") {
      const list = params as any[];
      if (list.length === 0) return { changes: 0 };

      const toArr = (p: any) => Array.isArray(p) ? p : [p];
      const firstTranslated = translateStatement(sql, toArr(list[0]));
      finalSql = firstTranslated.sql;
      finalParams = list.map((p) => translateStatement(sql, toArr(p)).params);
    } else {
      const translated = translateStatement(sql, params as unknown[]);
      finalSql = translated.sql;
      finalParams = translated.params;
    }

    const signal = new SharedArrayBuffer(4);
    const state = new Int32Array(signal);
    const resultPath = path.join(os.tmpdir(), `balanca-pg-${process.pid}-${Date.now()}-${++this.requestId}.json`);

    const worker = this.workers[workerIndex];

    try {
      worker.postMessage({
        id: this.requestId,
        sql: finalSql,
        params: finalParams,
        mode,
        manageBatchTransaction: mode === "runMany" && this.pinnedWorkerIndex === null,
        resultPath,
        signal
      });
    } catch (error) {
      this.replaceWorker(workerIndex, worker);
      throw new Error("Worker PostgreSQL indisponivel; a conexao foi reiniciada.", { cause: error });
    }

    const waitResult = Atomics.wait(state, 0, 0, this.queryTimeoutMs);

    if (waitResult === "timed-out") {
      fs.rmSync(resultPath, { force: true });
      this.replaceWorker(workerIndex, worker);
      throw new Error(`Consulta PostgreSQL excedeu ${this.queryTimeoutMs}ms.`);
    }

    let payload: WorkerPayload;
    try {
      payload = readWorkerPayload(resultPath);
    } catch (error) {
      this.replaceWorker(workerIndex, worker);
      throw new Error("Worker PostgreSQL encerrou sem retornar o resultado da consulta.", { cause: error });
    }

    if (!payload.ok) {
      const error = new Error(payload.error.message) as Error & {
        code?: string;
        constraint?: string;
        table?: string;
        detail?: string;
      };
      error.stack = payload.error.stack ?? error.stack;
      error.code = payload.error.code;
      error.constraint = payload.error.constraint;
      error.table = payload.error.table;
      error.detail = payload.error.detail;
      throw error;
    }

    return payload.result;
  }
}


function readWorkerPayload(resultPath: string): WorkerPayload {
  try {
    return JSON.parse(fs.readFileSync(resultPath, "utf8")) as WorkerPayload;
  } finally {
    fs.rmSync(resultPath, { force: true });
  }
}

function translateStatement(sql: string, params: unknown[]) {
  const normalizedSql = normalizeSqlDialect(sql);

  if (params.length === 1 && isPlainObject(params[0]) && /@[A-Za-z_][A-Za-z0-9_]*/.test(normalizedSql)) {
    return translateNamedStatement(normalizedSql, params[0] as Record<string, unknown>);
  }

  return {
    sql: translatePositionalPlaceholders(normalizedSql),
    params: params.map((value) => normalizeParamValue(null, value))
  };
}

function normalizeSqlDialect(sql: string) {
  return sql.replace(/\browid\b/gi, "id");
}

function translateNamedStatement(sql: string, params: Record<string, unknown>) {
  const positions = new Map<string, number>();
  const values: unknown[] = [];
  const translatedSql = sql.replace(/@([A-Za-z_][A-Za-z0-9_]*)/g, (_match, name: string) => {
    const existing = positions.get(name);

    if (existing) {
      return `$${existing}`;
    }

    const position = values.length + 1;
    positions.set(name, position);
    values.push(normalizeParamValue(name, params[name]));
    return `$${position}`;
  });

  return {
    sql: translatedSql,
    params: values
  };
}

function translatePositionalPlaceholders(sql: string) {
  let index = 0;
  let inSingleQuote = false;
  let inDoubleQuote = false;
  let translated = "";

  for (let position = 0; position < sql.length; position += 1) {
    const char = sql[position];
    const next = sql[position + 1];

    if (char === "'" && !inDoubleQuote) {
      translated += char;
      if (inSingleQuote && next === "'") {
        translated += next;
        position += 1;
      } else {
        inSingleQuote = !inSingleQuote;
      }
      continue;
    }

    if (char === '"' && !inSingleQuote) {
      inDoubleQuote = !inDoubleQuote;
      translated += char;
      continue;
    }

    if (char === "?" && !inSingleQuote && !inDoubleQuote) {
      index += 1;
      translated += `$${index}`;
      continue;
    }

    translated += char;
  }

  return translated;
}

function normalizeParamValue(name: string | null, value: unknown) {
  if ((name === "active" || name === "activeInt") && value !== null && value !== undefined) {
    return Boolean(value);
  }

  return value;
}

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value) && !(value instanceof Date);
}

export function readBoundedPositiveInteger(name: string, fallback: number, minimum: number, maximum: number) {
  const value = Number(process.env[name]);

  if (!Number.isInteger(value) || value < minimum || value > maximum) {
    return fallback;
  }

  return value;
}

function resolveWorkerUrl() {
  const current = fileURLToPath(import.meta.url);
  const extension = path.extname(current);
  const workerPath = path.join(path.dirname(current), `postgresSyncWorker${extension}`);
  return pathToFileURL(workerPath);
}
