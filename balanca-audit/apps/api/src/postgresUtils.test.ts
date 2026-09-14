import assert from "node:assert/strict";
import test from "node:test";
import { buildPgDumpProcessConfig } from "./postgresBackupProcess.js";

test("pg_dump recebe conexao sem URL ou senha na linha de comando", () => {
  const passwordMarker = ["senha", "somente", "teste"].join("-");
  const databaseUrl = new URL("postgresql://db.invalid/database_name");
  databaseUrl.username = "application_user";
  databaseUrl.password = passwordMarker;
  databaseUrl.port = "6543";
  databaseUrl.searchParams.set("sslmode", "require");

  const config = buildPgDumpProcessConfig(databaseUrl.toString(), "backup.dump", {
    DATABASE_URL: databaseUrl.toString(),
    POSTGRES_ADMIN_URL: databaseUrl.toString(),
    POSTGRES_PASSWORD: passwordMarker,
    SYSTEMROOT: "C:\\Windows"
  });

  assert.deepEqual(config.args, [
    "--format=custom",
    "--schema=public",
    "--no-owner",
    "--no-privileges",
    "--file",
    "backup.dump",
    "--host",
    "db.invalid",
    "--port",
    "6543",
    "--username",
    "application_user",
    "--dbname",
    "database_name"
  ]);
  assert.equal(config.args.some((argument) => argument.includes(passwordMarker)), false);
  assert.equal(config.args.some((argument) => argument.includes("postgresql://")), false);
  assert.equal(config.env.PGPASSWORD, passwordMarker);
  assert.equal(config.env.PGSSLMODE, "require");
  assert.equal(config.env.DATABASE_URL, undefined);
  assert.equal(config.env.POSTGRES_ADMIN_URL, undefined);
  assert.equal(config.env.POSTGRES_PASSWORD, undefined);
  assert.equal(config.env.SYSTEMROOT, "C:\\Windows");
});

test("pg_dump aceita PGPASSWORD configurada no ambiente", () => {
  const passwordMarker = ["senha", "de", "ambiente"].join("-");
  const config = buildPgDumpProcessConfig(
    "postgresql://application_user@db.invalid/database_name",
    "backup.dump",
    { PGPASSWORD: passwordMarker }
  );

  assert.equal(config.env.PGPASSWORD, passwordMarker);
  assert.equal(config.args.some((argument) => argument.includes(passwordMarker)), false);
});

test("pg_dump preserva autenticacao externa quando a URL nao contem senha", () => {
  const config = buildPgDumpProcessConfig(
    "postgresql://application_user@db.invalid/database_name",
    "backup.dump",
    { PGPASSFILE: "C:\\secure\\pgpass.conf" }
  );

  assert.equal(config.env.PGPASSWORD, undefined);
  assert.equal(config.env.PGPASSFILE, "C:\\secure\\pgpass.conf");
});

test("pg_dump traduz ssl booleano sem degradar silenciosamente a conexao", () => {
  const config = buildPgDumpProcessConfig(
    "postgresql://application_user@db.invalid/database_name?ssl=true",
    "backup.dump",
    {}
  );

  assert.equal(config.env.PGSSLMODE, "require");
});

test("pg_dump rejeita parametros ambiguos ou nao suportados", () => {
  assert.throws(
    () =>
      buildPgDumpProcessConfig(
        "postgresql://application_user@db.invalid/database_name?sslmode=require&sslmode=disable",
        "backup.dump",
        {}
      ),
    /repete o parametro de conexao sslmode/
  );
  assert.throws(
    () =>
      buildPgDumpProcessConfig(
        "postgresql://application_user@db.invalid/database_name?parametro_inesperado=valor",
        "backup.dump",
        {}
      ),
    /parametro de conexao nao suportado parametro_inesperado/
  );
  assert.throws(
    () =>
      buildPgDumpProcessConfig(
        "postgresql://application_user@db.invalid/database_name#fragmento",
        "backup.dump",
        {}
      ),
    /nao pode conter fragmento/
  );
});
