const spreadsheetFormulaPrefix = /^[\u0000-\u0020]*[=+\-@]/;

export function csvCell(value: unknown) {
  const text = value === undefined || value === null ? "" : String(value);
  const neutralized = typeof value === "string" && spreadsheetFormulaPrefix.test(text) ? `'${text}` : text;
  return `"${neutralized.replace(/"/g, '""')}"`;
}

export function toSemicolonCsv(rows: unknown[][]) {
  return rows.map((row) => row.map(csvCell).join(";")).join("\n");
}
