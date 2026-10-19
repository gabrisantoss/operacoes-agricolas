import assert from "node:assert/strict";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test, { after, before } from "node:test";
import ExcelJS from "exceljs";
import { createPostgresTestDatabase } from "../testSupport/postgresTestDatabase.js";

process.env.NODE_ENV = "test";
const testDatabaseUrl = process.env.BALANCA_TEST_DATABASE_URL?.trim();

if (!testDatabaseUrl) {
  test.skip("Order import integration tests require BALANCA_TEST_DATABASE_URL", () => {});
} else {
  const testDatabase = await createPostgresTestDatabase();
  const { closeOrder, createFarm, createOrder, db, listFarms, listOrders } = await import("../db.js");
  const { commitOrderImport, findOrderImport, listOrderImports, orderImportReportCsv, previewOrderImport } =
    await import("./orderImport.js");
  const folder = await fs.mkdtemp(path.join(os.tmpdir(), "os-excel-"));

  // Synthetic spreadsheet in the layout accepted by the public importer (extra columns are ignored).
  async function writeSheet(name: string, rows: Array<[string, string, string]>) {
    const workbook = new ExcelJS.Workbook();
    const sheet = workbook.addWorksheet("OS demonstrativa");
    sheet.addRow(["Codigo da OS", "Propriedade", "Setor", "Observacao"]);
    for (const row of rows) sheet.addRow([...row, "Exemplo ficticio"]);
    const filePath = path.join(folder, name);
    await workbook.xlsx.writeFile(filePath);
    return filePath;
  }

  before(() => {
    createFarm({ code: "100-961", name: "FAZENDA IMPORTACAO DEMO", fields: ["1", "2", "3"] });
    createFarm({ code: "100-962", name: "FAZENDA HISTORICA DEMO", fields: ["1"] });
    const farms = listFarms();
    const historic = farms.find((farm) => farm.code === "100-962")!;
    const closed = createOrder({ number: "OS-HIST-1", farmId: historic.id, fieldIds: [historic.fields[0]!.id], frontNumbers: [] });
    assert.ok(closed && closeOrder(closed.id));
  });

  after(async () => {
    await fs.rm(folder, { recursive: true, force: true });
    await Promise.resolve(db.close?.());
    await testDatabase.cleanup();
  });

  test("first export creates orders, keeps closed ones and records the import", async () => {
    const file = await writeSheet("export-1.xlsx", [
      ["OS-IMP-1", "100-961", "1"],
      ["OS-IMP-1", "100961", "2"],
      ["OS-HIST-1", "100-962", "1"]
    ]);
    const preview = await previewOrderImport(file, "export-1.xlsx");

    assert.equal(preview.summary.createCount, 1);
    assert.equal(preview.summary.skippedCount, 1);
    assert.equal(preview.summary.errorsCount, 0);
    assert.equal(preview.previousImport, null);

    const result = await commitOrderImport(file, "export-1.xlsx", preview.fileHash);
    assert.ok(result.importId);
    const created = listOrders().find((order) => order.number === "OS-IMP-1")!;
    assert.equal(created.origin, "EXCEL");
    assert.equal(created.fields.length, 2);
    assert.equal(listOrders().find((order) => order.number === "OS-HIST-1")!.status, "CLOSED");
  });

  test("the same file again is identified as a re-import and not applied twice", async () => {
    // A re-import is the very same file (same bytes), possibly renamed.
    const file = path.join(folder, "export-1-copia.xlsx");
    await fs.copyFile(path.join(folder, "export-1.xlsx"), file);
    const preview = await previewOrderImport(file, "export-1-copia.xlsx");

    assert.equal(preview.previousImport?.fileName, "export-1.xlsx");
    await assert.rejects(() => commitOrderImport(file, "export-1-copia.xlsx", preview.fileHash), /ja foi importado/);
    assert.equal(listOrderImports().length, 1);
  });

  test("a later export updates legitimately and reports what it cannot apply", async () => {
    const file = await writeSheet("export-2.xlsx", [
      ["OS-IMP-1", "100-961", "1"],
      ["OS-IMP-1", "100-961", "3"],
      ["OS-IMP-2", "100-961", "2"]
    ]);
    const preview = await previewOrderImport(file, "export-2.xlsx");

    assert.equal(preview.summary.updateCount, 1);
    assert.equal(preview.summary.errorsCount, 0);
    assert.deepEqual(preview.divergences.map((item) => item.kind).sort(), ["FIELD_IN_OTHER_ACTIVE_ORDER", "FIELD_MISSING_FROM_SHEET"]);

    await commitOrderImport(file, "export-2.xlsx", preview.fileHash);
    const order = listOrders().find((item) => item.number === "OS-IMP-1")!;
    assert.deepEqual(order.fields.map((field) => field.field.code).sort(), ["1", "2", "3"]);
    assert.equal(listOrders().some((item) => item.number === "OS-IMP-2"), false);
  });

  test("history keeps every import with its rows, divergences and a CSV report", () => {
    const imports = listOrderImports();
    assert.deepEqual(imports.map((item) => item.fileName), ["export-2.xlsx", "export-1.xlsx"]);
    assert.equal(imports[0]!.updateCount, 1);
    assert.equal(imports[0]!.divergenceCount, 2);

    const detail = findOrderImport(imports[0]!.id);
    assert.equal(detail.items.length, 3);
    assert.equal(detail.divergences.length, 2);

    const csv = orderImportReportCsv(imports[0]!.id);
    assert.match(csv, /"Setor adicionado"/);
    assert.match(csv, /"Divergencia \(nao aplicada\)"/);
    assert.match(csv, /sem remocao automatica/);
    assert.throws(() => findOrderImport("nao-existe"), /nao encontrada/);
  });

  test("a spreadsheet with an unknown property is blocked and nothing is recorded", async () => {
    const file = await writeSheet("export-erro.xlsx", [["OS-IMP-3", "999-999", "1"]]);
    const preview = await previewOrderImport(file, "export-erro.xlsx");

    assert.equal(preview.summary.errorsCount, 1);
    await assert.rejects(() => commitOrderImport(file, "export-erro.xlsx", preview.fileHash), /Importacao bloqueada/);
    assert.equal(listOrderImports().length, 2);
  });
}
