import "dotenv/config";
import { Client } from "pg";
import { assertDemoDatabaseTarget } from "./demoSafety.js";
import { runPostgresMigrations } from "./postgresMigrations.js";

const migrationDatabaseUrl = process.env.POSTGRES_MIGRATION_URL?.trim();

if (!migrationDatabaseUrl) {
  console.error("POSTGRES_MIGRATION_URL nao configurada para aplicar as migracoes PostgreSQL.");
  process.exitCode = 1;
} else {
  assertDemoDatabaseTarget(migrationDatabaseUrl);
  const client = new Client({ connectionString: migrationDatabaseUrl });
  let connected = false;

  try {
    await client.connect();
    connected = true;
    const result = await runPostgresMigrations(client);

    console.log(
      result.applied.length > 0
        ? `Migracoes PostgreSQL aplicadas: ${result.applied.join(", ")}.`
        : `Schema PostgreSQL ja esta na versao ${result.currentVersion ?? "ausente"}.`
    );
  } catch (error) {
    console.error(error instanceof Error ? error.message : "Falha ao aplicar migracoes PostgreSQL.");
    process.exitCode = 1;
  } finally {
    if (connected) {
      await client.end();
    }
  }
}
