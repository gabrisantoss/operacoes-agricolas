import assert from "node:assert/strict";
import test from "node:test";
import type { PostHarvestExportData } from "./postHarvestExcelExport.js";
import { renderPostHarvestExportPdf } from "./postHarvestPdfExport.js";

test("post-harvest PDF repeats farm context and table header on continuation pages", () => {
  const data = makeExportData(34);
  const pdf = new RecordingPdfDocument();
  renderPostHarvestExportPdf(pdf.asPdfDocument(), data);

  assert.equal(pdf.pages.length, 3);
  assert.equal(pdf.countText("Fazenda: FAZENDA QA"), 2);
  assert.equal(pdf.countText("Área (alq)"), 2);
  assert.ok(pdf.pages[2].includes("Fazenda: FAZENDA QA - continuação"));
});

class RecordingPdfDocument {
  readonly page = { width: 842, height: 595 };
  readonly pages: string[][] = [[]];

  asPdfDocument() {
    return this as unknown as PDFKit.PDFDocument;
  }

  addPage() {
    this.pages.push([]);
    return this;
  }

  text(value: string) {
    this.pages.at(-1)?.push(value);
    return this;
  }

  countText(needle: string) {
    return this.pages.flat().filter((value) => value.includes(needle)).length;
  }

  rect() { return this; }
  fill() { return this; }
  stroke() { return this; }
  fillColor() { return this; }
  fontSize() { return this; }
  font() { return this; }
  moveDown() { return this; }
  strokeColor() { return this; }
  moveTo() { return this; }
  lineTo() { return this; }
}

function makeExportData(rowCount: number): PostHarvestExportData {
  const rows = Array.from({ length: rowCount }, (_, index) => ({
    idTalhao: `1001${String(index + 1).padStart(4, "0")}`,
    dataInicio: new Date("2026-01-01T12:00:00Z"),
    dataFechamento: new Date("2026-01-31T12:00:00Z"),
    setor: "10",
    codigo: "1001",
    fundoAgricola: "FAZENDA QA",
    talhao: String(index + 1).padStart(4, "0"),
    areaAlq: 1,
    areaHa: 2.42,
    caneTons: 100,
    tch: 100 / 2.42,
    tca: 100,
    orderId: "order-qa-1",
    orderNumber: "OS-QA-001"
  }));

  return {
    rows,
    issues: [],
    summary: {
      closedOrders: 1,
      rowCount,
      invalidCount: 0
    }
  };
}
