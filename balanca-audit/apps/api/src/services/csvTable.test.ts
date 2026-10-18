import assert from "node:assert/strict";
import fs from "node:fs/promises";
import test from "node:test";
import { CsvTableError, decodeCsvBuffer, detectCsvDelimiter, parseCsvTable } from "./csvTable.js";

const demoCsvUrl = new URL("../../../../../demo-data/pesagem-ficticia.csv", import.meta.url);
const demoColumns = ["ticket", "data", "fazenda", "talhao", "os", "placa", "peso_bruto", "peso_liquido"];

test("reads the distributed demo CSV into the eight expected columns", async () => {
  const content = decodeCsvBuffer(await fs.readFile(demoCsvUrl));
  const [header, ...rows] = parseCsvTable(content);

  assert.equal(detectCsvDelimiter(content), ";");
  assert.deepEqual(header, demoColumns);
  assert.equal(rows.length, 6);
  for (const row of rows) {
    assert.equal(row.length, 8);
  }
  assert.deepEqual(rows[0], ["EXEMPLO-1", "14/09/2026", "100-901", "2", "90001", "DEMO-001", "43,500", "31,500"]);
});

test("keeps comma separated files with decimal points working", () => {
  const table = parseCsvTable("ticket,data,peso_liquido\nT-1,14/09/2026,31.5\nT-2,14/09/2026,30.25\n");

  assert.deepEqual(table, [
    ["ticket", "data", "peso_liquido"],
    ["T-1", "14/09/2026", "31.5"],
    ["T-2", "14/09/2026", "30.25"]
  ]);
});

test("keeps quoted decimal commas inside comma separated files", () => {
  const table = parseCsvTable('ticket,peso_liquido,obs\nT-1,"31,500","fila, portaria"\n');

  assert.equal(detectCsvDelimiter('ticket,peso_liquido,obs\n'), ",");
  assert.deepEqual(table[1], ["T-1", "31,500", "fila, portaria"]);
});

test("ignores delimiters inside quoted semicolon fields", () => {
  const content = 'ticket;"obs; livre";peso_liquido\nT-1;"chuva; atraso";31,500\n';

  assert.equal(detectCsvDelimiter(content), ";");
  assert.deepEqual(parseCsvTable(content), [
    ["ticket", "obs; livre", "peso_liquido"],
    ["T-1", "chuva; atraso", "31,500"]
  ]);
});

test("handles BOM, CRLF line endings and blank or separator-only rows", () => {
  const content = "﻿ticket;data;peso_liquido\r\nT-1;14/09/2026;31,500\r\n\r\n;;\r\nT-2;14/09/2026;30,000\r\n;;\r\n";

  assert.deepEqual(parseCsvTable(content), [
    ["ticket", "data", "peso_liquido"],
    ["T-1", "14/09/2026", "31,500"],
    ["T-2", "14/09/2026", "30,000"]
  ]);
});

test("decodes spreadsheet exports saved as Windows-1252", () => {
  const ansi = Buffer.from("ticket;talh\xE3o;peso_l\xEDquido\nT-1;2;31,500\n", "latin1");
  const utf8 = Buffer.from("ticket;talhão;peso_líquido\nT-1;2;31,500\n", "utf8");

  assert.deepEqual(parseCsvTable(decodeCsvBuffer(ansi))[0], ["ticket", "talhão", "peso_líquido"]);
  assert.deepEqual(parseCsvTable(decodeCsvBuffer(utf8))[0], ["ticket", "talhão", "peso_líquido"]);
});

test("uses the data rows to break a delimiter tie in the header", () => {
  const content = "a;b,c\nx,y\nz,w\n";

  assert.equal(detectCsvDelimiter(content), ",");
  assert.deepEqual(parseCsvTable(content)[1], ["x", "y"]);
});

test("reads a single column file without inventing a separator", () => {
  assert.deepEqual(parseCsvTable("ticket\nT-1\nT-2\n"), [["ticket"], ["T-1"], ["T-2"]]);
});

test("rejects unsupported separators instead of gluing every column together", () => {
  assert.throws(() => parseCsvTable("ticket\tdata\tpeso\nT-1\t14/09/2026\t31,5\n"), (error: unknown) => {
    assert.ok(error instanceof CsvTableError);
    assert.match(error.message, /ponto e virgula/);
    return true;
  });
  assert.throws(() => parseCsvTable("ticket|data|peso\nT-1|14/09/2026|31,5\n"), CsvTableError);
});

test("reports malformed quotes as a readable CSV error", () => {
  assert.throws(() => parseCsvTable('ticket;obs\nT-1;"sem fechamento\n'), (error: unknown) => {
    assert.ok(error instanceof CsvTableError);
    assert.match(error.message, /Nao foi possivel ler o CSV/);
    return true;
  });
});
