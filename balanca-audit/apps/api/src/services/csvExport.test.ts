import assert from "node:assert/strict";
import test from "node:test";
import { csvCell, toSemicolonCsv } from "./csvExport.js";

test("csvCell neutralizes formulas hidden behind whitespace and control characters", () => {
  assert.equal(csvCell("=WEBSERVICE(\"https://example.invalid\")"), "\"'=WEBSERVICE(\"\"https://example.invalid\"\")\"");
  assert.equal(csvCell("   +SUM(1;1)"), "\"'   +SUM(1;1)\"");
  assert.equal(csvCell("\t@SUM(A1:A2)"), "\"'\t@SUM(A1:A2)\"");
  assert.equal(csvCell("\r-2+3"), "\"'\r-2+3\"");
});

test("csvCell preserves safe strings and numeric values", () => {
  assert.equal(csvCell("Fazenda = Norte"), "\"Fazenda = Norte\"");
  assert.equal(csvCell(-42.5), "\"-42.5\"");
  assert.equal(csvCell('texto "entre aspas"'), '"texto ""entre aspas"""');
  assert.equal(toSemicolonCsv([["cabecalho", "=1+1"], [null, 12]]), '"cabecalho";"\'=1+1"\n"";"12"');
});
