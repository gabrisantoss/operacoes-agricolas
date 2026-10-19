import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test, { after, before } from "node:test";
import { createPostgresTestDatabase } from "../testSupport/postgresTestDatabase.js";
import { renderSyntheticCaneSummaryPdf, type SyntheticCaneSummaryRow } from "../testSupport/syntheticCaneSummaryPdf.js";

process.env.NODE_ENV = "test";
const popplerDir = process.env.POPPLER_BIN_DIR?.trim();
if (popplerDir) {
  process.env.PATH = `${popplerDir}${path.delimiter}${process.env.PATH ?? ""}`;
}
const testDatabaseUrl = process.env.BALANCA_TEST_DATABASE_URL?.trim();

// The PDF reader needs Poppler's pdftotext (-bbox-layout); Xpdf's binary of the same name does not support it.
function hasPopplerPdftotext() {
  const result = spawnSync("pdftotext", ["-h"], { encoding: "utf8" });
  return /-bbox-layout/.test(`${result.stdout ?? ""}${result.stderr ?? ""}`);
}

if (!testDatabaseUrl || !hasPopplerPdftotext()) {
  test.skip("PDF overlap integration tests require BALANCA_TEST_DATABASE_URL and Poppler pdftotext", () => {});
} else {
  const testDatabase = await createPostgresTestDatabase();
  const { createFarm, db } = await import("../db.js");
  const { commitImport, previewImport } = await import("./importer.js");
  const folder = await fs.mkdtemp(path.join(os.tmpdir(), "pdf-overlap-"));

  const aurora = (fieldCode: string, netWeight: number, trips: number): SyntheticCaneSummaryRow => ({
    supplierCode: "100", supplierNumber: "971", supplierName: "ORGANIZACAO FICTICIA DEMO", farmName: "FAZENDA SINTETICA AURORA", fieldCode, netWeight, trips
  });
  const horizonte = (fieldCode: string, netWeight: number, trips: number): SyntheticCaneSummaryRow => ({
    supplierCode: "100", supplierNumber: "972", supplierName: "ORGANIZACAO FICTICIA DEMO", farmName: "FAZENDA SINTETICA HORIZONTE", fieldCode, netWeight, trips
  });
  const weekOneRows = [aurora("1", 310.5, 10), aurora("2", 295.25, 9), aurora("3", 301, 10), aurora("4", 288.75, 9)];

  async function writePdf(name: string, periodStart: string, periodEnd: string, rows: SyntheticCaneSummaryRow[]) {
    const filePath = path.join(folder, name);
    await fs.writeFile(filePath, await renderSyntheticCaneSummaryPdf({ periodStart, periodEnd, rows }));
    return filePath;
  }

  async function importPdf(filePath: string, name: string, overlapReviewToken?: string) {
    const preview = await previewImport(filePath, name);
    return commitImport(filePath, name, undefined, { expectedFileHash: preview.fileHash, overlapReviewToken });
  }

  const countEntries = () => Number((db.prepare("SELECT COUNT(*) AS count FROM cane_entries").get() as { count: number | string }).count);

  before(async () => {
    createFarm({ code: "100-971", name: "FAZENDA SINTETICA AURORA", fields: ["1", "2", "3", "4"] });
    createFarm({ code: "100-972", name: "FAZENDA SINTETICA HORIZONTE", fields: ["1", "2"] });
    await importPdf(await writePdf("semana-1.pdf", "2026-09-01", "2026-09-07", weekOneRows), "semana-1.pdf");
  });

  after(async () => {
    await fs.rm(folder, { recursive: true, force: true });
    await Promise.resolve(db.close?.());
    await testDatabase.cleanup();
  });

  test("the first synthetic PDF is read, reconciled and saved without alerts", () => {
    assert.equal(countEntries(), 38);
  });

  test("the same file is identified in the preview and refused on save", async () => {
    const copy = path.join(folder, "semana-1-copia.pdf");
    await fs.copyFile(path.join(folder, "semana-1.pdf"), copy);
    const preview = await previewImport(copy, "semana-1-copia.pdf");

    assert.equal(preview.overlap?.status, "BLOCKED");
    assert.equal(preview.overlap?.alerts[0]?.kind, "IDENTICAL_FILE");
    await assert.rejects(() => commitImport(copy, "semana-1-copia.pdf", undefined, { expectedFileHash: preview.fileHash }), /ja foi lancado/);
    assert.equal(countEntries(), 38);
  });

  test("another PDF for the same period stays blocked and shows the fields", async () => {
    const file = await writePdf("semana-1-corrigida.pdf", "2026-09-01", "2026-09-07", [aurora("1", 312, 10)]);
    const preview = await previewImport(file, "semana-1-corrigida.pdf");

    assert.equal(preview.overlap?.alerts[0]?.kind, "SAME_PERIOD");
    assert.deepEqual(preview.overlap?.alerts[0]?.fields.map((field) => [field.farmName, field.fieldCode]), [["FAZENDA SINTETICA AURORA", "1"]]);
    await assert.rejects(() => commitImport(file, "semana-1-corrigida.pdf", undefined, { expectedFileHash: preview.fileHash }), /Exclua o grupo existente/);
  });

  test("a partially overlapping PDF with shared fields is saved only after explicit review", async () => {
    const file = await writePdf("05-a-10.pdf", "2026-09-05", "2026-09-10", [aurora("1", 150, 5), aurora("2", 140.5, 5)]);
    const preview = await previewImport(file, "05-a-10.pdf");
    const alert = preview.overlap!.alerts[0]!;

    assert.equal(preview.overlap?.status, "REVIEW_REQUIRED");
    assert.equal(alert.kind, "PARTIAL_PERIOD_OVERLAP");
    assert.deepEqual(alert.overlapPeriod, { start: "2026-09-05", end: "2026-09-07" });
    assert.equal(alert.fileName, "semana-1.pdf");

    await assert.rejects(() => commitImport(file, "05-a-10.pdf", undefined, { expectedFileHash: preview.fileHash }), /exige revisao explicita/);
    await assert.rejects(
      () => commitImport(file, "05-a-10.pdf", undefined, { expectedFileHash: preview.fileHash, overlapReviewToken: "0".repeat(64) }),
      /exige revisao explicita/
    );
    assert.equal(countEntries(), 38);

    await commitImport(file, "05-a-10.pdf", undefined, { expectedFileHash: preview.fileHash, overlapReviewToken: preview.overlap!.reviewToken! });
    assert.equal(countEntries(), 48);
    const noted = db.prepare("SELECT COUNT(*) AS count FROM cane_entries WHERE notes LIKE '%Sobreposicao revisada%semana-1.pdf%'").get() as { count: number | string };
    assert.equal(Number(noted.count), 10);
  });

  test("an overlapping period for other fields is a legitimate import", async () => {
    // Overlaps both previous PDFs (01-07 and 05-10) without being the same period and without shared fields.
    const file = await writePdf("horizonte-06-a-09.pdf", "2026-09-06", "2026-09-09", [horizonte("1", 120, 4), horizonte("2", 118.25, 4)]);
    const preview = await previewImport(file, "horizonte-06-a-09.pdf");

    assert.equal(preview.overlap?.status, "INFO");
    assert.equal(preview.overlap?.alerts.length, 2);
    assert.ok(preview.overlap?.alerts.every((alert) => alert.kind === "PERIOD_OVERLAP_OTHER_FIELDS"));
    await commitImport(file, "horizonte-06-a-09.pdf", undefined, { expectedFileHash: preview.fileHash });
    assert.equal(countEntries(), 56);
  });

  test("the same content under another period requires review", async () => {
    const file = await writePdf("dia-11.pdf", "2026-09-11", "2026-09-11", weekOneRows);
    const preview = await previewImport(file, "dia-11.pdf");

    assert.equal(preview.overlap?.status, "REVIEW_REQUIRED");
    assert.equal(preview.overlap?.alerts[0]?.kind, "COINCIDENT_RECORDS");
    await assert.rejects(() => commitImport(file, "dia-11.pdf", undefined, { expectedFileHash: preview.fileHash }), /exige revisao explicita/);
  });
}
