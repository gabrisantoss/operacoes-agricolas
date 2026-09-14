type PgDumpProcessConfig = {
  args: string[];
  env: NodeJS.ProcessEnv;
};

const postgresUrlParameterEnvironment = {
  application_name: "PGAPPNAME",
  channel_binding: "PGCHANNELBINDING",
  client_encoding: "PGCLIENTENCODING",
  connect_timeout: "PGCONNECT_TIMEOUT",
  gssencmode: "PGGSSENCMODE",
  krbsrvname: "PGKRBSRVNAME",
  options: "PGOPTIONS",
  passfile: "PGPASSFILE",
  requirepeer: "PGREQUIREPEER",
  service: "PGSERVICE",
  servicefile: "PGSERVICEFILE",
  sslcert: "PGSSLCERT",
  sslcrl: "PGSSLCRL",
  sslcrldir: "PGSSLCRLDIR",
  sslkey: "PGSSLKEY",
  sslmode: "PGSSLMODE",
  sslpassword: "PGSSLPASSWORD",
  sslrootcert: "PGSSLROOTCERT",
  target_session_attrs: "PGTARGETSESSIONATTRS"
} as const;

const inheritedPostgresSecrets = [
  "DATABASE_URL",
  "POSTGRES_ADMIN_URL",
  "POSTGRES_DATABASE_URL",
  "POSTGRES_MIGRATION_URL",
  "POSTGRES_PASSWORD"
] as const;

export function buildPgDumpProcessConfig(
  databaseUrl: string,
  backupPath: string,
  baseEnv: NodeJS.ProcessEnv = process.env
): PgDumpProcessConfig {
  let url: URL;

  try {
    url = new URL(databaseUrl);
  } catch {
    throw new Error("DATABASE_URL invalida para executar o backup PostgreSQL.");
  }

  if (url.protocol !== "postgres:" && url.protocol !== "postgresql:") {
    throw new Error("DATABASE_URL deve usar o protocolo postgres ou postgresql.");
  }

  if (url.hash) {
    throw new Error("DATABASE_URL nao pode conter fragmento para executar o backup PostgreSQL.");
  }

  const host = url.hostname.replace(/^\[|\]$/g, "");
  const port = url.port || "5432";
  const username = decodeUrlComponent(url.username, "usuario");
  const database = decodeUrlComponent(url.pathname.replace(/^\/+/, ""), "banco");
  const urlPassword = decodeUrlComponent(url.password, "senha");

  if (!host || !username || !database) {
    throw new Error("DATABASE_URL deve informar host, usuario e banco para executar o backup PostgreSQL.");
  }

  const env: NodeJS.ProcessEnv = { ...baseEnv };

  for (const key of inheritedPostgresSecrets) {
    delete env[key];
  }

  if (urlPassword) {
    env.PGPASSWORD = urlPassword;
  }

  for (const parameter of new Set(url.searchParams.keys())) {
    const values = url.searchParams.getAll(parameter);

    if (values.length !== 1) {
      throw new Error(`DATABASE_URL repete o parametro de conexao ${parameter}.`);
    }

    const value = values[0].trim();

    if (!value) {
      throw new Error(`DATABASE_URL contem o parametro de conexao ${parameter} vazio.`);
    }

    if (parameter === "ssl") {
      if (url.searchParams.has("sslmode")) {
        throw new Error("DATABASE_URL nao pode combinar ssl e sslmode.");
      }

      if (value === "true") {
        env.PGSSLMODE = "require";
      } else if (value === "false") {
        env.PGSSLMODE = "disable";
      } else {
        throw new Error("DATABASE_URL aceita apenas ssl=true ou ssl=false.");
      }

      continue;
    }

    const environmentKey = postgresUrlParameterEnvironment[
      parameter as keyof typeof postgresUrlParameterEnvironment
    ];

    if (!environmentKey) {
      throw new Error(`DATABASE_URL contem o parametro de conexao nao suportado ${parameter}.`);
    }

    env[environmentKey] = value;
  }

  return {
    args: [
      "--format=custom",
      "--schema=public",
      "--no-owner",
      "--no-privileges",
      "--file",
      backupPath,
      "--host",
      host,
      "--port",
      port,
      "--username",
      username,
      "--dbname",
      database
    ],
    env
  };
}

function decodeUrlComponent(value: string, field: string) {
  if (!value) {
    return "";
  }

  try {
    return decodeURIComponent(value);
  } catch {
    throw new Error(`DATABASE_URL contem ${field} com codificacao invalida.`);
  }
}
