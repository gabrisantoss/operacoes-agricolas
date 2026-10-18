import assert from "node:assert/strict";
import { createRequire } from "node:module";
import test from "node:test";
import type { CaneReportSourceRow } from "../db.js";
import { buildCaneReport } from "./caneReport.js";
import { formatTons, renderCaneReportPdf } from "./caneReportPdf.js";

const require = createRequire(import.meta.url);
const pdfParse = require("pdf-parse") as (data: Buffer) => Promise<{ text: string; numpages: number }>;
// Fixed generation time keeps the PDF bytes deterministic; the bundled pdf.js in pdf-parse rejects some valid files.
const generatedAt = new Date("2026-10-18T12:00:00.000Z");

function sourceRows(fieldCount: number): CaneReportSourceRow[] {
  return Array.from({ length: fieldCount }, (_, index) => ({
    farmId: index % 2 === 0 ? "farm-a" : "farm-b",
    farmCode: index % 2 === 0 ? "100-901" : "100-902",
    farmName: index % 2 === 0 ? "FAZENDA DEMO AURORA" : "FAZENDA DEMO HORIZONTE",
    fieldId: `field-${index}`,
    fieldCode: String(index + 1),
    fieldName: null,
    areaHa: 4.84,
    areaAlq: 2,
    referenceDate: `2026-09-${String((index % 28) + 1).padStart(2, "0")}`,
    fieldHarvestFirstDate: null,
    fieldHarvestLastDate: null,
    entryCount: 2,
    okCount: 2,
    divergentCount: 0,
    totalNetWeight: 63.25,
    divergentNetWeight: 0
  }));
}

async function pdfText(buffer: Buffer) {
  const parsed = await pdfParse(buffer);
  return { text: parsed.text, pages: parsed.numpages };
}

test("general PDF prints the same totals as the preview model", async () => {
  const report = buildCaneReport(sourceRows(6), { type: "GENERAL" }, { generatedAt });
  const buffer = await renderCaneReportPdf(report);
  const { text } = await pdfText(buffer);

  assert.equal(buffer.subarray(0, 4).toString(), "%PDF");
  assert.match(text, /Relatório geral de safra/);
  assert.ok(text.includes(formatTons(report.totals.totalNetWeight)), "total de cana do PDF difere da prévia");
  assert.equal(formatTons(report.totals.totalNetWeight), "379,500");
  assert.match(text, /FAZENDA DEMO AURORA/);
  assert.match(text, /Entregas por dia/);
  assert.match(text, /Todas as fazendas/);
});

test("detailed PDF paginates long tables and keeps headers and page numbers", async () => {
  const report = buildCaneReport(sourceRows(90), { type: "DETAILED" }, { generatedAt });
  const { text, pages } = await pdfText(await renderCaneReportPdf(report));

  assert.ok(pages >= 3, `esperado ao menos 3 paginas, obtido ${pages}`);
  assert.match(text, new RegExp(`Página ${pages} de ${pages}`));
  assert.ok((text.match(/Média\/carga \(t\)/g) ?? []).length >= pages - 1);
  assert.match(text, /Subtotal/);
  assert.match(text, /Resumo por fazenda/);
  assert.equal((text.match(/Relatório detalhado de safra por talhão \(continuação\)/g) ?? []).length, pages - 1);
  assert.equal((text.match(/Período: Todo o período/g) ?? []).length, pages);
  assert.ok(text.includes(formatTons(report.totals.totalNetWeight)));
});

test("partial-period PDF prints N/D and the explanation instead of an effective TCH", async () => {
  const rows = sourceRows(4).map((row) => ({ ...row, fieldHarvestFirstDate: "2026-08-25", fieldHarvestLastDate: row.referenceDate }));
  const report = buildCaneReport(rows, { type: "DETAILED", from: "2026-09-01", to: "2026-09-30" }, { generatedAt });
  const { text } = await pdfText(await renderCaneReportPdf(report));

  assert.equal(report.totals.tch, null);
  assert.match(text, /N\/D/);
  assert.match(text, /também têm entregas fora do período selecionado/);
  // Field tables show registered area; the farm summary shows harvested area, which is N/D here.
  assert.match(text, /Área cad\. \(ha\)/);
  assert.match(text, /Área colh\. \(ha\)/);
  assert.ok(text.includes("9,68"), "subtotal deve somar a area cadastrada dos talhoes");
  assert.ok(text.includes(formatTons(report.totals.totalNetWeight)));
});

test("the same report always renders the same PDF bytes", async () => {
  const report = buildCaneReport(sourceRows(6), { type: "DETAILED" }, { generatedAt });
  const first = await renderCaneReportPdf(report);
  const second = await renderCaneReportPdf(report);

  assert.ok(first.equals(second));
  assert.match(first.toString("latin1"), /\/CreationDate \d+ 0 R/);
});

test("empty PDF states that no records matched", async () => {
  const report = buildCaneReport([], { type: "DETAILED", from: "2030-01-01", to: "2030-01-31" }, { generatedAt });
  const { text, pages } = await pdfText(await renderCaneReportPdf(report));

  assert.equal(pages, 1);
  assert.match(text, /Nenhum registro encontrado para os filtros selecionados/);
  assert.match(text, /01\/01\/2030 a 31\/01\/2030/);
});
