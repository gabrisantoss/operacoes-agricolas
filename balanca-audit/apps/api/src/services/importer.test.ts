import assert from "node:assert/strict";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test, { after } from "node:test";
import { createPostgresTestDatabase } from "../testSupport/postgresTestDatabase.js";

process.env.NODE_ENV = "test";
const testDatabaseUrl = process.env.BALANCA_TEST_DATABASE_URL?.trim();

if (!testDatabaseUrl) {
  test.skip("Importer integration tests require BALANCA_TEST_DATABASE_URL", () => {});
} else {
const testDatabase = await createPostgresTestDatabase();

const {
  commitImport,
  findOrderForFieldByEntryDate,
  parseCaneSummaryPdfText,
  parseCaneSummaryPdfTextVariants,
  parseImportDate,
  readNumber
} = await import("./importer.js");
const { releasePostHarvestForClosedOrder } = await import("./postHarvestIntegrationService.js");
const {
  closeOrder,
  createFarm,
  createField,
  createImportBatch,
  createOrder,
  db,
  deleteOrder,
  findActiveOrderForFront,
  findOrderById,
  findPdfImportBatchByPeriod,
  findFarmByRaw,
  listFarms,
  listAvailableYears,
  listOrderHistory,
  listPostHarvestIntegrationEvents,
  listOrders,
  listOrdersWithNumber,
  removeOrderFarm,
  updateFarm,
  updateField,
  updateOrder,
} = await import("../db.js");

after(async () => {
  await Promise.resolve(db.close?.());
  await testDatabase.cleanup();
});

test("findOrderForFieldByEntryDate selects the historical order that covers the entry date", () => {
  const orders = [
    fakeOrder("active", "ACTIVE", "2026-01-01", null),
    fakeOrder("closed", "CLOSED", "2025-04-01", "2025-11-30")
  ];

  assert.equal(findOrderForFieldByEntryDate(orders, "farm-1", "field-1", "2025-08-15")?.id, "closed");
  assert.equal(findOrderForFieldByEntryDate(orders, "farm-1", "field-1", "2026-02-10")?.id, "active");
});

test("findOrderForFieldByEntryDate does not guess between ambiguous historical orders", () => {
  const orders = [
    fakeOrder("closed-a", "CLOSED", "2025-01-01", "2025-12-31"),
    fakeOrder("closed-b", "CLOSED", "2025-06-01", "2025-10-31")
  ];

  assert.equal(findOrderForFieldByEntryDate(orders, "farm-1", "field-1", "2025-08-15"), null);
});

function fakeOrder(id: string, status: "ACTIVE" | "CLOSED", startDate: string, endDate: string | null) {
  return {
    id,
    number: id,
    status,
    startDate,
    endDate,
    farmId: "farm-1",
    farmIds: ["farm-1"],
    frontNumbers: [],
    farm: { id: "farm-1" },
    farms: [{ id: "farm-1" }],
    fields: [{ id: `${id}-link`, fieldId: "field-1", field: { id: "field-1", farmId: "farm-1" } }]
  } as unknown as Parameters<typeof findOrderForFieldByEntryDate>[0][number];
}

test("parseImportDate reads Brazilian dates", () => {
  assert.equal(parseImportDate("31/03/2026")?.toISOString(), "2026-03-31T00:00:00.000Z");
  assert.equal(parseImportDate("31/03/26 14:30")?.toISOString(), "2026-03-31T14:30:00.000Z");
});

test("parseImportDate reads Excel serial dates", () => {
  assert.equal(parseImportDate(46112)?.toISOString(), "2026-03-31T00:00:00.000Z");
});

test("readNumber keeps decimal points and Brazilian decimal commas", () => {
  assert.equal(readNumber({ peso: "1.234,56" }, "peso"), 1234.56);
  assert.equal(readNumber({ peso: "1234.56" }, "peso"), 1234.56);
});

test("farm repository facade creates and updates farms and fields", () => {
  const suffix = `repo-fazenda-${process.pid}`;
  const farm = createFarm({
    code: `R-${suffix}`,
    name: `Fazenda Repo ${suffix}`,
    fields: ["10"]
  });
  assert.ok(farm);
  assert.equal(farm.fields.length, 1);
  assert.equal(farm.fields[0].code, "10");

  const updatedFarm = updateFarm(farm.id, {
    code: `R2-${suffix}`,
    name: `Fazenda Repo Atualizada ${suffix}`
  });
  assert.ok(updatedFarm);
  const expectedUpdatedCodeDigits = `2${process.pid}`;
  assert.equal(updatedFarm.name, `FAZENDA REPO ATUALIZADA ${suffix.toLocaleUpperCase("pt-BR")}`);
  assert.equal(updatedFarm.code, `${expectedUpdatedCodeDigits.slice(0, 3)}-${expectedUpdatedCodeDigits.slice(3)}`);

  const field = createField(farm.id, "11", "Talhao onze", 2);
  assert.ok(field);
  assert.equal(field.areaAlq, 2);
  assert.equal(field.areaHa, 4.84);

  const updatedField = updateField(field.id, {
    code: "12",
    name: "Talhao doze",
    areaAlq: 3
  });
  assert.ok(updatedField);
  assert.equal(updatedField.code, "12");
  assert.equal(updatedField.name, "Talhao doze");
  assert.equal(updatedField.areaAlq, 3);
  assert.equal(updatedField.areaHa, 7.26);

  const persisted = listFarms().find((item) => item.id === farm.id);
  assert.ok(persisted);
  assert.equal(persisted.fields.some((item) => item.code === "12"), true);
});

test("findFarmByRaw does not merge a different explicit supplier code by name prefix", () => {
  const farm = createFarm({
    code: "200-2471",
    name: `Fazenda Aparecida prefix ${process.pid}`,
    fields: ["7"]
  });
  assert.ok(farm);

  assert.equal(findFarmByRaw(`${farm.name} A`, "200-2472"), null);
});

test("findFarmByRaw accepts harmless supplier zero padding in an explicit code", () => {
  const farm = createFarm({
    code: "221-8",
    name: `Fazenda codigo preenchido ${process.pid}`,
    fields: ["4"]
  });
  assert.ok(farm);

  assert.equal(findFarmByRaw("Nome divergente no PDF", "221-008")?.id, farm.id);
});

test("orders repository facade lists and finds orders with farms, fields and fronts", () => {
  const suffix = `repo-os-${process.pid}`;
  const farm = createFarm({ name: `Fazenda OS ${suffix}`, fields: ["21", "22"] });
  assert.ok(farm);
  const fieldIds = farm.fields.map((field) => field.id);

  const order = createOrder({
    number: `OS-${suffix}`,
    frontNumbers: [3, 7],
    farmId: farm.id,
    fieldIds
  });
  assert.ok(order);

  const listed = listOrders().find((item) => item.id === order.id);
  assert.ok(listed);
  assert.deepEqual(listed.frontNumbers, [3, 7]);
  assert.equal(listed.farms.length, 1);
  assert.equal(listed.farms[0].id, farm.id);
  assert.deepEqual(
    listed.fields.map((item) => item.field.code),
    ["21", "22"]
  );

  const byNumber = listOrdersWithNumber(`OS-${suffix}`)[0];
  assert.ok(byNumber);
  assert.equal(byNumber.id, order.id);

  const byId = findOrderById(order.id);
  assert.ok(byId);
  assert.equal(byId.number, `OS-${suffix}`);
  assert.equal(listAvailableYears().includes(new Date().getFullYear()), true);
});

test("orders repository facade updates, closes and deletes orders", () => {
  const suffix = `repo-os-write-${process.pid}`;
  const farm = createFarm({ name: `Fazenda OS Escrita ${suffix}`, fields: ["31", "32", "33"] });
  assert.ok(farm);
  const [firstField, secondField, thirdField] = farm.fields;

  const order = createOrder({
    number: `OS-W-${suffix}`,
    frontNumbers: [4],
    farmId: farm.id,
    fieldIds: [firstField.id, secondField.id]
  });
  assert.ok(order);
  assert.equal(findActiveOrderForFront(4)?.id, order.id);

  const updated = updateOrder(order.id, {
    number: `OS-W2-${suffix}`,
    frontNumbers: [5, 6],
    farmId: farm.id,
    fieldIds: [thirdField.id]
  });
  assert.ok(updated);
  assert.equal(updated.number, `OS-W2-${suffix}`);
  assert.deepEqual(updated.frontNumbers, [5, 6]);
  assert.deepEqual(
    updated.fields.map((item) => item.field.code),
    ["33"]
  );
  assert.equal(findActiveOrderForFront(4), null);
  assert.equal(findActiveOrderForFront(5)?.id, order.id);

  const closed = closeOrder(order.id);
  assert.ok(closed);
  assert.equal(closed.status, "CLOSED");
  assert.equal(findActiveOrderForFront(5), null);

  const historyEvents = listOrderHistory(20).filter((item) => item.orderId === order.id).map((item) => item.eventType);
  assert.deepEqual(historyEvents, ["CLOSED", "FRONTS_CHANGED", "STARTED"]);

  assert.equal(deleteOrder(order.id), true);
  assert.equal(findOrderById(order.id), null);
});















test("parseCaneSummaryPdfText reads SCS0110P cane summary rows", () => {
  const text = `
Resumo de Cana Entregue - Talhao                      Operacoes Agricolas S/A                                       Data: 28 / 08 / 2025   10 : 24
PERIODO 27/08/2025 A 27/08/2025 - SAFRA 2025/2026                                                          SCS0110P        Pagina:   00001
ORIGEM         PICADA INTEIRA
    Codigo                           Fornecedor                Fundo Agricola         Talhao   KM   Area   Cana Entregue       Viagens

  220       26 EMPRESA DEMONSTRATIVA RURAL SA       FAZENDA DEMO SOL II                 10    5                   60,060             1
                                                                                TOTAL PROPRIEDADE                1.691,260            29
`;

  const parsed = parseCaneSummaryPdfText(text);

  assert.equal(parsed.rows.length, 1);
  assert.equal(parsed.rows[0].farmRaw, "FAZENDA DEMO SOL II");
  assert.equal(parsed.rows[0].fieldRaw, "10");
  assert.equal(parsed.rows[0].farmCodeRaw, "220-026");
  assert.equal(parsed.rows[0].netWeight, 60.06);
  assert.equal(parsed.rows[0].tripCount, 1);
  assert.equal(parsed.rows[0].entryDate?.toISOString(), "2025-08-27T00:00:00.000Z");
  assert.equal(parsed.metadata.periodStart?.toISOString(), "2025-08-27T00:00:00.000Z");
  assert.equal(parsed.metadata.periodEnd?.toISOString(), "2025-08-27T00:00:00.000Z");
});

test("parseCaneSummaryPdfText keeps a trailing farm number out of the field column", () => {
  const text = `
Resumo de Cana Entregue - Talhao                      Operacoes Agricolas S/A                                       Data: 20 / 06 / 2026   08 : 39
PERIODO 19/06/2026 A 19/06/2026 - SAFRA 2026/2027                                                          SCS0110P        Pagina:   00001

  221       9 PRODUTOR FICTICIO TESTE              FAZENDA DEMO LUA -D 2    04 35 245,160 3
`;

  const parsed = parseCaneSummaryPdfText(text);

  assert.equal(parsed.rows.length, 1);
  assert.equal(parsed.rows[0].farmCodeRaw, "221-009");
  assert.equal(parsed.rows[0].farmRaw, "FAZENDA DEMO LUA -D 2");
  assert.equal(parsed.rows[0].fieldRaw, "04");
  assert.equal(parsed.rows[0].netWeight, 245.16);
  assert.equal(parsed.rows[0].tripCount, 3);
});

test("parseCaneSummaryPdfText reads SCS0110P rows without space before field code", () => {
  const text = `
Resumo de Cana Entregue - Talhao                      Operacoes Agricolas S/A                                       Data: 02 / 05 / 2026   09 : 03
PERIODO 28/04/2026 A 1/05/2026 - SAFRA 2026/2027                                                          SCS0110P        Pagina:   00002

  105    1964 Operacoes Agricolas S/A                      FAZ DEMO CAMPO AZUL - D 1/PESSOA DEMO01        60                  902,280            12
`;

  const parsed = parseCaneSummaryPdfText(text);

  assert.equal(parsed.rows.length, 1);
  assert.equal(parsed.rows[0].farmCodeRaw, "105-1964");
  assert.equal(parsed.rows[0].farmRaw, "FAZ DEMO CAMPO AZUL - D 1/PESSOA DEMO");
  assert.equal(parsed.rows[0].fieldRaw, "01");
  assert.equal(parsed.rows[0].entryDate?.toISOString(), "2026-04-28T00:00:00.000Z");
  assert.equal(parsed.metadata.periodStart?.toISOString(), "2026-04-28T00:00:00.000Z");
  assert.equal(parsed.metadata.periodEnd?.toISOString(), "2026-05-01T00:00:00.000Z");
  assert.equal(parsed.metadata.isConsolidatedPeriod, true);
});

test("parseCaneSummaryPdfText reads compact PDF rows with glued trips", () => {
  const text = `
Resumo de Cana Entregue - TalhÃ£o                      Operacoes Agricolas S/A                                       Data: 04 / 06 / 2026   15 : 40
PERIODO 04/06/26 A 04/06/26 - SAFRA 2026/2027                                                             SCS0110P        Pagina:   00001

1051964 Operacoes Agricolas S/A                      FAZ DEMO CAMPO AZUL - D 1/PESSOA DEMO01        60                  902,28012
TOTAL GERAL 902,28012
`;

  const parsed = parseCaneSummaryPdfText(text);

  assert.equal(parsed.rows.length, 1);
  assert.equal(parsed.rows[0].farmCodeRaw, "105-1964");
  assert.equal(parsed.rows[0].farmRaw, "FAZ DEMO CAMPO AZUL - D 1/PESSOA DEMO");
  assert.equal(parsed.rows[0].fieldRaw, "01");
  assert.equal(parsed.rows[0].netWeight, 902.28);
  assert.equal(parsed.rows[0].tripCount, 12);
  assert.equal(parsed.rows[0].entryDate?.toISOString(), "2026-06-04T00:00:00.000Z");
});

test("parseCaneSummaryPdfTextVariants deduplicates extraction variants and reconciles TOTAL GERAL", () => {
  const header = `
Resumo de Cana Entregue - Talhao                      Operacoes Agricolas S/A                                       Data: 19 / 06 / 2026   08 : 39
PERIODO 18/06/2026 A 18/06/2026 - SAFRA 2026/2027                                                          SCS0110P        Pagina:   00001
`;
  const layout = `${header}
  113     2457 Operacoes Agricolas S/A                      FAZ DEMO LUZ - I-A empresa               26    10                  303,840             4
  200     2289 PRODUTOR TESTE                        FAZENDA DEMO VALE 55 KM.                  01    55                  538,380             7
TOTAL GERAL 842,220 11
`;
  const raw = `${header}
113 2457 Operacoes Agricolas S/A empresa 26 10 303,840 4
200 2289 PRODUTOR TESTE FAZENDA DEMO VALE 55 KM. 01 55 538,380 7
TOTAL GERAL 842,220 11
`;

  const parsed = parseCaneSummaryPdfTextVariants([layout, raw]);

  assert.equal(parsed.rows.length, 2);
  assert.equal(parsed.rows[0].farmRaw, "FAZ DEMO LUZ - I-A empresa");
  assert.equal(parsed.metadata.reconciliation?.status, "MATCH");
  assert.equal(parsed.metadata.reconciliation?.parsedNetWeight, 842.22);
  assert.equal(parsed.metadata.reconciliation?.parsedTrips, 11);
});

test("parseCaneSummaryPdfText reports a mismatch when parsed rows do not close with TOTAL GERAL", () => {
  const text = `
Resumo de Cana Entregue - Talhao                      Operacoes Agricolas S/A                                       Data: 19 / 06 / 2026   08 : 39
PERIODO 18/06/2026 A 18/06/2026 - SAFRA 2026/2027                                                          SCS0110P        Pagina:   00001
  113     2457 Operacoes Agricolas S/A                      FAZ DEMO LUZ - I-A empresa               26    10                  303,840             4
TOTAL GERAL 842,220 11
`;

  const parsed = parseCaneSummaryPdfText(text);

  assert.equal(parsed.metadata.reconciliation?.status, "MISMATCH");
  assert.equal(parsed.metadata.reconciliation?.netWeightDifference, -538.38);
  assert.equal(parsed.metadata.reconciliation?.tripDifference, -7);
});

test("findPdfImportBatchByPeriod detects only the same already imported PDF period", () => {
  const suffix = `periodo-duplicado-${process.pid}`;
  const batch = createImportBatch({
    fileName: `SCS0110P-${suffix}.pdf`,
    rowCount: 1,
    metadata: {
      sourceType: "SCS0110P_PDF",
      periodStart: new Date("2026-05-19T00:00:00.000Z"),
      periodEnd: new Date("2026-05-21T00:00:00.000Z")
    }
  });
  assert.ok(batch);

  const samePeriod = findPdfImportBatchByPeriod(
    new Date("2026-05-19T00:00:00.000Z"),
    new Date("2026-05-21T00:00:00.000Z")
  );
  const insideRange = findPdfImportBatchByPeriod(
    new Date("2026-05-20T00:00:00.000Z"),
    new Date("2026-05-20T00:00:00.000Z")
  );
  const adjacentRange = findPdfImportBatchByPeriod(
    new Date("2026-05-21T00:00:00.000Z"),
    new Date("2026-05-22T00:00:00.000Z")
  );
  const outside = findPdfImportBatchByPeriod(
    new Date("2026-05-22T00:00:00.000Z"),
    new Date("2026-05-22T00:00:00.000Z")
  );

  assert.equal(samePeriod?.id, batch.id);
  assert.equal(insideRange, null);
  assert.equal(adjacentRange, null);
  assert.equal(outside, null);
});

test("commitImport validates spreadsheet row by active farm and field when OS is missing", async () => {
  const suffix = `sem-os-${process.pid}`;
  const farm = createFarm({ name: `Fazenda ${suffix}`, fields: ["10"] });
  assert.ok(farm);
  const field = farm.fields[0];
  const order = createOrder({ number: `Frente ${suffix}`, frontNumber: 1, farmId: farm.id, fieldIds: [field.id] });
  assert.ok(order);

  const filePath = path.join(os.tmpdir(), `balanca-${suffix}.csv`);
  await fs.writeFile(filePath, `Fazenda,Talhao,OS\n${farm.name},${field.code},\n`, "utf8");

  const result = await commitImport(filePath, `balanca-${suffix}.csv`);
  const entry = db
    .prepare("SELECT status, order_id, order_number_raw FROM cane_entries WHERE batch_id = ?")
    .get(result.batch?.id) as { status: string; order_id: string | null; order_number_raw: string | null } | undefined;

  assert.equal(entry?.status, "OK");
  assert.equal(entry?.order_id, order.id);
  assert.equal(entry?.order_number_raw, order.number);
});

test("commitImport rejects a file already saved in history", async () => {
  const suffix = `duplicado-${process.pid}`;
  const farm = createFarm({ name: `Fazenda ${suffix}`, fields: ["10"] });
  assert.ok(farm);
  const field = farm.fields[0];
  const order = createOrder({ number: `Frente ${suffix}`, frontNumber: 1, farmId: farm.id, fieldIds: [field.id] });
  assert.ok(order);

  const content = `Fazenda,Talhao,OS\n${farm.name},${field.code},\n`;
  const firstFilePath = path.join(os.tmpdir(), `balanca-${suffix}-1.csv`);
  const secondFilePath = path.join(os.tmpdir(), `balanca-${suffix}-2.csv`);
  await fs.writeFile(firstFilePath, content, "utf8");
  await fs.writeFile(secondFilePath, content, "utf8");

  await commitImport(firstFilePath, `balanca-${suffix}-1.csv`);

  await assert.rejects(
    () => commitImport(secondFilePath, `balanca-${suffix}-2.csv`),
    /arquivo ja foi lancado/i
  );
});

test("commitImport falls back to active farm and field when spreadsheet OS is external", async () => {
  const suffix = `os-externa-${process.pid}`;
  const farm = createFarm({ name: `Fazenda ${suffix}`, fields: ["12"] });
  assert.ok(farm);
  const field = farm.fields[0];
  const order = createOrder({ number: `Frente ${suffix}`, frontNumber: 2, farmId: farm.id, fieldIds: [field.id] });
  assert.ok(order);

  const filePath = path.join(os.tmpdir(), `balanca-${suffix}.csv`);
  await fs.writeFile(filePath, `Fazenda,Talhao,OS\n${farm.name},${field.code},OS-EXTERNA-123\n`, "utf8");

  const result = await commitImport(filePath, `balanca-${suffix}.csv`);
  const entry = db
    .prepare("SELECT status, order_id, order_number_raw FROM cane_entries WHERE batch_id = ?")
    .get(result.batch?.id) as { status: string; order_id: string | null; order_number_raw: string | null } | undefined;

  assert.equal(entry?.status, "OK");
  assert.equal(entry?.order_id, order.id);
  assert.equal(entry?.order_number_raw, "OS-EXTERNA-123");
});

test("commitImport accepts one OS with more than one active front", async () => {
  const suffix = `os-multifrent-${process.pid}`;
  const farm = createFarm({ name: `Fazenda ${suffix}`, fields: ["1", "2"] });
  assert.ok(farm);
  const order = createOrder({
    number: `OS-${suffix}`,
    frontNumber: 3,
    frontNumbers: [3, 4],
    farmId: farm.id,
    fieldIds: farm.fields.map((field) => field.id)
  });
  assert.ok(order);

  const filePath = path.join(os.tmpdir(), `balanca-${suffix}.csv`);
  await fs.writeFile(filePath, `Fazenda,Talhao,OS\n${farm.name},${farm.fields[0].code},OS-${suffix}\n`, "utf8");

  const result = await commitImport(filePath, `balanca-${suffix}.csv`);
  const entry = db
    .prepare("SELECT status, order_id, order_number_raw FROM cane_entries WHERE batch_id = ?")
    .get(result.batch?.id) as { status: string; order_id: string | null; order_number_raw: string | null } | undefined;

  assert.equal(entry?.status, "OK");
  assert.equal(entry?.order_id, order.id);
  assert.equal(entry?.order_number_raw, `OS-${suffix}`);
});

test("commitImport accepts one OS with fields from more than one farm", async () => {
  const suffix = `os-multifaz-${process.pid}`;
  const firstFarm = createFarm({ name: `Fazenda A ${suffix}`, fields: ["1"] });
  const secondFarm = createFarm({ name: `Fazenda B ${suffix}`, fields: ["8"] });
  assert.ok(firstFarm);
  assert.ok(secondFarm);
  const order = createOrder({
    number: `OS-${suffix}`,
    frontNumber: 5,
    farmId: firstFarm.id,
    fieldIds: [firstFarm.fields[0].id, secondFarm.fields[0].id]
  });
  assert.ok(order);

  const filePath = path.join(os.tmpdir(), `balanca-${suffix}.csv`);
  await fs.writeFile(filePath, `Fazenda,Talhao,OS\n${secondFarm.name},${secondFarm.fields[0].code},OS-${suffix}\n`, "utf8");

  const result = await commitImport(filePath, `balanca-${suffix}.csv`);
  const entry = db
    .prepare("SELECT status, order_id, order_number_raw FROM cane_entries WHERE batch_id = ?")
    .get(result.batch?.id) as { status: string; order_id: string | null; order_number_raw: string | null } | undefined;

  assert.equal(entry?.status, "OK");
  assert.equal(entry?.order_id, order.id);
  assert.equal(entry?.order_number_raw, `OS-${suffix}`);
});
}
