import assert from "node:assert/strict";
import test from "node:test";
import { fitPdfSingleLine } from "./pdfTextLayout.js";

const measurer = {
  widthOfString(value: string) {
    return value.length * 5;
  }
};

test("fitPdfSingleLine keeps a PDF table cell on one measured line", () => {
  assert.equal(fitPdfSingleLine(measurer, "FAZENDA QA", 60), "FAZENDA QA");

  const fitted = fitPdfSingleLine(measurer, "FAZENDA QA MUITO LONGA", 65);
  assert.ok(measurer.widthOfString(fitted) <= 65);
  assert.ok(fitted.endsWith("..."));
  assert.equal(fitted.includes("\n"), false);
});

test("fitPdfSingleLine normalizes embedded line breaks", () => {
  assert.equal(fitPdfSingleLine(measurer, "FAZENDA\r\nQA", 80), "FAZENDA QA");
});
