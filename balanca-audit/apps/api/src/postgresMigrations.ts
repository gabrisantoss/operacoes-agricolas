import { createHash } from "node:crypto";
import fs from "node:fs/promises";
import path from "node:path";
import type { Client } from "pg";

const migrationFilePattern = /^(\d{4})_([a-z0-9_]+)\.sql$/;
const migrationLockName = "balanca-audit-schema-migrations";
const defaultMigrationLockTimeoutMs = 15_000;
export const POSTGRES_MIGRATION_TABLE = "balanca_schema_migrations";
const migrationTableSql = `
  CREATE TABLE IF NOT EXISTS ${POSTGRES_MIGRATION_TABLE} (
    version text PRIMARY KEY,
    description text NOT NULL,
    checksum text NOT NULL,
    applied_at timestamptz NOT NULL DEFAULT now()
  )
`;

type MigrationClient = Pick<Client, "query">;

export type PostgresMigration = {
  version: string;
  description: string;
  checksum: string;
  sql: string;
  fileName: string;
};

export type PostgresMigrationResult = {
  applied: string[];
  currentVersion: string | null;
};

export type PostgresMigrationVerificationResult = {
  schemaName: string;
  currentVersion: string;
  knownVersions: string[];
  tableCount: number;
};

type AppliedPostgresMigration = {
  version: string;
  description: string;
  checksum: string;
};

type MigrationPaths = {
  schemaPath?: string;
  migrationsDir?: string;
  lockTimeoutMs?: number;
};

export async function runPostgresMigrations(
  client: MigrationClient,
  paths: MigrationPaths = {}
): Promise<PostgresMigrationResult> {
  const [schemaSql, migrations] = await Promise.all([
    readBasePostgresSchema(paths.schemaPath),
    loadPostgresMigrations(paths.migrationsDir)
  ]);
  const appliedVersions: string[] = [];

  await client.query("BEGIN");
  try {
    const lockTimeoutMs = readMigrationLockTimeout(paths.lockTimeoutMs);
    await client.query(`SET LOCAL lock_timeout = '${lockTimeoutMs}ms'`);
    await client.query("SELECT pg_advisory_xact_lock(hashtext($1))", [migrationLockName]);
    const coreTables = await client.query<{ exists: boolean }>(`
      SELECT
        to_regclass(format('%I.%I', current_schema(), 'users')) IS NOT NULL
        OR to_regclass(format('%I.%I', current_schema(), 'farms')) IS NOT NULL AS exists
    `);

    if (coreTables.rows[0]?.exists) {
      await client.query(migrationTableSql);
    } else {
      await client.query(schemaSql);
    }

    const appliedResult = await client.query<{
      version: string;
      description: string;
      checksum: string;
    }>(`SELECT version, description, checksum FROM ${POSTGRES_MIGRATION_TABLE} ORDER BY version`);
    const knownMigrations = new Map(migrations.map((migration) => [migration.version, migration]));
    const recordedMigrations = new Map(appliedResult.rows.map((migration) => [migration.version, migration]));

    for (const recorded of appliedResult.rows) {
      const known = knownMigrations.get(recorded.version);

      if (!known) {
        throw new Error(
          `O banco registra a migracao ${recorded.version}, mas ela nao existe neste codigo. ` +
            "Use uma versao da aplicacao compativel com o banco."
        );
      }

      if (known.checksum !== recorded.checksum) {
        throw new Error(
          `A migracao ${recorded.version} foi alterada depois de aplicada ` +
            `(checksum esperado ${recorded.checksum}, encontrado ${known.checksum}).`
        );
      }
    }

    for (const migration of migrations) {
      if (recordedMigrations.has(migration.version)) {
        continue;
      }

      await client.query(migration.sql);
      await client.query(
        `
        INSERT INTO ${POSTGRES_MIGRATION_TABLE} (version, description, checksum)
        VALUES ($1, $2, $3)
        `,
        [migration.version, migration.description, migration.checksum]
      );
      appliedVersions.push(migration.version);
    }

    await client.query("COMMIT");
  } catch (error) {
    await client.query("ROLLBACK").catch(() => undefined);
    throw error;
  }

  return {
    applied: appliedVersions,
    currentVersion: migrations.at(-1)?.version ?? null
  };
}

export async function verifyPostgresMigrations(
  client: MigrationClient,
  paths: MigrationPaths = {}
): Promise<PostgresMigrationVerificationResult> {
  const [schemaSql, migrations] = await Promise.all([
    readBasePostgresSchema(paths.schemaPath),
    loadPostgresMigrations(paths.migrationsDir)
  ]);
  const schemaResult = await client.query<{ schema_name: string | null }>(
    "SELECT current_schema() AS schema_name"
  );
  const schemaName = schemaResult.rows[0]?.schema_name;

  if (!schemaName) {
    throw new Error("A conexao PostgreSQL nao possui um schema atual para validar.");
  }

  const expectedTables = extractPostgresSchemaTables(schemaSql);
  const tableResult = await client.query<{ table_name: string }>(
    `
    SELECT table_name
    FROM information_schema.tables
    WHERE table_schema = $1
      AND table_type = 'BASE TABLE'
      AND table_name = ANY($2::text[])
    ORDER BY table_name
    `,
    [schemaName, expectedTables]
  );
  const presentTables = tableResult.rows.map((row) => row.table_name);
  const missingTables = expectedTables.filter((table) => !presentTables.includes(table));

  if (missingTables.length > 0) {
    throw new Error(`Schema PostgreSQL incompleto; tabelas ausentes: ${missingTables.join(", ")}.`);
  }

  const migrationTable = `${quotePostgresIdentifier(schemaName)}.${quotePostgresIdentifier(POSTGRES_MIGRATION_TABLE)}`;
  const appliedResult = await client.query<AppliedPostgresMigration>(
    `SELECT version, description, checksum FROM ${migrationTable} ORDER BY version`
  );

  return assertPostgresMigrationState({
    schemaName,
    expectedTables,
    presentTables,
    knownMigrations: migrations,
    appliedMigrations: appliedResult.rows
  });
}

export function assertPostgresMigrationState(input: {
  schemaName: string;
  expectedTables: string[];
  presentTables: string[];
  knownMigrations: PostgresMigration[];
  appliedMigrations: AppliedPostgresMigration[];
}): PostgresMigrationVerificationResult {
  const missingTables = input.expectedTables.filter((table) => !input.presentTables.includes(table));

  if (missingTables.length > 0) {
    throw new Error(`Schema PostgreSQL incompleto; tabelas ausentes: ${missingTables.join(", ")}.`);
  }

  const knownByVersion = new Map(input.knownMigrations.map((migration) => [migration.version, migration]));
  const appliedByVersion = new Map(input.appliedMigrations.map((migration) => [migration.version, migration]));

  if (appliedByVersion.size !== input.appliedMigrations.length) {
    throw new Error(`A tabela ${POSTGRES_MIGRATION_TABLE} contem versoes duplicadas.`);
  }

  const unknownVersions = input.appliedMigrations
    .map((migration) => migration.version)
    .filter((version) => !knownByVersion.has(version));

  if (unknownVersions.length > 0) {
    throw new Error(
      `O banco contem migracoes desconhecidas por esta release: ${unknownVersions.join(", ")}.`
    );
  }

  for (const applied of input.appliedMigrations) {
    const known = knownByVersion.get(applied.version)!;

    if (known.checksum !== applied.checksum) {
      throw new Error(`Checksum divergente para a migracao ${applied.version}.`);
    }
  }

  const pendingVersions = input.knownMigrations
    .map((migration) => migration.version)
    .filter((version) => !appliedByVersion.has(version));

  if (pendingVersions.length > 0) {
    throw new Error(`Migracoes PostgreSQL pendentes: ${pendingVersions.join(", ")}.`);
  }

  const expectedVersion = input.knownMigrations.at(-1)?.version;
  const currentVersion = input.appliedMigrations.at(-1)?.version;

  if (!expectedVersion || !currentVersion || currentVersion !== expectedVersion) {
    throw new Error(
      `Versao PostgreSQL divergente; banco=${currentVersion ?? "ausente"}, release=${expectedVersion ?? "ausente"}.`
    );
  }

  return {
    schemaName: input.schemaName,
    currentVersion,
    knownVersions: input.knownMigrations.map((migration) => migration.version),
    tableCount: input.presentTables.length
  };
}

export async function readBasePostgresSchema(schemaPath = defaultSchemaPath()) {
  return fs.readFile(schemaPath, "utf8");
}

export async function loadPostgresMigrations(migrationsDir = defaultMigrationsDir()) {
  const entries = await fs.readdir(migrationsDir, { withFileTypes: true });
  const migrations = await Promise.all(
    entries
      .filter((entry) => entry.isFile() && entry.name.endsWith(".sql"))
      .map(async (entry): Promise<PostgresMigration> => {
        const match = migrationFilePattern.exec(entry.name);

        if (!match) {
          throw new Error(
            `Nome de migracao invalido: ${entry.name}. Use o formato 0001_descricao_em_snake_case.sql.`
          );
        }

        const sql = await fs.readFile(path.join(migrationsDir, entry.name), "utf8");
        const normalizedSql = normalizeLineEndings(sql);

        if (!normalizedSql.trim()) {
          throw new Error(`A migracao ${entry.name} esta vazia.`);
        }

        return {
          version: match[1],
          description: match[2].replace(/_/g, " "),
          checksum: createHash("sha256").update(normalizedSql).digest("hex"),
          sql,
          fileName: entry.name
        };
      })
  );

  migrations.sort((left, right) => left.version.localeCompare(right.version));

  if (migrations.length === 0) {
    throw new Error(`Nenhuma migracao PostgreSQL encontrada em ${migrationsDir}.`);
  }

  for (let index = 1; index < migrations.length; index += 1) {
    if (migrations[index - 1].version === migrations[index].version) {
      throw new Error(`Mais de uma migracao usa a versao ${migrations[index].version}.`);
    }
  }

  return migrations;
}

export function extractPostgresSchemaTables(schemaSql: string) {
  const tables = Array.from(
    schemaSql.matchAll(/\bCREATE\s+TABLE\s+IF\s+NOT\s+EXISTS\s+([a-z_][a-z0-9_]*)\s*\(/gi),
    (match) => match[1].toLowerCase()
  );

  if (tables.length === 0) {
    throw new Error("O schema PostgreSQL base nao declara nenhuma tabela reconhecivel.");
  }

  if (new Set(tables).size !== tables.length) {
    throw new Error("O schema PostgreSQL base declara tabelas duplicadas.");
  }

  return tables;
}

function defaultSchemaPath() {
  return path.resolve(import.meta.dirname, "..", "sql", "postgres", "schema.sql");
}

function defaultMigrationsDir() {
  return path.resolve(import.meta.dirname, "..", "sql", "postgres", "migrations");
}

function normalizeLineEndings(value: string) {
  return value.replace(/\r\n/g, "\n").replace(/\r/g, "\n");
}

function quotePostgresIdentifier(value: string) {
  return `"${value.replace(/"/g, '""')}"`;
}

function readMigrationLockTimeout(value: number | undefined) {
  if (value === undefined) {
    return defaultMigrationLockTimeoutMs;
  }

  if (!Number.isSafeInteger(value) || value < 1 || value > 300_000) {
    throw new Error("lockTimeoutMs deve ser um inteiro entre 1 e 300000.");
  }

  return value;
}
