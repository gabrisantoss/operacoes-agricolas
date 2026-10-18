import { useEffect, useMemo, useRef, useState } from "react";
import type { FormEvent } from "react";
import { Download, Eye } from "lucide-react";
import type { CaneReportType } from "@balanca/shared";
import { apiRequest, downloadFile, queryString } from "./api";

type ReportFilters = {
  type: CaneReportType;
  farmId: string;
  fieldId: string;
  from: string;
  to: string;
};

type ReportOptions = {
  farms: Array<{ id: string; code: string | null; name: string; fields: Array<{ id: string; code: string; name: string | null }> }>;
};

type FarmRow = {
  key: string;
  farmCode: string | null;
  farmName: string;
  fieldCount: number;
  entryCount: number;
  divergentCount: number;
  totalNetWeight: number;
  shareOfTotal: number;
  registeredAreaHa: number;
  provenAreaHa: number;
  provenFieldCount: number;
  provenNetWeight: number;
  effectiveTch: number | null;
  firstDate: string | null;
  lastDate: string | null;
};

type CaneReport = {
  type: CaneReportType;
  title: string;
  filterLabels: { farm: string; field: string; period: string };
  isEmpty: boolean;
  notes: string[];
  totals: {
    farmCount: number;
    fieldCount: number;
    entryCount: number;
    divergentCount: number;
    totalNetWeight: number;
    divergentNetWeight: number;
    averageNetWeightPerEntry: number | null;
    deliveryDays: number;
    firstDate: string | null;
    lastDate: string | null;
    registeredAreaHa: number;
    provenAreaHa: number;
    provenFieldCount: number;
    provenNetWeight: number;
    effectiveTch: number | null;
  };
  farms: FarmRow[];
  fields: Array<{
    key: string;
    farmKey: string;
    fieldCode: string;
    fieldName: string | null;
    registeredAreaHa: number | null;
    entryCount: number;
    divergentCount: number;
    totalNetWeight: number;
    averageNetWeightPerEntry: number | null;
    evidenceLabel: string;
    effectiveTch: number | null;
    deliveryDays: number;
    firstDate: string | null;
    lastDate: string | null;
  }>;
  days: Array<{ date: string; entryCount: number; fieldCount: number; totalNetWeight: number; divergentNetWeight: number }>;
};

const emptyFilters: ReportFilters = { type: "GENERAL", farmId: "", fieldId: "", from: "", to: "" };

export function CaneReportsView({ token, setMessage }: { token: string; setMessage: (message: string | null) => void }) {
  const [options, setOptions] = useState<ReportOptions | null>(null);
  const [draft, setDraft] = useState<ReportFilters>(emptyFilters);
  const [applied, setApplied] = useState<ReportFilters | null>(null);
  const [report, setReport] = useState<CaneReport | null>(null);
  const [loading, setLoading] = useState(false);
  const [exporting, setExporting] = useState(false);
  const requestIdRef = useRef(0);

  const fieldOptions = useMemo(
    () => options?.farms.find((farm) => farm.id === draft.farmId)?.fields ?? [],
    [options, draft.farmId]
  );

  useEffect(() => {
    apiRequest<ReportOptions>("/reports/cane/options", token)
      .then(setOptions)
      .catch((error) => setMessage(error instanceof Error ? error.message : "Falha ao carregar fazendas."));
    void loadPreview(emptyFilters);
  }, [token]);

  async function loadPreview(filters: ReportFilters) {
    const requestId = ++requestIdRef.current;
    setLoading(true);
    setMessage(null);

    try {
      const payload = await apiRequest<CaneReport>(`/reports/cane/preview${reportQuery(filters)}`, token);
      if (requestId === requestIdRef.current) {
        setReport(payload);
        setApplied(filters);
      }
    } catch (error) {
      if (requestId === requestIdRef.current) {
        setMessage(error instanceof Error ? error.message : "Falha ao gerar a prévia.");
      }
    } finally {
      if (requestId === requestIdRef.current) {
        setLoading(false);
      }
    }
  }

  async function exportPdf() {
    if (!applied) return;
    setExporting(true);
    setMessage(null);

    try {
      await downloadFile(
        `/reports/cane.pdf${reportQuery(applied)}`,
        token,
        applied.type === "DETAILED" ? "relatorio-safra-detalhado.pdf" : "relatorio-safra-geral.pdf"
      );
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Falha ao exportar o PDF.");
    } finally {
      setExporting(false);
    }
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    void loadPreview(draft);
  }

  const outdated = applied !== null && JSON.stringify(applied) !== JSON.stringify(draft);

  return (
    <div className="stack caneReportsView">
      <section className="panel dashboardFiltersPanel">
        <div className="dashboardSectionHeader">
          <div>
            <h2>Central de relatórios</h2>
            <span className="muted">Escolha o relatório e os filtros. A prévia e o PDF usam o mesmo cálculo.</span>
          </div>
        </div>
        <form className="filterGrid" onSubmit={submit}>
          <label>
            Relatório
            <select
              value={draft.type}
              onChange={(event) => setDraft((current) => ({ ...current, type: event.target.value as CaneReportType }))}
            >
              <option value="GENERAL">Geral de safra</option>
              <option value="DETAILED">Detalhado por talhão</option>
            </select>
          </label>
          <label>
            Fazenda
            <select
              value={draft.farmId}
              onChange={(event) => setDraft((current) => ({ ...current, farmId: event.target.value, fieldId: "" }))}
            >
              <option value="">Todas</option>
              {(options?.farms ?? []).map((farm) => (
                <option key={farm.id} value={farm.id}>
                  {farm.code ? `${farm.code} - ` : ""}
                  {farm.name}
                </option>
              ))}
            </select>
          </label>
          <label>
            Talhão
            <select
              value={draft.fieldId}
              disabled={!draft.farmId}
              onChange={(event) => setDraft((current) => ({ ...current, fieldId: event.target.value }))}
            >
              <option value="">{draft.farmId ? "Todos" : "Escolha a fazenda"}</option>
              {fieldOptions.map((field) => (
                <option key={field.id} value={field.id}>
                  {field.code}
                  {field.name ? ` - ${field.name}` : ""}
                </option>
              ))}
            </select>
          </label>
          <label>
            De
            <input type="date" value={draft.from} max={draft.to || undefined} onChange={(event) => setDraft((current) => ({ ...current, from: event.target.value }))} />
          </label>
          <label>
            Até
            <input type="date" value={draft.to} min={draft.from || undefined} onChange={(event) => setDraft((current) => ({ ...current, to: event.target.value }))} />
          </label>
          <div className="filterActions">
            <button className="secondaryButton" type="submit" disabled={loading}>
              <Eye size={18} />
              {loading ? "Gerando" : "Gerar prévia"}
            </button>
            <button className="secondaryButton" type="button" onClick={() => setDraft(emptyFilters)}>
              Limpar
            </button>
            <button className="primaryButton" type="button" onClick={exportPdf} disabled={!report || outdated || exporting}>
              <Download size={18} />
              {exporting ? "Exportando" : "Exportar PDF"}
            </button>
          </div>
        </form>
        {outdated ? <span className="muted">Filtros alterados: gere a prévia novamente antes de exportar.</span> : null}
      </section>

      {!report ? <div className="emptyState">{loading ? "Gerando prévia..." : "Gere a prévia para ver os resultados."}</div> : null}

      {report ? (
        <section className="panel caneReportPreview">
          <div className="sectionHeader">
            <div>
              <h2>{report.title}</h2>
              <span className="muted">
                Fazenda: {report.filterLabels.farm} · Talhão: {report.filterLabels.field} · Período: {report.filterLabels.period}
              </span>
            </div>
          </div>

          {report.isEmpty ? (
            <div className="emptyState">Nenhum registro encontrado para os filtros selecionados.</div>
          ) : (
            <>
              <section className="metricsGrid">
                <ReportMetric label="Cana entregue (t)" value={formatTons(report.totals.totalNetWeight)} />
                <ReportMetric label="Cargas" value={formatInteger(report.totals.entryCount)} />
                <ReportMetric label="Média por carga (t)" value={formatTons(report.totals.averageNetWeightPerEntry)} />
                <ReportMetric label="Fazendas / talhões" value={`${report.totals.farmCount} / ${report.totals.fieldCount}`} />
                <ReportMetric label="Dias com entrega" value={formatInteger(report.totals.deliveryDays)} />
                <ReportMetric label="Área cadastrada (ha)" value={formatDecimal(report.totals.registeredAreaHa)} />
                <ReportMetric label="Área colhida comprovada (ha)" value={formatDecimal(report.totals.provenAreaHa)} caption={provenBasis(report)} />
                <ReportMetric label={effectiveTchLabel(report)} value={formatIndicator(report.totals.effectiveTch)} caption={provenBasis(report)} />
                <ReportMetric label="Cargas divergentes" value={formatInteger(report.totals.divergentCount)} />
              </section>
              {report.notes.map((note) => (
                <p className="muted" key={note}>
                  {note}
                </p>
              ))}

              {report.type === "DETAILED" ? <DetailedTables report={report} /> : <GeneralTables report={report} />}
            </>
          )}
        </section>
      ) : null}
    </div>
  );
}

function GeneralTables({ report }: { report: CaneReport }) {
  return (
    <>
      <h3>Cana entregue por fazenda</h3>
      <FarmTable report={report} />
      <h3>Entregas por dia</h3>
      <div className="tableWrap">
        <table>
          <thead>
            <tr>
              <th>Data</th>
              <th>Cargas</th>
              <th>Talhões com entrega</th>
              <th>Cana entregue (t)</th>
              <th>Cana em cargas divergentes (t)</th>
            </tr>
          </thead>
          <tbody>
            {report.days.map((day) => (
              <tr key={day.date}>
                <td>{formatDate(day.date)}</td>
                <td>{formatInteger(day.entryCount)}</td>
                <td>{formatInteger(day.fieldCount)}</td>
                <td>{formatTons(day.totalNetWeight)}</td>
                <td>{formatTons(day.divergentNetWeight)}</td>
              </tr>
            ))}
            <tr className="totalRow">
              <td>Total</td>
              <td>{formatInteger(report.totals.entryCount)}</td>
              <td>{formatInteger(report.totals.fieldCount)}</td>
              <td>{formatTons(report.totals.totalNetWeight)}</td>
              <td>{formatTons(report.totals.divergentNetWeight)}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </>
  );
}

function DetailedTables({ report }: { report: CaneReport }) {
  return (
    <>
      {report.farms.map((farm) => (
        <div key={farm.key}>
          <h3>
            {farm.farmCode ? `${farm.farmCode} - ` : ""}
            {farm.farmName}
          </h3>
          <div className="tableWrap">
            <table>
              <thead>
                <tr>
                  <th>Talhão</th>
                  <th>Nome</th>
                  <th>Área cad. (ha)</th>
                  <th>Cargas</th>
                  <th>Cana (t)</th>
                  <th>Média/carga (t)</th>
                  <th>Situação da colheita</th>
                  <th>TCH efetivo</th>
                  <th>Dias</th>
                  <th>Primeira</th>
                  <th>Última</th>
                  <th>Divergentes</th>
                </tr>
              </thead>
              <tbody>
                {report.fields
                  .filter((field) => field.farmKey === farm.key)
                  .map((field) => (
                    <tr key={field.key}>
                      <td>{field.fieldCode}</td>
                      <td>{field.fieldName ?? "-"}</td>
                      <td>{formatIndicator(field.registeredAreaHa)}</td>
                      <td>{formatInteger(field.entryCount)}</td>
                      <td>{formatTons(field.totalNetWeight)}</td>
                      <td>{formatTons(field.averageNetWeightPerEntry)}</td>
                      <td>{field.evidenceLabel}</td>
                      <td>{formatIndicator(field.effectiveTch)}</td>
                      <td>{formatInteger(field.deliveryDays)}</td>
                      <td>{formatDate(field.firstDate)}</td>
                      <td>{formatDate(field.lastDate)}</td>
                      <td>{formatInteger(field.divergentCount)}</td>
                    </tr>
                  ))}
                <tr className="totalRow">
                  <td>Subtotal</td>
                  <td>{farm.fieldCount} talhão(ões)</td>
                  <td>{formatIndicator(farm.registeredAreaHa || null)}</td>
                  <td>{formatInteger(farm.entryCount)}</td>
                  <td>{formatTons(farm.totalNetWeight)}</td>
                  <td>{formatTons(farm.entryCount > 0 ? farm.totalNetWeight / farm.entryCount : null)}</td>
                  <td>
                    {farm.provenFieldCount} de {farm.fieldCount} comprovados
                  </td>
                  <td>{formatIndicator(farm.effectiveTch)}</td>
                  <td>-</td>
                  <td>{formatDate(farm.firstDate)}</td>
                  <td>{formatDate(farm.lastDate)}</td>
                  <td>{formatInteger(farm.divergentCount)}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      ))}
      <h3>Resumo por fazenda</h3>
      <FarmTable report={report} />
    </>
  );
}

function FarmTable({ report }: { report: CaneReport }) {
  const total: FarmRow = {
    key: "total",
    farmCode: "Total",
    farmName: `${report.totals.farmCount} fazenda(s)`,
    fieldCount: report.totals.fieldCount,
    entryCount: report.totals.entryCount,
    divergentCount: report.totals.divergentCount,
    totalNetWeight: report.totals.totalNetWeight,
    shareOfTotal: report.totals.totalNetWeight > 0 ? 100 : 0,
    registeredAreaHa: report.totals.registeredAreaHa,
    provenAreaHa: report.totals.provenAreaHa,
    provenFieldCount: report.totals.provenFieldCount,
    provenNetWeight: report.totals.provenNetWeight,
    effectiveTch: report.totals.effectiveTch,
    firstDate: report.totals.firstDate,
    lastDate: report.totals.lastDate
  };

  return (
    <div className="tableWrap">
      <table>
        <thead>
          <tr>
            <th>Código</th>
            <th>Fazenda</th>
            <th>Talhões</th>
            <th>Cargas</th>
            <th>Cana (t)</th>
            <th>% do total</th>
            <th>Área cad. (ha)</th>
            <th>Área comprov. (ha)</th>
            <th>Comprovados</th>
            <th>TCH efetivo</th>
            <th>Divergentes</th>
            <th>Período</th>
          </tr>
        </thead>
        <tbody>
          {[...report.farms, total].map((farm) => (
            <tr key={farm.key} className={farm.key === "total" ? "totalRow" : undefined}>
              <td>{farm.farmCode ?? "-"}</td>
              <td>{farm.farmName}</td>
              <td>{formatInteger(farm.fieldCount)}</td>
              <td>{formatInteger(farm.entryCount)}</td>
              <td>{formatTons(farm.totalNetWeight)}</td>
              <td>{formatDecimal(farm.shareOfTotal, 1)}</td>
              <td>{formatDecimal(farm.registeredAreaHa)}</td>
              <td>{formatDecimal(farm.provenAreaHa)}</td>
              <td>
                {farm.provenFieldCount}/{farm.fieldCount}
              </td>
              <td>{formatIndicator(farm.effectiveTch)}</td>
              <td>{formatInteger(farm.divergentCount)}</td>
              <td>
                {formatDate(farm.firstDate)} a {formatDate(farm.lastDate)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ReportMetric({ label, value, caption }: { label: string; value: string; caption?: string }) {
  return (
    <article className="metric">
      <span>{label}</span>
      <strong>{value}</strong>
      {caption ? <small className="muted">{caption}</small> : null}
    </article>
  );
}

function provenBasis(report: CaneReport) {
  return `${report.totals.provenFieldCount} de ${report.totals.fieldCount} talhões`;
}

function effectiveTchLabel(report: CaneReport) {
  const { provenFieldCount, fieldCount } = report.totals;
  return provenFieldCount > 0 && provenFieldCount < fieldCount ? "TCH efetivo parcial (t/ha)" : "TCH efetivo (t/ha)";
}

function reportQuery(filters: ReportFilters) {
  return queryString({
    type: filters.type,
    farmId: filters.farmId || undefined,
    fieldId: filters.fieldId || undefined,
    from: filters.from || undefined,
    to: filters.to || undefined
  });
}

function formatTons(value: number | null | undefined) {
  return formatDecimal(value, 3);
}

function formatDecimal(value: number | null | undefined, digits = 2) {
  if (value === null || value === undefined || !Number.isFinite(value)) return "-";
  return new Intl.NumberFormat("pt-BR", { minimumFractionDigits: digits, maximumFractionDigits: digits }).format(value);
}

function formatIndicator(value: number | null | undefined) {
  return value === null || value === undefined || !Number.isFinite(value) ? "N/D" : formatDecimal(value);
}

function formatInteger(value: number) {
  return new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 0 }).format(value);
}

function formatDate(value: string | null | undefined) {
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(value ?? "");
  return match ? `${match[3]}/${match[2]}/${match[1]}` : "-";
}
