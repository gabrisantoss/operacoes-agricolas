import assert from "node:assert/strict";
import test from "node:test";
import { analyzePdfImportOverlap, summarizePdfFields, type ImportedPdfBatch, type PdfFieldTotal } from "./pdfImportOverlap.js";

const field = (fieldCode: string, netWeight: number, entryCount: number, farmCode = "100-901"): PdfFieldTotal => ({
  farmCode,
  farmName: farmCode === "100-901" ? "FAZENDA DEMO AURORA" : "FAZENDA DEMO HORIZONTE",
  fieldCode,
  netWeight,
  entryCount
});

const weekOne: ImportedPdfBatch = {
  id: "batch-1",
  fileName: "resumo-01-a-07.pdf",
  importedAt: "2026-09-08T10:00:00.000Z",
  periodStart: "2026-09-01",
  periodEnd: "2026-09-07",
  fields: [field("1", 310.5, 10), field("2", 295.25, 9), field("3", 301, 10), field("4", 288.75, 9)]
};

function analyze(periodStart: string, periodEnd: string, fields: PdfFieldTotal[], extra: Partial<Parameters<typeof analyzePdfImportOverlap>[0]> = {}) {
  return analyzePdfImportOverlap({ fileHash: "f".repeat(64), periodStart, periodEnd, fields, identicalFile: null, importedBatches: [weekOne], ...extra });
}

test("a new period without shared fields or repeated content is a legitimate import", () => {
  const result = analyze("2026-09-08", "2026-09-14", [field("1", 320, 11), field("2", 280, 9)]);

  assert.equal(result.status, "NONE");
  assert.deepEqual(result.alerts, []);
  assert.equal(result.reviewToken, null);
});

test("the identical file is blocked before anything else", () => {
  const result = analyze("2026-09-01", "2026-09-07", weekOne.fields, {
    identicalFile: { id: "batch-1", fileName: weekOne.fileName, importedAt: weekOne.importedAt, periodStart: "2026-09-01", periodEnd: "2026-09-07" }
  });

  assert.equal(result.status, "BLOCKED");
  assert.deepEqual(result.alerts.map((alert) => alert.kind), ["IDENTICAL_FILE"]);
});

test("another PDF for exactly the same period keeps the existing block and lists the fields", () => {
  const result = analyze("2026-09-01", "2026-09-07", [field("1", 300, 10)]);

  assert.equal(result.status, "BLOCKED");
  assert.equal(result.alerts[0]!.kind, "SAME_PERIOD");
  assert.match(result.alerts[0]!.message, /Exclua o grupo existente/);
  assert.equal(result.alerts[0]!.fields[0]!.fieldCode, "1");
});

test("a partially overlapping period with shared fields requires review and shows farm, field and period", () => {
  const result = analyze("2026-09-05", "2026-09-10", [field("01", 150, 5), field("2", 140.5, 5), field("1", 90, 3, "100-902")]);
  const alert = result.alerts[0]!;

  assert.equal(result.status, "REVIEW_REQUIRED");
  assert.equal(alert.kind, "PARTIAL_PERIOD_OVERLAP");
  assert.deepEqual(alert.overlapPeriod, { start: "2026-09-05", end: "2026-09-07" });
  assert.deepEqual(alert.fields.map((item) => [item.farmName, item.fieldCode, item.existingNetWeight, item.newNetWeight]), [
    ["FAZENDA DEMO AURORA", "01", 310.5, 150],
    ["FAZENDA DEMO AURORA", "2", 295.25, 140.5]
  ]);
  assert.match(alert.message, /05\/09\/2026 a 07\/09\/2026/);
  assert.match(result.reviewToken ?? "", /^[a-f0-9]{64}$/);
});

test("an overlapping period with no shared field is only informed", () => {
  const result = analyze("2026-09-05", "2026-09-10", [field("1", 90, 3, "100-902"), field("2", 80, 3, "100-902")]);

  assert.equal(result.status, "INFO");
  assert.equal(result.alerts[0]!.kind, "PERIOD_OVERLAP_OTHER_FIELDS");
  assert.equal(result.reviewToken, null);
});

test("the same content under a different period requires review", () => {
  const result = analyze("2026-09-11", "2026-09-11", weekOne.fields.map((item) => ({ ...item })));

  assert.equal(result.status, "REVIEW_REQUIRED");
  assert.equal(result.alerts[0]!.kind, "COINCIDENT_RECORDS");
  assert.equal(result.alerts[0]!.fields.length, 4);
  assert.match(result.alerts[0]!.message, /4 de 4 talhao/);
});

test("a few coincident field totals in another period are not treated as duplication", () => {
  const result = analyze("2026-09-11", "2026-09-17", [field("1", 310.5, 10), field("2", 200, 7), field("3", 210, 7), field("4", 190, 6)]);

  assert.equal(result.status, "NONE");
});

test("the review token changes when the stored batches change", () => {
  const fields = [field("1", 150, 5)];
  const first = analyze("2026-09-05", "2026-09-10", fields);
  const second = analyze("2026-09-05", "2026-09-10", fields, {
    importedBatches: [weekOne, { ...weekOne, id: "batch-2", periodStart: "2026-09-06", periodEnd: "2026-09-12" }]
  });

  assert.notEqual(first.reviewToken, second.reviewToken);
});

test("field totals sum the unrolled trips of each field", () => {
  assert.deepEqual(
    summarizePdfFields([
      { farmCodeRaw: "100-901", farmRaw: "FAZENDA DEMO AURORA", fieldRaw: "1", netWeight: 30.5 },
      { farmCodeRaw: "100-901", farmRaw: "FAZENDA DEMO AURORA", fieldRaw: "1", netWeight: 30.25 },
      { farmCodeRaw: "100-901", farmRaw: "FAZENDA DEMO AURORA", fieldRaw: "2", netWeight: 28 }
    ]),
    [
      { farmCode: "100-901", farmName: "FAZENDA DEMO AURORA", fieldCode: "1", netWeight: 60.75, entryCount: 2 },
      { farmCode: "100-901", farmName: "FAZENDA DEMO AURORA", fieldCode: "2", netWeight: 28, entryCount: 1 }
    ]
  );
});
