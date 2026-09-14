import assert from "node:assert/strict";
import test from "node:test";
import type { ApportionmentResult } from "./apportionment.js";
import { renderAllApportionmentsPdf, renderSingleApportionmentPdf } from "./apportionmentPdfExport.js";

test("apportionment PDFs repeat order context and table header on continuation pages", () => {
  const result = makeResult(34);
  const allPdf = new RecordingPdfDocument();
  renderAllApportionmentsPdf(allPdf.asPdfDocument(), [result], 1, new Date("2026-08-31T12:00:00Z"));

  assert.equal(allPdf.pages.length, 3);
  assert.equal(allPdf.countText("OS OS-QA-001"), 2);
  assert.equal(allPdf.countText("Faz./Talhão"), 2);
  assert.equal(allPdf.countText("Total de OS Fechadas: 1"), 1);
  assert.ok(allPdf.pages[2].includes("OS OS-QA-001 - continuação"));

  const singlePdf = new RecordingPdfDocument();
  renderSingleApportionmentPdf(singlePdf.asPdfDocument(), result);

  assert.equal(singlePdf.pages.length, 2);
  assert.equal(singlePdf.countText("Rateio OS OS-QA-001"), 2);
  assert.equal(singlePdf.countText("Faz./Talhão"), 2);
  assert.ok(singlePdf.pages[1].includes("Rateio OS OS-QA-001 - continuação"));
});

class RecordingPdfDocument {
  readonly page = { width: 595, height: 842 };
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
  fillColor() { return this; }
  fontSize() { return this; }
  font() { return this; }
  moveTo() { return this; }
  lineTo() { return this; }
  stroke() { return this; }
}

function makeResult(fieldCount: number): ApportionmentResult {
  const fields = Array.from({ length: fieldCount }, (_, index) => ({
    fieldId: `field-${index + 1}`,
    fieldCode: String(index + 1),
    farmId: "farm-1",
    farmCode: "101-0001",
    farmName: "FAZENDA QA",
    areaHa: 1,
    percentage: 1 / fieldCount,
    farmPercentage: 1 / fieldCount,
    proratedWeight: 100,
    harvested: true
  }));
  return {
    orderId: "order-1",
    orderNumber: "OS-QA-001",
    farmName: "FAZENDA QA",
    farmCode: "101-0001",
    weightUnit: "t",
    totalAreaHa: fieldCount,
    totalWeight: fieldCount * 100,
    allocatedWeight: fieldCount * 100,
    unassignedWeight: 0,
    farms: [{
      farmId: "farm-1",
      farmCode: "101-0001",
      farmName: "FAZENDA QA",
      totalAreaHa: fieldCount,
      totalWeight: fieldCount * 100,
      fields
    }],
    fields
  };
}
