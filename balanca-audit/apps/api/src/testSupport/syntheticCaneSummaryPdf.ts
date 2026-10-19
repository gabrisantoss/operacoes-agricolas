import PDFDocument from "pdfkit";

// Synthetic "Resumo de Cana Entregue - Talhao" (RELPESAG) built on the column grid the importer reads.
// Every value is fictional; the footer marks the document as synthetic.
export type SyntheticCaneSummaryRow = {
  supplierCode: string;
  supplierNumber: string;
  supplierName: string;
  farmName: string;
  fieldCode: string;
  netWeight: number;
  trips: number;
};

const headerAnchors: Array<[string, number]> = [
  ["Codigo", 26.1],
  ["Fornecedor", 122.85],
  ["Fundo Agricola", 273.6],
  ["Talhao", 382.35],
  ["KM", 415.35],
  ["Area", 443.85],
  ["Cana Entregue", 478.35],
  ["Viagens", 541.35]
];
const fieldRight = 407.798;
const caneRight = 532;
const tripsRight = 574;

export function renderSyntheticCaneSummaryPdf(input: {
  periodStart: string;
  periodEnd: string;
  reportDate?: string;
  rows: SyntheticCaneSummaryRow[];
  createdAt?: Date;
}): Promise<Buffer> {
  const doc = new PDFDocument({ size: "A4", margin: 0, info: { Title: "Resumo de Cana Entregue - Talhao (sintetico)", CreationDate: input.createdAt ?? new Date("2026-10-01T12:00:00Z") } });
  const chunks: Buffer[] = [];
  const done = new Promise<Buffer>((resolve, reject) => {
    doc.on("data", (chunk: Buffer) => chunks.push(Buffer.from(chunk)));
    doc.on("end", () => resolve(Buffer.concat(chunks)));
    doc.on("error", reject);
  });
  const reportDate = input.reportDate ?? input.periodEnd;

  doc.font("Helvetica").fontSize(7).fillColor("#000000");
  doc.text("Resumo de Cana Entregue - Talhao", 26.1, 30, { lineBreak: false });
  doc.text("Operacoes Agricolas Demonstrativas", 230, 30, { lineBreak: false });
  doc.text(`Data: ${brDate(reportDate).replace(/\//g, " / ")}   08 : 00`, 440, 30, { lineBreak: false });
  doc.text(`PERIODO ${brDate(input.periodStart)} A ${brDate(input.periodEnd)} - SAFRA 2026/2027`, 26.1, 42, { lineBreak: false });
  doc.text("RELPESAG", 430, 42, { lineBreak: false });
  doc.text("Pagina:   00001", 500, 42, { lineBreak: false });
  doc.text("ORIGEM         PICADA INTEIRA", 26.1, 54, { lineBreak: false });

  const headerY = 70;
  for (const [label, x] of headerAnchors) {
    doc.text(label, x, headerY, { lineBreak: false });
  }

  let y = 86;
  for (const row of input.rows) {
    doc.text(row.supplierCode, 26.1, y, { lineBreak: false });
    doc.text(row.supplierNumber, 46, y, { lineBreak: false });
    doc.text(row.supplierName, 70, y, { lineBreak: false });
    doc.text(row.farmName, 224, y, { lineBreak: false });
    rightAligned(doc, row.fieldCode, fieldRight, y);
    rightAligned(doc, formatTons(row.netWeight), caneRight, y);
    rightAligned(doc, String(row.trips), tripsRight, y);
    y += 12;
  }

  const total = input.rows.reduce((sum, row) => sum + row.netWeight, 0);
  const trips = input.rows.reduce((sum, row) => sum + row.trips, 0);
  y += 6;
  doc.text("TOTAL GERAL", 300, y, { lineBreak: false });
  rightAligned(doc, formatTons(total), caneRight, y);
  rightAligned(doc, String(trips), tripsRight, y);
  doc.text("DOCUMENTO SINTETICO PARA DEMONSTRACAO - DADOS FICTICIOS", 26.1, 800, { lineBreak: false });
  doc.end();
  return done;
}

function rightAligned(doc: PDFKit.PDFDocument, text: string, right: number, y: number) {
  doc.text(text, right - doc.widthOfString(text), y, { lineBreak: false });
}

function brDate(value: string) {
  const [year, month, day] = value.slice(0, 10).split("-");
  return `${day}/${month}/${year}`;
}

function formatTons(value: number) {
  return new Intl.NumberFormat("pt-BR", { minimumFractionDigits: 3, maximumFractionDigits: 3 }).format(Math.round(value * 1000) / 1000);
}
