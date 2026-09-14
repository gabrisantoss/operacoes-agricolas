import "dotenv/config";
import { Client } from "pg";
import { verifyPostgresMigrations } from "./postgresMigrations.js";

const databaseUrl = process.env.DATABASE_URL?.trim();

if (!databaseUrl) {
  console.error("DATABASE_URL nao configurada para verificar as migracoes PostgreSQL.");
  process.exitCode = 1;
} else {
  const client = new Client({ connectionString: databaseUrl });
  let connected = false;
  let transactionOpen = false;

  try {
    await client.connect();
    connected = true;
    await client.query("BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY");
    transactionOpen = true;

    const result = await verifyPostgresMigrations(client);

    await client.query("COMMIT");
    transactionOpen = false;
    console.log(
      `Migracoes PostgreSQL conferidas: schema=${result.schemaName}, ` +
        `versao=${result.currentVersion}, tabelas=${result.tableCount}.`
    );
  } catch (error) {
    if (transactionOpen) {
      await client.query("ROLLBACK").catch(() => undefined);
    }
    console.error(error instanceof Error ? error.message : "Falha ao verificar migracoes PostgreSQL.");
    process.exitCode = 1;
  } finally {
    if (connected) {
      await client.end();
    }
  }
}
