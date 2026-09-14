import { execFile } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { promisify } from "node:util";

const execFileAsync = promisify(execFile);

type ExternalCommand = "exiftool" | "pdftoppm" | "pdftotext" | "tesseract";

const commandConfig: Record<ExternalCommand, { env: string[]; binDirEnv?: string[]; windowsExe: string }> = {
  exiftool: {
    env: ["EXIFTOOL_CMD", "EXIFTOOL_PATH"],
    windowsExe: "exiftool.exe"
  },
  pdftoppm: {
    env: ["PDFTOPPM_CMD", "PDFTOPPM_PATH"],
    binDirEnv: ["POPPLER_BIN_DIR", "MAP_POPPLER_BIN_DIR"],
    windowsExe: "pdftoppm.exe"
  },
  pdftotext: {
    env: ["PDFTOTEXT_CMD", "PDFTOTEXT_PATH"],
    binDirEnv: ["POPPLER_BIN_DIR", "MAP_POPPLER_BIN_DIR"],
    windowsExe: "pdftotext.exe"
  },
  tesseract: {
    env: ["TESSERACT_CMD", "TESSERACT_PATH", "MAP_TESSERACT_CMD", "MAP_TESSERACT_PATH"],
    binDirEnv: ["TESSERACT_BIN_DIR", "MAP_TESSERACT_BIN_DIR"],
    windowsExe: "tesseract.exe"
  }
};

export function resolveExternalCommand(command: ExternalCommand) {
  const config = commandConfig[command];

  for (const name of config.env) {
    const value = process.env[name]?.trim();

    if (value) {
      return path.resolve(value);
    }
  }

  for (const name of config.binDirEnv ?? []) {
    const value = process.env[name]?.trim();

    if (value) {
      return path.join(path.resolve(value), process.platform === "win32" ? config.windowsExe : command);
    }
  }

  return command;
}

export async function execExternalCommand(
  command: ExternalCommand,
  args: string[],
  options: { timeout?: number; maxBuffer?: number } = {}
) {
  return execFileAsync(resolveExternalCommand(command), args, options);
}

export function externalCommandExists(command: ExternalCommand) {
  const resolved = resolveExternalCommand(command);

  if (resolved === command) {
    return true;
  }

  return fs.existsSync(resolved);
}
