import type { PdfOverlapAnalysis } from "./types";

const kindLabels: Record<PdfOverlapAnalysis["alerts"][number]["kind"], string> = {
  IDENTICAL_FILE: "Arquivo idêntico",
  SAME_PERIOD_SHARED_FIELDS: "Mesmo período com talhões em comum",
  PARTIAL_PERIOD_OVERLAP: "Período sobreposto com talhões em comum",
  PERIOD_OVERLAP_OTHER_FIELDS: "Período coincidente, outras fazendas/talhões",
  COINCIDENT_RECORDS: "Conteúdo coincidente com outro período"
};

/** True when the PDF may be saved: no blocking alert, and any ambiguous overlap was explicitly reviewed. */
export function pdfOverlapAllowsSave(overlap: PdfOverlapAnalysis | undefined, reviewed: boolean) {
  if (!overlap) return true;
  if (overlap.status === "BLOCKED") return false;
  return overlap.status !== "REVIEW_REQUIRED" || reviewed;
}

export function PdfOverlapNotice({
  overlap,
  reviewed,
  onReviewedChange
}: {
  overlap: PdfOverlapAnalysis | undefined;
  reviewed: boolean;
  onReviewedChange: (value: boolean) => void;
}) {
  if (!overlap || overlap.alerts.length === 0) return null;

  return (
    <section className={`notice pdfOverlapNotice ${overlap.status === "BLOCKED" ? "blocked" : ""}`}>
      <strong>
        {overlap.status === "BLOCKED"
          ? "Gravação bloqueada"
          : overlap.status === "REVIEW_REQUIRED"
            ? "Revisão obrigatória antes de gravar"
            : "Sobreposição informada (não impede a gravação)"}
      </strong>
      {overlap.alerts.map((alert) => (
        <div key={`${alert.kind}-${alert.batchId}`} className="pdfOverlapAlert">
          <p>
            <b>{kindLabels[alert.kind]}:</b> {alert.message}
          </p>
          {alert.fields.length > 0 ? (
            <div className="tableWrap">
              <table>
                <thead>
                  <tr>
                    <th>Fazenda</th>
                    <th>Talhão</th>
                    <th>PDF anterior ({formatPeriod(alert.existingPeriod)})</th>
                    <th>Este PDF ({formatPeriod(overlap.newPeriod)})</th>
                    <th>Período em comum</th>
                  </tr>
                </thead>
                <tbody>
                  {alert.fields.map((field) => (
                    <tr key={`${field.farmCode}-${field.fieldCode}`}>
                      <td>
                        {field.farmCode} - {field.farmName}
                      </td>
                      <td>{field.fieldCode}</td>
                      <td>
                        {formatTons(field.existingNetWeight)} t · {field.existingEntries} viagem(ns)
                      </td>
                      <td>
                        {formatTons(field.newNetWeight)} t · {field.newEntries} viagem(ns)
                        {field.sameTotals ? " (idêntico)" : ""}
                      </td>
                      <td>{alert.overlapPeriod ? formatPeriod(alert.overlapPeriod) : "-"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : null}
        </div>
      ))}
      {overlap.status === "REVIEW_REQUIRED" ? (
        <label className="pdfOverlapReview">
          <input type="checkbox" checked={reviewed} onChange={(event) => onReviewedChange(event.target.checked)} />
          Conferi os talhões e períodos acima e confirmo que este PDF traz entregas que ainda não foram lançadas. A revisão
          reduz, mas não elimina, o risco de contagem duplicada; se for o mesmo conteúdo, exclua o lote anterior no Histórico
          em vez de gravar.
        </label>
      ) : null}
    </section>
  );
}

function formatPeriod(period: { start: string; end: string }) {
  const format = (value: string) => {
    const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(value);
    return match ? `${match[3]}/${match[2]}/${match[1]}` : value;
  };
  return period.start === period.end ? format(period.start) : `${format(period.start)} a ${format(period.end)}`;
}

function formatTons(value: number) {
  return new Intl.NumberFormat("pt-BR", { minimumFractionDigits: 3, maximumFractionDigits: 3 }).format(value);
}
