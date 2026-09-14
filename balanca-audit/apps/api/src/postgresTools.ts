import fs from "node:fs";
import path from "node:path";

export function resolvePostgresTool(tool: "pg_dump" | "pg_restore") {
  const configuredName = tool === "pg_dump" ? "PG_DUMP_BIN" : "PG_RESTORE_BIN";
  const configured = process.env[configuredName]?.trim();
  if (configured) {
    return configured;
  }

  const executable = process.platform === "win32" ? `${tool}.exe` : tool;
  const configuredDir = process.env.POSTGRES_BIN_DIR?.trim();
  if (configuredDir) {
    const candidate = path.join(configuredDir, executable);
    if (fs.existsSync(candidate)) {
      return candidate;
    }
  }

  if (process.platform === "win32") {
    const programFiles = process.env.ProgramFiles || "C:\\Program Files";
    const postgresRoot = path.join(programFiles, "PostgreSQL");
    try {
      const versions = fs.readdirSync(postgresRoot, { withFileTypes: true })
        .filter((entry) => entry.isDirectory())
        .map((entry) => entry.name)
        .sort((left, right) => right.localeCompare(left, undefined, { numeric: true }));
      for (const version of versions) {
        const candidate = path.join(postgresRoot, version, "bin", executable);
        if (fs.existsSync(candidate)) {
          return candidate;
        }
      }
    } catch {
      // Fall through to PATH lookup by spawn.
    }
  }

  return executable;
}
