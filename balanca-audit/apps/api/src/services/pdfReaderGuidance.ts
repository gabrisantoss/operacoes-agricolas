// The positioned reading needs Poppler's pdftotext. Another binary with the same name (e.g. Xpdf) has no
// -bbox-layout; the user gets the cause and how to point the application to Poppler, nothing is saved.
export function pdfReaderGuidance(input: { command: string; missing: boolean; helpOutput: string }) {
  const configure =
    "Instale o Poppler (poppler-utils) e coloque a pasta bin dele antes no PATH ao iniciar a aplicacao, ou defina POPPLER_BIN_DIR (ou PDFTOTEXT_CMD) apontando para o Poppler. Nenhum dado foi gravado.";
  if (input.missing) {
    return `Leitura de PDF indisponivel: o programa pdftotext nao foi encontrado (${input.command}). ${configure}`;
  }
  if (!/-bbox-layout/.test(input.helpOutput)) {
    const origin = /xpdf/i.test(input.helpOutput) ? " (parece ser do Xpdf)" : "";
    return `Leitura de PDF indisponivel: o pdftotext encontrado (${input.command})${origin} nao e do Poppler e nao le as posicoes das colunas (-bbox-layout). ${configure}`;
  }
  return null;
}
