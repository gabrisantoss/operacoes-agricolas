import zlib from "node:zlib";

// Reads the text PDFKit writes with its standard fonts (hex strings in TJ arrays inside Flate streams).
// Used instead of pdf-parse, whose bundled pdf.js 1.10 intermittently rejects valid files.
export function extractPdfText(buffer: Buffer) {
  const raw = buffer.toString("latin1");
  const pages = (raw.match(/\/Type \/Page\b(?!s)/g) ?? []).length;
  const parts: string[] = [];
  const streamPattern = /\/Length (\d+)\s*\/Filter \/FlateDecode\s*>>\s*stream\r?\n/g;

  for (const match of raw.matchAll(streamPattern)) {
    const start = match.index! + match[0].length;
    const content = zlib.inflateSync(buffer.subarray(start, start + Number(match[1]))).toString("latin1");

    for (const array of content.matchAll(/\[((?:<[0-9a-fA-F]*>|[^\]])*)\]\s*TJ/g)) {
      parts.push([...array[1]!.matchAll(/<([0-9a-fA-F]*)>/g)].map((hex) => Buffer.from(hex[1]!, "hex").toString("latin1")).join(""));
    }
  }

  // Wrapped lines become separate text runs; collapse the joints so labels read as one phrase.
  return { text: parts.join(" ").replace(/\s+/g, " "), pages };
}
