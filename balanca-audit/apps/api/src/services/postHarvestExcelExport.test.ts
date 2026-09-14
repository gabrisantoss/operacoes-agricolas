import assert from "node:assert/strict";
import test, { after } from "node:test";
import { createPostgresTestDatabase } from "../testSupport/postgresTestDatabase.js";

process.env.NODE_ENV = "test";
const testDatabaseUrl = process.env.BALANCA_TEST_DATABASE_URL?.trim();

if (!testDatabaseUrl) {
  test(
    "post-harvest export tests require BALANCA_TEST_DATABASE_URL",
    { skip: "BALANCA_TEST_DATABASE_URL is not configured" },
    () => {}
  );
} else {
  const testDatabase = await createPostgresTestDatabase();

  const {
    buildPostHarvestExportWorkbook,
    formatPostHarvestExportRow
  } = await import("./postHarvestExcelExport.js");
  const { db } = await import("../db.js");

  after(async () => {
    await Promise.resolve(db.close?.());
    await testDatabase.cleanup();
  });

  test("post harvest export preserves full sector and pads code and field", () => {
    const row = formatPostHarvestExportRow({
      order_id: "order-1",
      order_number: "OS12345",
      order_created_at: "2026-06-10T12:00:00.000Z",
      order_end_date: "2026-06-17T18:00:00.000Z",
      farm_code: "100-001",
      farm_name: "FAZENDA COLHEITA FELIZ",
      field_code: "1",
      area_alq: 2.5,
      area_ha: 6.05
    });

    assert.equal(row.setor, "100");
    assert.equal(row.codigo, "0001");
    assert.equal(row.talhao, "0001");
    assert.equal(row.idTalhao, "10000010001");
    assert.equal(row.fundoAgricola, "FAZENDA COLHEITA FELIZ");
  });

  test("post harvest export blocks farm codes longer than four digits", () => {
    assert.throws(
      () =>
        formatPostHarvestExportRow({
          order_id: "order-2",
          order_number: "OS99999",
          order_created_at: "2026-06-10T12:00:00.000Z",
          order_end_date: "2026-06-17T18:00:00.000Z",
          farm_code: "500-10109",
          farm_name: "FAZENDA TESTE",
          field_code: "1",
          area_alq: 1,
          area_ha: 2.42
        }),
      /mais de 4 digitos/
    );
  });

  test("post harvest workbook keeps exact columns, widths and formats", () => {
    const row = formatPostHarvestExportRow({
      order_id: "order-3",
      order_number: "OS25051",
      order_created_at: "2026-06-10T12:00:00.000Z",
      order_end_date: "2026-06-17T18:00:00.000Z",
      farm_code: "110-1030",
      farm_name: "FAZENDA BOM JESUS",
      field_code: "12",
      area_alq: 10.25,
      area_ha: 24.805,
      cane_tons: 198.44
    });
    const workbook = buildPostHarvestExportWorkbook([row]);
    const worksheet = workbook.getWorksheet("Talhoes OS Fechadas");

    assert.ok(worksheet);
    const headerValues = worksheet.getRow(1).values;
    assert.ok(Array.isArray(headerValues));
    assert.deepEqual(
      headerValues.slice(1),
      [
        "ID_talhao",
        "Data_Inicio",
        "Data_Fechamento",
        "Setor",
        "Codigo",
        "Fundo Agricola",
        "Talhao",
        "Area alq",
        "Area Ha"
      ]
    );
    assert.deepEqual(worksheet.columns.map((column) => column.width), [20, 16, 16, 10, 12, 42, 12, 14, 14]);
    assert.equal(worksheet.getCell("A2").value, "11010300012");
    assert.equal(worksheet.getCell("D2").value, "110");
    assert.equal(worksheet.getCell("E2").value, "1030");
    assert.equal(worksheet.getCell("G2").value, "0012");
    assert.equal(worksheet.getColumn("E").numFmt, "@");
    assert.equal(worksheet.getColumn("G").numFmt, "@");
    assert.equal(worksheet.getColumn("B").numFmt, "dd/mm/yyyy");
    assert.equal(worksheet.getColumn("H").numFmt, "#,##0.00");
    assert.equal(worksheet.autoFilter, "A1:I1");

    const harvestWorksheet = workbook.getWorksheet("Colheita por Talhao");
    assert.ok(harvestWorksheet);
    const harvestHeaders = harvestWorksheet.getRow(1).values;
    assert.ok(Array.isArray(harvestHeaders));
    assert.deepEqual(harvestHeaders.slice(1), [
      "ID_talhao",
      "OS",
      "Fundo Agricola",
      "Talhao",
      "Data_Fechamento",
      "Cana Entregue (t)",
      "TCH (t/ha)",
      "TCA (t/alq)"
    ]);
    assert.equal(harvestWorksheet.getCell("A2").value, "11010300012");
    assert.equal(harvestWorksheet.getCell("B2").value, "OS25051");
    assert.equal(harvestWorksheet.getCell("F2").value, 198.44);
    assert.equal(harvestWorksheet.getCell("G2").value, 198.44 / 24.805);
    assert.equal(harvestWorksheet.getCell("H2").value, 198.44 / 10.25);
    assert.equal(harvestWorksheet.autoFilter, "A1:H1");
  });
}
