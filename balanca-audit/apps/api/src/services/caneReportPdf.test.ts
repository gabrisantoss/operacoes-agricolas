import assert from "node:assert/strict";
import test from "node:test";
import type { CaneReportSourceRow } from "../db.js";
import { buildCaneReport } from "./caneReport.js";
import { extractPdfText } from "../testSupport/pdfText.js";
import { formatTons, renderCaneReportPdf } from "./caneReportPdf.js";

// Fixed generation time keeps the PDF bytes deterministic.
const generatedAt = new Date("2026-10-18T12:00:00.000Z");

// Even fields belong to a closed order with all their entries in the report; odd fields to an active order.
function sourceRows(fieldCount: number, closedEvery = 2): CaneReportSourceRow[] {
  return Array.from({ length: fieldCount }, (_, index) => {
    const closed = index % closedEvery === 0;
    return {
      farmId: index % 2 === 0 ? "farm-a" : "farm-b",
      farmCode: index % 2 === 0 ? "100-901" : "100-902",
      farmName: index % 2 === 0 ? "FAZENDA DEMO AURORA" : "FAZENDA DEMO HORIZONTE",
      fieldId: `field-${index}`,
      fieldCode: String(index + 1),
      fieldName: null,
      areaHa: 4.84,
      areaAlq: 2,
      referenceDate: `2026-09-${String((index % 28) + 1).padStart(2, "0")}`,
      orderId: closed ? "os-closed" : "os-active",
      orderNumber: closed ? "90007" : "90001",
      closedOrderEndDate: closed ? "2026-09-30" : null,
      closedOrderEntryCount: closed ? 2 : null,
      entryCount: 2,
      okCount: 2,
      divergentCount: 0,
      totalNetWeight: 63.25,
      divergentNetWeight: 0
    };
  });
}

async function pdfText(buffer: Buffer) {
  return extractPdfText(buffer);
}

test("general PDF prints the same totals as the preview model", async () => {
  const report = buildCaneReport(sourceRows(6, 1), { type: "GENERAL" }, { generatedAt });
  const buffer = await renderCaneReportPdf(report);
  const { text } = await pdfText(buffer);

  assert.equal(buffer.subarray(0, 4).toString(), "%PDF");
  assert.match(text, /Relatório geral de safra/);
  assert.ok(text.includes(formatTons(report.totals.totalNetWeight)), "total de cana do PDF difere da prévia");
  assert.equal(formatTons(report.totals.totalNetWeight), "379,500");
  assert.match(text, /TCH talhões encerrados \(t\/ha\)/);
  assert.doesNotMatch(text, /TCH talhões encerrados, parcial/);
  assert.match(text, /Área cadastrada \(ha\)/);
  assert.match(text, /Área dos talhões encerrados \(ha\)/);
  assert.match(text, /Entregas por dia/);
});

test("partial evidence is labeled as partial with its basis", async () => {
  // Field 3 belongs to the closed order but only part of its stored entries is in the report.
  const rows = sourceRows(4).map((row, index) => (index === 2 ? { ...row, closedOrderEntryCount: 5 } : row));
  const report = buildCaneReport(rows, { type: "DETAILED" }, { generatedAt });
  const { text } = await pdfText(await renderCaneReportPdf(report));

  assert.match(text, /TCH talhões encerrados, parcial \(t\/ha\)/);
  assert.match(text, /1 de 4 talhões/);
  assert.match(text, /TCH talhões encerrados parcial: calculado só com 1 de 4 talhões/);
  assert.match(text, /OS 90007 encerrada fora do recorte/);
  assert.doesNotMatch(text, /\.\.\./, "nenhum texto de tabela pode ser truncado");
  assert.match(text, /Situação da colheita/);
  assert.match(text, /OS 90007 encerrada/);
  assert.match(text, /Sem OS encerrada/);
  assert.match(text, /Área cad\. \(ha\)/);
  assert.match(text, /Área encerr\. \(ha\)/);
  assert.doesNotMatch(text, /Área colh|comprovad|efetivo/);
});

test("PDF prints N/D when no field has a closed order in the report", async () => {
  const report = buildCaneReport(sourceRows(3, 99).slice(1), { type: "DETAILED" }, { generatedAt });
  const { text } = await pdfText(await renderCaneReportPdf(report));

  assert.equal(report.totals.closedFieldsTch, null);
  assert.match(text, /N\/D/);
  assert.match(text, /TCH talhões encerrados N\/D: nenhum dos 2 talhão\(ões\) tem OS encerrada com todas as entregas no recorte/);
  assert.ok(text.includes(formatTons(report.totals.totalNetWeight)));
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
