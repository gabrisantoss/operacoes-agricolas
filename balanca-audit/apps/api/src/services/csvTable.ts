import { CsvError, parse } from "csv-parse/sync";

export const supportedCsvDelimiters = [";", ","] as const;
export type CsvDelimiter = (typeof supportedCsvDelimiters)[number];

const unsupportedDelimiters = ["\t", "|"];

export class CsvTableError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "CsvTableError";
  }
}

// Spreadsheet exports in pt-BR are often saved as Windows-1252 instead of UTF-8.
export function decodeCsvBuffer(buffer: Buffer) {
  try {
    return new TextDecoder("utf-8", { fatal: true }).decode(buffer);
  } catch {
    return new TextDecoder("windows-1252").decode(buffer);
  }
}

export function detectCsvDelimiter(content: string): CsvDelimiter {
  const header = readHeaderLine(content);
  const counts = supportedCsvDelimiters.map((delimiter) => countOutsideQuotes(header, delimiter));
  const best = Math.max(...counts);

  if (best === 0) {
    return ",";
  }

  const candidates = supportedCsvDelimiters.filter((_, index) => counts[index] === best);

  if (candidates.length === 1) {
    return candidates[0];
  }

  // Same count in the header: keep the delimiter whose rows agree with the header width.
  const scored = candidates.map((delimiter) => ({ delimiter, score: consistentRowCount(content, delimiter) }));
  scored.sort((left, right) => right.score - left.score);
  return scored[0].delimiter;
}

export function parseCsvTable(content: string): string[][] {
  const delimiter = detectCsvDelimiter(content);
  let table: string[][];

  try {
    table = parseWithDelimiter(content, delimiter);
  } catch (error) {
    if (error instanceof CsvError) {
      const line = typeof error.lines === "number" ? ` (linha ${error.lines})` : "";
      throw new CsvTableError(`Nao foi possivel ler o CSV${line}: confira aspas e separadores.`);
    }
    throw error;
  }

  const header = table[0] ?? [];
  if (header.length === 1 && unsupportedDelimiters.some((delimiter) => String(header[0]).includes(delimiter))) {
    throw new CsvTableError("Separador de CSV nao suportado. Use ponto e virgula (;) ou virgula (,).");
  }

  return table;
}

function parseWithDelimiter(content: string, delimiter: CsvDelimiter) {
  return parse(content, {
    bom: true,
    delimiter,
    relaxColumnCount: true,
    skip_empty_lines: true,
    skip_records_with_empty_values: true
  }) as string[][];
}

function readHeaderLine(content: string) {
  const text = content.replace(/^﻿/, "");
  let inQuotes = false;

  for (let index = 0; index < text.length; index += 1) {
    const char = text[index];

    if (char === '"') {
      inQuotes = !inQuotes;
    } else if (!inQuotes && (char === "\n" || char === "\r")) {
      const line = text.slice(0, index);
      if (line.trim()) {
        return line;
      }
      return readHeaderLine(text.slice(index + 1));
    }
  }

  return text;
}

function countOutsideQuotes(line: string, delimiter: string) {
  let count = 0;
  let inQuotes = false;

  for (const char of line) {
    if (char === '"') {
      inQuotes = !inQuotes;
    } else if (!inQuotes && char === delimiter) {
      count += 1;
    }
  }

  return count;
}

function consistentRowCount(content: string, delimiter: CsvDelimiter) {
  try {
    const [header = [], ...rows] = parseWithDelimiter(content, delimiter);
    return rows.filter((row) => row.length === header.length).length;
  } catch {
    return -1;
  }
}
