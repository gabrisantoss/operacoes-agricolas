import { useEffect, useState } from "react";
import { Download, Eye, Upload } from "lucide-react";
import { apiRequest, downloadFile, postFormJson } from "./api";

type ItemStatus = "CREATE" | "UPDATE" | "SKIP" | "DIVERGENCE" | "ERROR";

type ImportItem = {
  rowNumber: number;
  orderNumber: string;
  farmReference: string;
  fieldReference: string;
  status: ItemStatus;
  message: string;
};

type ImportDivergence = {
  kind: string;
  rowNumber: number | null;
  orderNumber: string;
  farmName: string;
  fieldCode: string;
  message: string;
};

type ImportPreview = {
  fileName: string;
  fileHash: string;
  summary: {
    rowCount: number;
    createCount: number;
    updateCount: number;
    skippedCount: number;
    divergenceCount: number;
    errorsCount: number;
  };
  items: ImportItem[];
  divergences: ImportDivergence[];
  errors: string[];
  previousImport: { fileName: string; importedAt: string } | null;
};

type ImportSummary = {
  id: string;
  fileName: string;
  importedAt: string;
  importedByName: string | null;
  rowCount: number;
  createCount: number;
  updateCount: number;
  skippedCount: number;
  divergenceCount: number;
};

type ImportDetail = ImportSummary & { items: ImportItem[]; divergences: ImportDivergence[] };

const statusLabels: Record<ItemStatus, string> = {
  CREATE: "Criar OS",
  UPDATE: "Adicionar setor",
  SKIP: "Sem alteração",
  DIVERGENCE: "Divergência",
  ERROR: "Erro"
};

const statusTone: Record<ItemStatus, string> = {
  CREATE: "ok",
  UPDATE: "ok",
  SKIP: "",
  DIVERGENCE: "warning",
  ERROR: "danger"
};

export function OrderExcelImportView({
  token,
  onImported,
  setMessage
}: {
  token: string;
  onImported: () => Promise<void>;
  setMessage: (message: string | null) => void;
}) {
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<ImportPreview | null>(null);
  const [history, setHistory] = useState<ImportSummary[]>([]);
  const [detail, setDetail] = useState<ImportDetail | null>(null);
  const [busy, setBusy] = useState(false);
  // Remounts the file input so the same spreadsheet can be selected again (e.g. to see the re-import notice).
  const [fileInputKey, setFileInputKey] = useState(0);

  async function loadHistory() {
    const payload = await apiRequest<{ imports: ImportSummary[] }>("/orders/import-excel/history", token);
    setHistory(payload.imports);
  }

  useEffect(() => {
    loadHistory().catch((error) => setMessage(error instanceof Error ? error.message : "Falha ao carregar o histórico."));
  }, [token]);

  async function send(path: string, extra?: Record<string, string>) {
    if (!file) {
      setMessage("Selecione a planilha exportada do sistema corporativo.");
      return null;
    }
    const body = new FormData();
    body.append("file", file);
    for (const [key, value] of Object.entries(extra ?? {})) body.append(key, value);
    return postFormJson<ImportPreview & { importId?: string }>(path, token, body);
  }

  async function runPreview() {
    setBusy(true);
    setMessage(null);
    try {
      setPreview(await send("/orders/import-excel/preview"));
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Falha ao gerar a prévia.");
    } finally {
      setBusy(false);
    }
  }

  async function confirm() {
    if (!preview) return;
    setBusy(true);
    setMessage(null);
    try {
      const result = await send("/orders/import-excel", { previewHash: preview.fileHash });
      if (result?.importId) {
        setMessage(`Importação registrada: ${result.summary.createCount} OS criada(s), ${result.summary.updateCount} OS atualizada(s), ${result.summary.divergenceCount} divergência(s) para conferir no sistema corporativo.`);
        setPreview(null);
        setFile(null);
        setFileInputKey((key) => key + 1);
        await Promise.all([loadHistory(), onImported()]);
        await openDetail(result.importId);
      }
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Falha ao confirmar a importação.");
    } finally {
      setBusy(false);
    }
  }

  async function openDetail(id: string) {
    try {
      setDetail(await apiRequest<ImportDetail>(`/orders/import-excel/history/${id}`, token));
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Falha ao abrir a importação.");
    }
  }

  const blocked = !preview || preview.summary.errorsCount > 0 || Boolean(preview.previousImport);

  return (
    <div className="stack orderImportView">
      <section className="panel dashboardFiltersPanel">
        <div className="dashboardSectionHeader">
          <div>
            <h2>Importar OS exportadas do sistema corporativo</h2>
            <span className="muted">
              Fluxo: sistema corporativo (oficial) → planilha Excel exportada → prévia → registro no Balança para gestão e relatórios.
              Nada é enviado ao sistema corporativo. Divergências são apenas relatadas; nenhuma OS encerrada ou setor existente é alterado
              automaticamente.
            </span>
          </div>
        </div>
        <div className="importRow">
          <label className="fileInput">
            <Upload size={20} />
            <span>{file?.name ?? "Selecionar planilha .xlsx"}</span>
            <input
              key={fileInputKey}
              type="file"
              accept=".xlsx"
              onChange={(event) => {
                setFile(event.target.files?.[0] ?? null);
                setPreview(null);
              }}
            />
          </label>
          <button className="secondaryButton" type="button" onClick={runPreview} disabled={busy || !file}>
            <Eye size={18} />
            {preview ? "Atualizar prévia" : "Prévia"}
          </button>
          {preview ? (
            <button className="primaryButton" type="button" onClick={confirm} disabled={busy || blocked}>
              Confirmar importação
            </button>
          ) : null}
        </div>
        <span className="muted">
          Layout demonstrativo aceito: colunas "Codigo da OS", "Propriedade" (código ou número da propriedade cadastrada) e
          "Setor" (código do talhão). Outras colunas são ignoradas.
        </span>
      </section>

      {preview ? (
        <section className="panel orderImportPreview">
          <h2>Prévia de {preview.fileName}</h2>
          {preview.previousImport ? (
            <div className="notice">
              Este arquivo já foi importado em {formatDateTime(preview.previousImport.importedAt)} como "{preview.previousImport.fileName}".
              Reimportação do mesmo arquivo não é aplicada novamente.
            </div>
          ) : null}
          {preview.summary.errorsCount > 0 ? (
            <div className="notice">Importação bloqueada: corrija o cadastro ou a planilha antes de confirmar.</div>
          ) : null}
          <section className="metricsGrid">
            <Metric label="Linhas" value={preview.summary.rowCount} />
            <Metric label="OS a criar" value={preview.summary.createCount} />
            <Metric label="OS a atualizar" value={preview.summary.updateCount} />
            <Metric label="Sem alteração" value={preview.summary.skippedCount} />
            <Metric label="Divergências" value={preview.summary.divergenceCount} />
            <Metric label="Erros" value={preview.summary.errorsCount} />
          </section>
          <ItemsTable items={preview.items} />
          <DivergencesTable divergences={preview.divergences} />
        </section>
      ) : null}

      <section className="panel">
        <h2>Histórico de importações</h2>
        <div className="tableWrap">
          <table>
            <thead>
              <tr>
                <th>Importado em</th>
                <th>Arquivo</th>
                <th>Usuário</th>
                <th>Linhas</th>
                <th>Criadas</th>
                <th>Atualizadas</th>
                <th>Sem alteração</th>
                <th>Divergências</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {history.length === 0 ? (
                <tr>
                  <td colSpan={9}>Nenhuma planilha importada ainda.</td>
                </tr>
              ) : (
                history.map((item) => (
                  <tr key={item.id}>
                    <td>{formatDateTime(item.importedAt)}</td>
                    <td>{item.fileName}</td>
                    <td>{item.importedByName ?? "-"}</td>
                    <td>{item.rowCount}</td>
                    <td>{item.createCount}</td>
                    <td>{item.updateCount}</td>
                    <td>{item.skippedCount}</td>
                    <td>{item.divergenceCount}</td>
                    <td>
                      <button className="secondaryButton compactButton" type="button" onClick={() => openDetail(item.id)}>
                        Detalhes
                      </button>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </section>

      {detail ? (
        <section className="panel">
          <div className="sectionHeader">
            <div>
              <h2>Importação de {detail.fileName}</h2>
              <span className="muted">
                {formatDateTime(detail.importedAt)} · {detail.createCount} criada(s) · {detail.updateCount} atualizada(s) ·{" "}
                {detail.divergenceCount} divergência(s)
              </span>
            </div>
            <button
              className="secondaryButton compactButton"
              type="button"
              onClick={() =>
                downloadFile(`/orders/import-excel/history/${detail.id}/report.csv`, token, "importacao-os.csv").catch((error) =>
                  setMessage(error instanceof Error ? error.message : "Falha ao exportar o relatório.")
                )
              }
            >
              <Download size={16} />
              Relatório CSV
            </button>
          </div>
          <ItemsTable items={detail.items} />
          <DivergencesTable divergences={detail.divergences} />
        </section>
      ) : null}
    </div>
  );
}

function ItemsTable({ items }: { items: ImportItem[] }) {
  return (
    <>
      <h3>Linhas da planilha</h3>
      <div className="tableWrap">
        <table>
          <thead>
            <tr>
              <th>Linha</th>
              <th>Codigo da OS</th>
              <th>Propriedade</th>
              <th>Setor</th>
              <th>Resultado</th>
              <th>Detalhe</th>
            </tr>
          </thead>
          <tbody>
            {items.map((item) => (
              <tr key={`${item.rowNumber}-${item.status}`}>
                <td>{item.rowNumber}</td>
                <td>{item.orderNumber}</td>
                <td>{item.farmReference}</td>
                <td>{item.fieldReference}</td>
                <td>
                  <span className={`statusBadge ${statusTone[item.status]}`}>{statusLabels[item.status]}</span>
                </td>
                <td>{item.message}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

function DivergencesTable({ divergences }: { divergences: ImportDivergence[] }) {
  if (divergences.length === 0) return null;
  return (
    <>
      <h3>Divergências para conferir no sistema corporativo (não aplicadas)</h3>
      <div className="tableWrap">
        <table>
          <thead>
            <tr>
              <th>Linha</th>
              <th>OS</th>
              <th>Fazenda</th>
              <th>Setor</th>
              <th>Detalhe</th>
            </tr>
          </thead>
          <tbody>
            {divergences.map((item, index) => (
              <tr key={`${item.kind}-${item.orderNumber}-${item.fieldCode}-${index}`}>
                <td>{item.rowNumber ?? "-"}</td>
                <td>{item.orderNumber}</td>
                <td>{item.farmName || "-"}</td>
                <td>{item.fieldCode}</td>
                <td>{item.message}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

function Metric({ label, value }: { label: string; value: number }) {
  return (
    <article className="metric">
      <span>{label}</span>
      <strong>{value}</strong>
    </article>
  );
}

function formatDateTime(value: string) {
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString("pt-BR");
}
