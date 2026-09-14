type PdfTextMeasurer = {
  widthOfString(value: string): number;
};

export function fitPdfSingleLine(doc: PdfTextMeasurer, value: string, maxWidth: number) {
  const normalized = value.replace(/[\r\n]+/g, " ");
  if (doc.widthOfString(normalized) <= maxWidth) return normalized;

  const suffix = "...";
  if (doc.widthOfString(suffix) > maxWidth) return "";

  let low = 0;
  let high = normalized.length;
  while (low < high) {
    const middle = Math.ceil((low + high) / 2);
    const candidate = `${normalized.slice(0, middle).trimEnd()}${suffix}`;
    if (doc.widthOfString(candidate) <= maxWidth) low = middle;
    else high = middle - 1;
  }

  return `${normalized.slice(0, low).trimEnd()}${suffix}`;
}
