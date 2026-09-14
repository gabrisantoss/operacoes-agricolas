import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import test from "node:test";
import { Client } from "pg";
import {
  POSTGRES_MIGRATION_TABLE,
  assertPostgresMigrationState,
  extractPostgresSchemaTables,
  loadPostgresMigrations,
  readBasePostgresSchema,
  runPostgresMigrations,
  verifyPostgresMigrations
} from "./postgresMigrations.js";

test("versioned migration covers columns required by the current repositories", async () => {
  const migrations = await loadPostgresMigrations();

  assert.deepEqual(migrations.map((migration) => migration.version), ["0001", "0002", "0003"]);
  assert.match(migrations[0].sql, /ALTER TABLE harvest_orders[\s\S]*ADD COLUMN IF NOT EXISTS origin text/i);
  assert.match(migrations[0].sql, /ALTER TABLE cane_entries[\s\S]*ADD COLUMN IF NOT EXISTS farm_code_raw text/i);
  assert.match(migrations[1].sql, /CREATE UNIQUE INDEX IF NOT EXISTS idx_import_batches_file_hash_unique/i);
  assert.match(migrations[1].sql, /row_number\(\) OVER/i);
  assert.match(migrations[2].sql, /CREATE TABLE IF NOT EXISTS background_jobs/i);
  assert.match(migrations[2].sql, /idx_background_jobs_active_dedupe/i);
  assert.match(migrations[2].sql, /ADD COLUMN IF NOT EXISTS lease_expires_at/i);
  assert.ok(migrations.every((migration) => /^[a-f0-9]{64}$/.test(migration.checksum)));
});

test("API migration namespace stays isolated from the external legacy runner", async () => {
  const schemaSql = await readBasePostgresSchema();

  assert.equal(POSTGRES_MIGRATION_TABLE, "balanca_schema_migrations");
  assert.match(schemaSql, /CREATE TABLE IF NOT EXISTS balanca_schema_migrations/i);
  assert.doesNotMatch(schemaSql, /CREATE TABLE IF NOT EXISTS schema_migrations/i);
});

test("read-only state validation rejects missing, pending, unknown and changed migrations", async () => {
  const schemaSql = await readBasePostgresSchema();
  const expectedTables = extractPostgresSchemaTables(schemaSql);
  const knownMigrations = await loadPostgresMigrations();
  const appliedMigrations = knownMigrations.map((migration) => ({
    version: migration.version,
    description: migration.description,
    checksum: migration.checksum
  }));
  const appliedMigration = appliedMigrations[0]!;
  const validState = {
    schemaName: "public",
    expectedTables,
    presentTables: [...expectedTables],
    knownMigrations,
    appliedMigrations
  };

  const result = assertPostgresMigrationState(validState);
  assert.equal(result.currentVersion, "0003");
  assert.equal(result.tableCount, expectedTables.length);

  assert.throws(
    () => assertPostgresMigrationState({ ...validState, presentTables: expectedTables.slice(1) }),
    /tabelas ausentes/i
  );
  assert.throws(
    () => assertPostgresMigrationState({ ...validState, appliedMigrations: [] }),
    /pendentes: 0001, 0002, 0003/i
  );
  assert.throws(
    () =>
      assertPostgresMigrationState({
        ...validState,
        appliedMigrations: [{ ...appliedMigration, version: "9999" }, appliedMigrations[1]!]
      }),
    /desconhecidas.*9999/i
  );
  assert.throws(
    () =>
      assertPostgresMigrationState({
        ...validState,
        appliedMigrations: [{ ...appliedMigration, checksum: "0".repeat(64) }, appliedMigrations[1]!]
      }),
    /checksum divergente.*0001/i
  );
});

const testDatabaseUrl = process.env.BALANCA_TEST_DATABASE_URL?.trim();

test(
  "upgrades the previous schema and keeps fresh installation idempotent",
  { skip: testDatabaseUrl ? false : "BALANCA_TEST_DATABASE_URL nao configurada" },
  async () => {
    const client = new Client({ connectionString: testDatabaseUrl });
    const suffix = randomUUID().replace(/-/g, "");
    const legacySchema = `balanca_migration_legacy_${suffix}`;
    const freshSchema = `balanca_migration_fresh_${suffix}`;

    await client.connect();
    try {
      const currentSchema = await readBasePostgresSchema();
      const previousSchema = makePreviousSchema(currentSchema);

      await client.query(`CREATE SCHEMA ${quoteIdentifier(legacySchema)}`);
      await client.query(`SET search_path TO ${quoteIdentifier(legacySchema)}`);
      await client.query(previousSchema);
      await insertLegacyRows(client);

      await assert.rejects(
        () => verifyPostgresMigrations(client),
        /tabelas ausentes: balanca_schema_migrations/i
      );

      const legacyResult = await runPostgresMigrations(client);
      assert.deepEqual(legacyResult.applied, ["0001", "0002", "0003"]);
      await assertCurrentColumnsAndVersion(client, { expectExternalLegacyTable: true });

      await client.query("BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY");
      try {
        const verification = await verifyPostgresMigrations(client);
        assert.equal(verification.currentVersion, "0003");
        assert.ok(verification.tableCount > 0);
        await client.query("COMMIT");
      } catch (error) {
        await client.query("ROLLBACK");
        throw error;
      }

      await client.query("BEGIN");
      try {
        await client.query("UPDATE balanca_schema_migrations SET checksum = $1 WHERE version = '0001'", ["f".repeat(64)]);
        await assert.rejects(() => verifyPostgresMigrations(client), /checksum divergente.*0001/i);
      } finally {
        await client.query("ROLLBACK");
      }

      const originResult = await client.query<{ origin: string }>(
        "SELECT origin FROM harvest_orders WHERE id = 'legacy-order'"
      );
      assert.equal(originResult.rows[0]?.origin, "MANUAL");

      const repeatedResult = await runPostgresMigrations(client);
      assert.deepEqual(repeatedResult.applied, []);
      await assertCurrentColumnsAndVersion(client, { expectExternalLegacyTable: true });

      const lockOwner = new Client({ connectionString: testDatabaseUrl });
      await lockOwner.connect();
      try {
        await lockOwner.query("BEGIN");
        await lockOwner.query("SELECT pg_advisory_xact_lock(hashtext($1))", ["balanca-audit-schema-migrations"]);
        await assert.rejects(
          () => runPostgresMigrations(client, { lockTimeoutMs: 100 }),
          (error: unknown) => {
            assert.ok(error instanceof Error);
            assert.match(error.message, /lock timeout/i);
            assert.doesNotMatch(error.message, /postgres(?:ql)?:\/\//i);
            return true;
          }
        );
      } finally {
        await lockOwner.query("ROLLBACK").catch(() => undefined);
        await lockOwner.end();
      }

      await client.query(`CREATE SCHEMA ${quoteIdentifier(freshSchema)}`);
      await client.query(`SET search_path TO ${quoteIdentifier(freshSchema)}`);
      const freshResult = await runPostgresMigrations(client);
      assert.deepEqual(freshResult.applied, ["0001", "0002", "0003"]);
      await assertCurrentColumnsAndVersion(client);
      const freshVerification = await verifyPostgresMigrations(client);
      assert.equal(freshVerification.currentVersion, "0003");
    } finally {
      await client.query("SET search_path TO public").catch(() => undefined);
      await client.query(`DROP SCHEMA IF EXISTS ${quoteIdentifier(legacySchema)} CASCADE`).catch(() => undefined);
      await client.query(`DROP SCHEMA IF EXISTS ${quoteIdentifier(freshSchema)} CASCADE`).catch(() => undefined);
      await client.end();
    }
  }
);

function makePreviousSchema(currentSchema: string) {
  let previousSchema = currentSchema.replace(
    /CREATE TABLE IF NOT EXISTS balanca_schema_migrations \([\s\S]*?\);\s*/i,
    ""
  );
  previousSchema = previousSchema.replace(
    /CREATE UNIQUE INDEX IF NOT EXISTS idx_import_batches_file_hash_unique[\s\S]*?;\s*/i,
    ""
  );
  previousSchema = previousSchema.replace(
    /CREATE TABLE IF NOT EXISTS background_jobs \([\s\S]*?\);\s*/i,
    ""
  );
  previousSchema = previousSchema.replace(
    /CREATE (?:UNIQUE )?INDEX IF NOT EXISTS idx_background_jobs_[\s\S]*?;\s*/gi,
    ""
  );
  previousSchema = previousSchema.replace(
    /CREATE INDEX IF NOT EXISTS idx_post_harvest_dispatch_claim[\s\S]*?;\s*/i,
    ""
  );
  previousSchema = previousSchema.replace(
    /CREATE TABLE IF NOT EXISTS farm_coordinate_sync_events \([\s\S]*?\);\s*/i,
    ""
  );
  previousSchema = previousSchema.replace(
    /CREATE INDEX IF NOT EXISTS idx_farm_coordinate_sync_[\s\S]*?;\s*/gi,
    ""
  );

  const removedColumns = [
    ["harvest_orders", "origin"],
    ["cane_entries", "farm_code_raw"],
    ["post_harvest_integration_events", "event_version"],
    ["post_harvest_integration_events", "max_attempts"],
    ["post_harvest_integration_events", "available_at"],
    ["post_harvest_integration_events", "lease_owner"],
    ["post_harvest_integration_events", "lease_expires_at"],
    ["post_harvest_integration_events", "dead_at"]
  ] as const;

  for (const [tableName, columnName] of removedColumns) {
    previousSchema = removeColumnFromTable(previousSchema, tableName, columnName);
  }

  // A base produtiva historica guardava estes timestamps como texto. O teste
  // precisa reproduzir esse contrato, nao apenas o schema base mais recente.
  const integrationBlock = readTableBlock(previousSchema, "post_harvest_integration_events");
  const legacyIntegrationBlock = integrationBlock
    .replace(/created_at timestamptz NOT NULL DEFAULT now\(\)/i, "created_at text NOT NULL DEFAULT CURRENT_TIMESTAMP")
    .replace(/updated_at timestamptz NOT NULL DEFAULT now\(\)/i, "updated_at text NOT NULL DEFAULT CURRENT_TIMESTAMP");
  assert.notEqual(legacyIntegrationBlock, integrationBlock);
  previousSchema = previousSchema.replace(integrationBlock, legacyIntegrationBlock);

  assert.notEqual(previousSchema, currentSchema, "O fixture legado precisa diferir do schema atual.");
  assert.doesNotMatch(previousSchema, /CREATE TABLE IF NOT EXISTS balanca_schema_migrations/i);

  for (const [tableName, columnName] of removedColumns) {
    assert.equal(tableDeclaresColumn(previousSchema, tableName, columnName), false);
  }

  return previousSchema;
}

function removeColumnFromTable(schemaSql: string, tableName: string, columnName: string) {
  const block = readTableBlock(schemaSql, tableName);
  const columnPattern = new RegExp(`^\\s*${escapeRegExp(columnName)}\\s+[^\\r\\n]+(?:\\r?\\n)?`, "im");
  const updatedBlock = block.replace(columnPattern, "");

  assert.notEqual(updatedBlock, block, `A coluna ${tableName}.${columnName} precisa existir no schema atual.`);
  return schemaSql.replace(block, updatedBlock);
}

function tableDeclaresColumn(schemaSql: string, tableName: string, columnName: string) {
  const block = readTableBlock(schemaSql, tableName);
  return new RegExp(`^\\s*${escapeRegExp(columnName)}\\s+`, "im").test(block);
}

function readTableBlock(schemaSql: string, tableName: string) {
  const startMarker = `CREATE TABLE IF NOT EXISTS ${tableName} (`;
  const start = schemaSql.indexOf(startMarker);
  assert.notEqual(start, -1, `Tabela ${tableName} ausente do schema base.`);
  const remainder = schemaSql.slice(start);
  const endMatch = /\r?\n\);/.exec(remainder);
  assert.ok(endMatch, `Fim da tabela ${tableName} nao encontrado.`);
  return remainder.slice(0, endMatch.index + endMatch[0].length);
}

function escapeRegExp(value: string) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

async function insertLegacyRows(client: Client) {
  await client.query(`
    CREATE TABLE schema_migrations (
      version text PRIMARY KEY,
      description text NOT NULL,
      applied_at timestamptz NOT NULL DEFAULT now()
    )
  `);
  await client.query(
    "INSERT INTO schema_migrations (version, description) VALUES ('001', 'backend foundation indexes')"
  );
  await client.query("INSERT INTO farms (id, code, name) VALUES ('legacy-farm', '100-0001', 'FAZENDA LEGADA')");
  await client.query(
    "INSERT INTO harvest_orders (id, number, farm_id) VALUES ('legacy-order', 'OS-LEGACY', 'legacy-farm')"
  );
  await client.query(
    "INSERT INTO import_batches (id, file_name, file_hash) VALUES ('legacy-batch', 'legacy.xlsx', ' ABC123 ')"
  );
  await client.query(
    "INSERT INTO import_batches (id, file_name, file_hash) VALUES ('legacy-batch-duplicate', 'legacy-copy.xlsx', 'abc123')"
  );
  await client.query(
    "INSERT INTO cane_entries (id, batch_id, farm_name_raw) VALUES ('legacy-entry', 'legacy-batch', 'FAZENDA LEGADA')"
  );
  await client.query(`
    INSERT INTO post_harvest_integration_events (
      id, event_id, event_type, order_number, farm_name, field_code, payload_json, created_at, updated_at
    ) VALUES (
      'legacy-event', 'legacy-event-id', 'FIELD_CLOSED', 'OS-LEGACY', 'FAZENDA LEGADA', '01', '{}',
      '2026-08-30 10:00:00', '2026-08-30 10:05:00'
    )
  `);
}

async function assertCurrentColumnsAndVersion(
  client: Client,
  options: { expectExternalLegacyTable?: boolean } = {}
) {
  const columns = await client.query<{ table_name: string; column_name: string }>(`
    SELECT table_name, column_name
    FROM information_schema.columns
    WHERE table_schema = current_schema()
      AND (table_name, column_name) IN (
        ('harvest_orders', 'origin'),
        ('cane_entries', 'farm_code_raw')
      )
    ORDER BY table_name, column_name
  `);
  assert.deepEqual(columns.rows, [
    { table_name: "cane_entries", column_name: "farm_code_raw" },
    { table_name: "harvest_orders", column_name: "origin" },
  ]);



  const versions = await client.query<{ version: string }>(
    "SELECT version FROM balanca_schema_migrations ORDER BY version"
  );
  assert.deepEqual(versions.rows, [
    { version: "0001" },
    { version: "0002" },
    { version: "0003" }
  ]);



  if (options.expectExternalLegacyTable) {
    const legacyEvent = await client.query<{ count: string }>(`
      SELECT COUNT(*)::text AS count
      FROM post_harvest_integration_events
      WHERE id = 'legacy-event' AND available_at IS NOT NULL
    `);
    assert.equal(legacyEvent.rows[0]?.count, "1");

    const externalVersions = await client.query<{ version: string; has_checksum: boolean }>(`
      SELECT version,
             EXISTS (
               SELECT 1
               FROM information_schema.columns
               WHERE table_schema = current_schema()
                 AND table_name = 'schema_migrations'
                 AND column_name = 'checksum'
             ) AS has_checksum
      FROM schema_migrations
      ORDER BY version
    `);
    assert.deepEqual(externalVersions.rows, [{ version: "001", has_checksum: false }]);
  } else {
    const externalTable = await client.query<{ name: string | null }>(
      "SELECT to_regclass(current_schema() || '.schema_migrations')::text AS name"
    );
    assert.equal(externalTable.rows[0]?.name, null);
  }

  const hashes = await client.query<{ id: string; file_hash: string | null }>(`
    SELECT id, file_hash
    FROM import_batches
    WHERE id IN ('legacy-batch', 'legacy-batch-duplicate')
    ORDER BY id ASC
  `);
  if (hashes.rows.length > 0) {
    assert.deepEqual(hashes.rows, [
      { id: "legacy-batch", file_hash: "abc123" },
      { id: "legacy-batch-duplicate", file_hash: null }
    ]);
  }

  const fileHashIndex = await client.query<{ exists: boolean }>(`
    SELECT to_regclass(format('%I.%I', current_schema(), 'idx_import_batches_file_hash_unique')) IS NOT NULL AS exists
  `);
  assert.equal(fileHashIndex.rows[0]?.exists, true);
}

function quoteIdentifier(value: string) {
  return `"${value.replace(/"/g, '""')}"`;
}
