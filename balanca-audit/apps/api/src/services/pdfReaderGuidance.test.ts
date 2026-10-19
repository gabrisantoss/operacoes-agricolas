import assert from "node:assert/strict";
import test from "node:test";
import { pdfReaderGuidance } from "./pdfReaderGuidance.js";

test("a missing pdftotext explains how to point the application to Poppler", () => {
  const message = pdfReaderGuidance({ command: "pdftotext", missing: true, helpOutput: "" });

  assert.match(message ?? "", /nao foi encontrado/);
  assert.match(message ?? "", /POPPLER_BIN_DIR/);
  assert.match(message ?? "", /Nenhum dado foi gravado/);
});

test("an Xpdf pdftotext is identified as unable to read column positions", () => {
  const xpdfHelp = "pdftotext version 4.06 [www.xpdfreader.com]\nUsage: pdftotext [options] <PDF-file>\n  -layout : maintain original physical layout";
  const message = pdfReaderGuidance({ command: "C:\\xpdf\\pdftotext.exe", missing: false, helpOutput: xpdfHelp });

  assert.match(message ?? "", /parece ser do Xpdf/);
  assert.match(message ?? "", /-bbox-layout/);
});

test("Poppler's pdftotext needs no guidance", () => {
  const popplerHelp = "pdftotext version 25.07.0\nUsage: pdftotext [options] <PDF-file>\n  -bbox-layout : like -bbox but with extra layout bounding box data";

  assert.equal(pdfReaderGuidance({ command: "pdftotext", missing: false, helpOutput: popplerHelp }), null);
});
