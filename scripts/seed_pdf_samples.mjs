// Synthetic standard weighing report PDFs for the overlap scenarios of the PDF import. All values are fictional and refer to the
// demonstration farms; August dates stay outside the fictional daily CSV window.
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const target = path.join(root, "demo-data", "pdf-sobreposicao");
const generator = path.join(root, "balanca-audit", "apps", "api", "dist", "testSupport", "syntheticCaneSummaryPdf.js");
const { renderSyntheticCaneSummaryPdf } = await import(pathToFileURL(generator).href);

const aurora = (fieldCode, netWeight, trips) => ({
  supplierCode: "100", supplierNumber: "901", supplierName: "ORGANIZACAO FICTICIA DEMO", farmName: "FAZENDA DEMO AURORA", fieldCode, netWeight, trips
});
const horizonte = (fieldCode, netWeight, trips) => ({
  supplierCode: "100", supplierNumber: "902", supplierName: "ORGANIZACAO FICTICIA DEMO", farmName: "FAZENDA DEMO HORIZONTE", fieldCode, netWeight, trips
});
const weekOne = [aurora("1", 310.5, 10), aurora("2", 295.25, 9), aurora("3", 301, 10), aurora("4", 288.75, 9)];

const samples = [
  ["01-resumo-01-a-07-ago.pdf", "2026-08-01", "2026-08-07", weekOne],
  ["02-resumo-01-a-07-ago-copia.pdf", "2026-08-01", "2026-08-07", weekOne],
  ["03-resumo-05-a-10-ago-mesmos-talhoes.pdf", "2026-08-05", "2026-08-10", [aurora("1", 150, 5), aurora("2", 140.5, 5)]],
  ["04-resumo-06-a-09-ago-outra-fazenda.pdf", "2026-08-06", "2026-08-09", [horizonte("1", 120, 4), horizonte("2", 118.25, 4)]],
  ["05-resumo-11-ago-conteudo-repetido.pdf", "2026-08-11", "2026-08-11", weekOne],
  ["06-resumo-01-a-07-ago-corrigido.pdf", "2026-08-01", "2026-08-07", [aurora("1", 312, 10)]],
  ["07-resumo-01-a-07-ago-outra-fazenda.pdf", "2026-08-01", "2026-08-07", [horizonte("3", 95, 3), horizonte("4", 92.5, 3)]]
];

fs.mkdirSync(target, { recursive: true });
for (const [name, periodStart, periodEnd, rows] of samples) {
  const file = path.join(target, name);
  if (fs.existsSync(file)) continue;
  // Fixed creation date: the "copia" sample must be byte-identical to the first one.
  fs.writeFileSync(file, await renderSyntheticCaneSummaryPdf({ periodStart, periodEnd, rows, createdAt: new Date("2026-08-12T12:00:00Z") }));
}
console.log(`PDFs sinteticos de sobreposicao: ${target}`);
