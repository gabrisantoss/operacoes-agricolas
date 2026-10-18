import assert from "node:assert/strict";
import test from "node:test";
import { columnAliases, detectMapping, findColumn } from "./importColumnMapping.js";

test("maps the demo CSV columns without confusing plate and net weight", () => {
  const mapping = detectMapping(["ticket", "data", "fazenda", "talhao", "os", "placa", "peso_bruto", "peso_liquido"]);

  assert.deepEqual(mapping, {
    ticketNumber: "ticket",
    entryDate: "data",
    farm: "fazenda",
    field: "talhao",
    order: "os",
    vehiclePlate: "placa",
    grossWeight: "peso_bruto",
    netWeight: "peso_liquido"
  });
});

test("matches short aliases only as whole words", () => {
  assert.equal(findColumn(["Placa"], columnAliases.netWeight), undefined);
  assert.equal(findColumn(["Posto"], columnAliases.order), undefined);
  assert.equal(findColumn(["Placa", "PL (t)"], columnAliases.netWeight), "PL (t)");
  assert.equal(findColumn(["Nº OS"], columnAliases.order), "Nº OS");
});

test("maps accented and punctuated spreadsheet headers", () => {
  const mapping = detectMapping([
    "Nº Nota",
    "Data Entrada",
    "Fazenda",
    "Talhão",
    "O.S.",
    "Placa",
    "Peso Bruto (t)",
    "Peso Líquido (t)"
  ]);

  assert.deepEqual(mapping, {
    ticketNumber: "Nº Nota",
    entryDate: "Data Entrada",
    farm: "Fazenda",
    field: "Talhão",
    order: "O.S.",
    vehiclePlate: "Placa",
    grossWeight: "Peso Bruto (t)",
    netWeight: "Peso Líquido (t)"
  });
});

test("keeps matching compact headers through long aliases", () => {
  const mapping = detectMapping(["DtEntrada", "PesoBruto", "PesoLiquido"]);

  assert.equal(mapping.entryDate, "DtEntrada");
  assert.equal(mapping.grossWeight, "PesoBruto");
  assert.equal(mapping.netWeight, "PesoLiquido");
});

test("prefers an exact header over an earlier partial match", () => {
  assert.equal(findColumn(["Data Saida", "Data"], columnAliases.entryDate), "Data");
  assert.equal(findColumn(["Data Saida", "Data Entrada"], columnAliases.entryDate), "Data Entrada");
});

test("keeps a user provided mapping over detection", () => {
  const mapping = detectMapping(["placa", "liquido_balanca"], { netWeight: "liquido_balanca", vehiclePlate: "placa" });

  assert.equal(mapping.netWeight, "liquido_balanca");
  assert.equal(mapping.vehiclePlate, "placa");
});
