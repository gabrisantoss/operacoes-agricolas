import "dotenv/config";
import fs from "node:fs/promises";
import path from "node:path";
import { randomUUID } from "node:crypto";
import { Client } from "pg";
import { assertDemoDatabaseTarget } from "../demoSafety.js";

type TestDatabase = {
  schemaName: string;
  cleanup(): Promise<void>;
};

export async function createPostgresTestDatabase(): Promise<TestDatabase> {
  if (process.env.NODE_ENV !== "test") {
    throw new Error("O banco PostgreSQL descartavel so pode ser criado com NODE_ENV=test.");
  }

  const baseDatabaseUrl = (process.env.BALANCA_TEST_DATABASE_URL ?? "").trim();

  if (!baseDatabaseUrl) {
    throw new Error("Configure BALANCA_TEST_DATABASE_URL com uma conexao PostgreSQL exclusiva para testes.");
  }

  const schemaName = `balanca_test_${process.pid}_${randomUUID().replace(/-/g, "")}`;
  assertDemoDatabaseTarget(baseDatabaseUrl);
  const schemaSql = await fs.readFile(
    path.resolve(import.meta.dirname, "..", "..", "sql", "postgres", "schema.sql"),
    "utf8"
  );
  const setupClient = new Client({ connectionString: baseDatabaseUrl });

  await setupClient.connect();
  try {
    await setupClient.query(`CREATE SCHEMA ${quoteIdentifier(schemaName)}`);
    await setupClient.query(`SET search_path TO ${quoteIdentifier(schemaName)}`);
    await setupClient.query(schemaSql);
  } catch (error) {
    await setupClient.query(`DROP SCHEMA IF EXISTS ${quoteIdentifier(schemaName)} CASCADE`).catch(() => undefined);
    throw error;
  } finally {
    await setupClient.end();
  }

  const originalDatabaseUrl = process.env.DATABASE_URL;
  const originalProvider = process.env.DATABASE_PROVIDER;
  process.env.DATABASE_PROVIDER = "postgres";
  process.env.DATABASE_URL = databaseUrlWithSearchPath(baseDatabaseUrl, schemaName);

  return {
    schemaName,
    async cleanup() {
      if (!schemaName.startsWith("balanca_test_")) {
        throw new Error("Nome de schema de teste invalido; limpeza cancelada.");
      }

      const cleanupClient = new Client({ connectionString: baseDatabaseUrl });
      await cleanupClient.connect();
      try {
        await cleanupClient.query(`DROP SCHEMA IF EXISTS ${quoteIdentifier(schemaName)} CASCADE`);
      } finally {
        await cleanupClient.end();
        restoreEnvironment("DATABASE_URL", originalDatabaseUrl);
        restoreEnvironment("DATABASE_PROVIDER", originalProvider);
      }
    }
  };
}

function databaseUrlWithSearchPath(databaseUrl: string, schemaName: string) {
  const url = new URL(databaseUrl);
  const currentOptions = url.searchParams.get("options")?.trim();
  const searchPathOption = `-c search_path=${schemaName}`;
  url.searchParams.set("options", currentOptions ? `${currentOptions} ${searchPathOption}` : searchPathOption);
  return url.toString();
}

function quoteIdentifier(value: string) {
  return `"${value.replace(/"/g, '""')}"`;
}

function restoreEnvironment(name: string, value: string | undefined) {
  if (value === undefined) {
    delete process.env[name];
    return;
  }

  process.env[name] = value;
}
