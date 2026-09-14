import { startTransition, useCallback, useDeferredValue, useEffect, useMemo, useRef, useState } from "react";
import type { CSSProperties, DragEvent, FormEvent, KeyboardEvent, MouseEvent, ReactNode, WheelEvent } from "react";


import {
  AlertTriangle,
  CalendarDays,
  BarChart3,
  ChevronDown,
  CheckCircle2,
  ClipboardList,
  Database,
  Download,
  Edit3,
  ExternalLink,
  Eye,
  FileText,
  FileSpreadsheet,
  Filter,
  FolderOpen,
  Gauge,
  History,
  Image as ImageIcon,
  Layers3,
  LocateFixed,
  Maximize2,
  Navigation,
  RefreshCw,
  RotateCcw,
  RotateCw,
  Search,
  Share2,
  TrendingUp,
  Trash2,
  Upload,
  X,
  PieChart,
  Calendar,
  ZoomIn,
  ZoomOut,
  MessageCircle
} from "lucide-react";
import {
  apiRequest,
  createObjectUrl,
  downloadCsv,
  downloadFile,
  downloadFormFile,
  fetchFileBlob,
  openFile,
  postFormJson,
  queryString,
  type TransferProgress
} from "./api";
import { OperationalHealthPanel } from "./OperationalHealthPanel";



import { dashboardPathForYear } from "./dashboardYear";
import { systemIdentity } from "@balanca/shared";
import type {
  EntryStatus,
  FleetEquipmentType,
  FleetMovementInput,
  FleetMovementStatus,
  FleetMovementType,
} from "@balanca/shared";
import type {
  DashboardFilters,
  BulkCloseOrderResult,
  Farm,
  FleetMovement,
  FleetReportPreview,
  HarvestExecutiveDashboard,
  HarvestOwnershipType,
  HarvestOrder,
  HarvestOrderHistory,
  ImportBatch,
  ImportBatchEntry,
  PostHarvestIntegrationConnection,
  PostHarvestIntegrationEvent,
  PostHarvestIntegrationStatus,
  PreviewImport,
  ProductionDashboard,
  Summary,
  User
} from "./types";

type View =
  | "dashboard"
  | "harvest"
  | "production"
  | "farms"
  | "orders"
  | "orderClosure"
  | "integrations"
  | "imports"
  | "history"
  | "apportionment";
const viewStorageKey = "oaDemo.activeView";
const yearStorageKey = "oaDemo.selectedYear";
const viewOptions: View[] = [
  "dashboard",
  "harvest",
  "production",
  "farms",
  "orders",
  "orderClosure",
  "integrations",
  "imports",
  "history",
  "apportionment"
];





function readInitialView(): View {
  try {
    const stored = window.localStorage.getItem(viewStorageKey) as View | null;
    return stored && viewOptions.includes(stored) ? stored : "dashboard";
  } catch {
    return "dashboard";
  }
}

type AvailableReport = {
  key: string;
  start: string;
  end: string;
  label: string;
  analyses: number;
  rows: number;
  ok: number;
  errors: number;
  fileNames: string[];
  reportDates: string[];
  latestImportedAt?: string;
};

type FieldDraft = {
  id: string;
  code: string;
  areaAlq: string;
};

const statusLabels: Record<string, string> = {
  OK: "OK",
  OS_NOT_FOUND: "OS nao encontrada",
  FARM_NOT_FOUND: "Fazenda nao cadastrada",
  FIELD_NOT_FOUND: "Talhao nao cadastrado",
  FARM_MISMATCH: "Fazenda divergente",
  FIELD_NOT_RELEASED: "Talhao nao liberado",
  MISSING_DATA: "Dados faltando"
};





const fleetMovementTypeOptions: FleetMovementType[] = ["LEFT_MILL", "RETURNED_MILL", "RESERVE_ACTIVATED", "RESERVE_RELEASED"];

const fleetMovementTypeLabels: Record<FleetMovementType, string> = {
  LEFT_MILL: "Saiu da operacao",
  RETURNED_MILL: "Voltou para operacao",
  RESERVE_ACTIVATED: "Reserva usado",
  RESERVE_RELEASED: "Reserva liberado"
};

const fleetEquipmentTypeOptions: FleetEquipmentType[] = [
  "COLHEDORA",
  "TRANSBORDO",
  "CARREGADEIRA",
  "VIVENCIA",
  "CAMINHAO_DAGUA",
  "FURGAO",
  "ONIBUS",
  "OUTRO"
];

const fleetEquipmentTypeLabels: Record<FleetEquipmentType, string> = {
  COLHEDORA: "Colhedora",
  TRANSBORDO: "Transbordo",
  CARREGADEIRA: "Carregadeira",
  VIVENCIA: "Vivência",
  CAMINHAO_DAGUA: "Caminhão d'água",
  FURGAO: "Furgão",
  ONIBUS: "Ônibus",
  OUTRO: "Outro"
};

const fleetMovementStatusLabels: Record<FleetMovementStatus, string> = {
  OPEN: "Aberto",
  CLOSED: "Concluído"
};

const mappingFields: Array<{ key: keyof PreviewImport["mapping"]; label: string }> = [
  { key: "ticketNumber", label: "Nota" },
  { key: "entryDate", label: "Data de entrada" },
  { key: "farm", label: "Fazenda" },
  { key: "field", label: "Talhão" },
  { key: "order", label: "OS" },
  { key: "vehiclePlate", label: "Placa" },
  { key: "grossWeight", label: "Peso bruto" },
  { key: "netWeight", label: "Peso líquido" }
];

function isLoopbackBrowserHost() {
  const host = window.location.hostname.toLowerCase();
  return host === "localhost" || host === "127.0.0.1" || host === "[::1]" || host === "::1";
}

// The bearer token is only for loopback development. In production, the
// portal session cookie is forwarded by apiRequest with credentials enabled.
const localAccessToken = import.meta.env.DEV && isLoopbackBrowserHost() ? "local-access" : "";
const initialFarmRenderLimit = 60;
const farmRenderStep = 60;
const collapsedFieldPreviewLimit = 8;
const initialProductionRowLimit = 120;
const productionRowStep = 120;
const ownershipLabels: Record<HarvestOwnershipType, string> = {
  OWN: "Cana própria",
  SUPPLIER: "Fornecedor",
  UNKNOWN: "Sem classificação"
};

type DataSlice = "summary" | "farms" | "orders" | "orderHistory" | "batches";

const initialDataLoading: Record<DataSlice, boolean> = {
  summary: false,
  farms: false,
  orders: false,
  orderHistory: false,
  batches: false
};

export function App() {
  const token = localAccessToken;
  const launcherHref = useMemo(() => {
    const host = window.location.hostname || "127.0.0.1";
    return `${window.location.protocol}//${host}:8890/`;
  }, []);
  const [view, setView] = useState<View>(() => readInitialView());
  const [currentUser, setCurrentUser] = useState<User | null>(null);
  const [summary, setSummary] = useState<Summary | null>(null);
  const [farms, setFarms] = useState<Farm[]>([]);
  const [orders, setOrders] = useState<HarvestOrder[]>([]);
  const [orderHistory, setOrderHistory] = useState<HarvestOrderHistory[]>([]);
  const [analysisBatches, setAnalysisBatches] = useState<ImportBatch[]>([]);
  const [dashboardFilters, setDashboardFilters] = useState<DashboardFilters>({});
  const [message, setMessage] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [harvestReloadKey, setHarvestReloadKey] = useState(0);
  const [productionReloadKey, setProductionReloadKey] = useState(0);
  const [dataLoading, setDataLoading] = useState<Record<DataSlice, boolean>>(initialDataLoading);
  const loadedSlicesRef = useRef<Partial<Record<DataSlice, boolean>>>({});
  const dataRequestsRef = useRef<Partial<Record<DataSlice, Promise<void>>>>({});
  const dataAbortControllersRef = useRef<Partial<Record<DataSlice, AbortController>>>({});
  const [availableYears, setAvailableYears] = useState<number[]>([]);
  const [selectedYear, setSelectedYear] = useState<number | null>(() => {
    try {
      const stored = window.localStorage.getItem(yearStorageKey);
      const parsed = stored ? Number(stored) : Number.NaN;
      return Number.isInteger(parsed) && parsed > 0 ? parsed : null;
    } catch {
      return null;
    }
  });

  useEffect(() => {
    let active = true;

    apiRequest<{ user: User }>("/auth/me", token)
      .then((payload) => {
        if (active) setCurrentUser(payload.user);
      })
      .catch(() => {
        if (active) setCurrentUser(null);
      });

    return () => {
      active = false;
    };
  }, [token]);

  useEffect(() => {
    apiRequest<{ years: number[] }>("/safras", token)
      .then((payload) => {
        setAvailableYears(payload.years);
        if (selectedYear === null || !payload.years.includes(selectedYear)) {
          const mostRecent = payload.years[0] ?? new Date().getFullYear();
          setSelectedYear(mostRecent);
          try { window.localStorage.setItem(yearStorageKey, String(mostRecent)); } catch {}
        }
      })
      .catch(() => {
        const fallback = new Date().getFullYear();
        setAvailableYears([fallback]);
        if (selectedYear === null) setSelectedYear(fallback);
      });
  }, [token]);

  function handleYearChange(year: number) {
    setSelectedYear(year);
    try { window.localStorage.setItem(yearStorageKey, String(year)); } catch {}
    loadedSlicesRef.current = {};
  }

  const yearQuerySuffix = selectedYear ? `year=${selectedYear}` : "";

  function setSliceLoading(slice: DataSlice, value: boolean) {
    setDataLoading((current) => (current[slice] === value ? current : { ...current, [slice]: value }));
  }

  function loadSlice(slice: DataSlice, loader: (signal: AbortSignal) => Promise<void>, force = false) {
    if (!force && loadedSlicesRef.current[slice]) {
      return Promise.resolve();
    }

    const currentRequest = dataRequestsRef.current[slice];

    if (!force && currentRequest) {
      return currentRequest;
    }

    if (force) {
      dataAbortControllersRef.current[slice]?.abort();
    }

    setSliceLoading(slice, true);
    const controller = new AbortController();
    dataAbortControllersRef.current[slice] = controller;

    const request = loader(controller.signal)
      .then(() => {
        if (!controller.signal.aborted) {
          loadedSlicesRef.current[slice] = true;
        }
      })
      .catch((error) => {
        if (!controller.signal.aborted) {
          throw error;
        }
      })
      .finally(() => {
        if (dataRequestsRef.current[slice] === request) {
          delete dataRequestsRef.current[slice];
          delete dataAbortControllersRef.current[slice];
          setSliceLoading(slice, false);
        }
      });

    dataRequestsRef.current[slice] = request;
    return request;
  }

  function loadSummary(filters = dashboardFilters, force = false) {
    return loadSlice(
      "summary",
      async (signal) => {
        const payload = await apiRequest<Summary>(`/dashboard/summary${queryString(toQueryFilters(filters))}`, token, { signal });
        setSummary(payload);
      },
      force
    );
  }

  function loadFarms(force = false) {
    return loadSlice(
      "farms",
      async (signal) => {
        const payload = await apiRequest<{ farms: Farm[] }>("/farms", token, { signal });
        setFarms(payload.farms);
      },
      force
    );
  }

  function loadOrders(force = false) {
    return loadSlice(
      "orders",
      async (signal) => {
        const yearQs = yearQuerySuffix ? `?${yearQuerySuffix}` : "";
        const payload = await apiRequest<{ orders: HarvestOrder[] }>(`/orders${yearQs}`, token, { signal });
        setOrders(payload.orders);
      },
      force
    );
  }

  function loadOrderHistory(force = false) {
    return loadSlice(
      "orderHistory",
      async (signal) => {
        const payload = await apiRequest<{ history: HarvestOrderHistory[] }>("/orders/history?limit=150", token, { signal });
        setOrderHistory(payload.history);
      },
      force
    );
  }

  function loadBatches(force = false) {
    return loadSlice(
      "batches",
      async (signal) => {
        const payload = await apiRequest<{ batches: ImportBatch[] }>("/imports/batches?limit=150", token, { signal });
        setAnalysisBatches(payload.batches);
      },
      force
    );
  }

  async function loadDashboardData(filters = dashboardFilters, force = false) {
    await Promise.all([loadSummary(filters, force), loadBatches(force)]);
  }

  async function loadOrdersData(force = false) {
    await Promise.all([loadFarms(force), loadOrders(force), loadOrderHistory(force)]);
  }

  async function refreshCurrentView(force = true) {
    if (view === "dashboard") {
      await loadDashboardData(dashboardFilters, force);
      void loadFarms(false).catch((error) => setMessage(error.message));
      return;
    }

    if (view === "harvest") {
      if (force) {
        setHarvestReloadKey((key) => key + 1);
      }

      return;
    }

    if (view === "farms") {
      await loadFarms(force);
      return;
    }

    if (view === "production") {
      if (force) {
        setProductionReloadKey((key) => key + 1);
      }

      return;
    }

    if (view === "orders") {
      await loadOrdersData(force);
      return;
    }



    if (view === "orderClosure") {
      await loadOrdersData(force);
      return;
    }

    if (view === "imports") {
      await loadDashboardData(dashboardFilters, force);
      return;
    }

    if (view === "history") {
      await loadBatches(force);
    }
  }

  async function refreshDashboardAfterImport(filters = dashboardFilters) {
    await Promise.all([loadSummary(filters, true), loadBatches(true)]);
  }

  async function refreshFarmsAfterSave() {
    await Promise.all([loadFarms(true), loadOrders(true), loadSummary(dashboardFilters, true)]);
  }

  async function refreshOrdersAfterSave() {
    await Promise.all([loadFarms(true), loadOrders(true), loadOrderHistory(true), loadSummary(dashboardFilters, true), loadBatches(true)]);
  }

  function navigate(nextView: View) {
    if (nextView === view) {
      return;
    }

    setMessage(null);
    startTransition(() => setView(nextView));
  }

  useEffect(() => {
    try {
      window.localStorage.setItem(viewStorageKey, view);
    } catch {
      // Browser storage is optional for navigation memory.
    }
  }, [view]);

  useEffect(() => {
    refreshCurrentView(false).catch((error) => setMessage(error.message));
  }, [token, view, selectedYear]);

  useEffect(() => {
    const loadWarmCache = () => {
      void Promise.allSettled([loadFarms(false), loadOrders(false), loadOrderHistory(false)]).catch(() => undefined);
    };
    const idleWindow = window as Window & {
      requestIdleCallback?: (callback: () => void, options?: { timeout: number }) => number;
    };

    if (idleWindow.requestIdleCallback) {
      idleWindow.requestIdleCallback(loadWarmCache, { timeout: 3000 });
    } else {
      window.setTimeout(loadWarmCache, 900);
    }
  }, [token]);

  async function applyDashboardFilters(filters: DashboardFilters) {
    setDashboardFilters(filters);
    setLoading(true);

    try {
      await loadSummary(filters, true);
    } finally {
      setLoading(false);
    }
  }

  const title = {
    dashboard: "Resultado da validação",
    harvest: "Painel da safra",
    production: "Entradas por talhão",
    farms: "Cadastro",
    orders: "Colheita atual",
    orderClosure: "Encerrar OS",
    integrations: "Integracao pos-colheita",
    imports: "Validar colheita",
    history: "Histórico de análises",
    apportionment: "Rateio de OS"
  }[view];

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brandMark">
            <img src={`${import.meta.env.BASE_URL}assets/logo.svg`} alt="OA" />
          </div>
          <div className="brandCopy">
            <strong>Operações Agrícolas</strong>
            <span>{systemIdentity.currentName}</span>
          </div>
        </div>

        <div className="safraSelector">
          <label className="safraLabel">
            <Calendar size={16} />
            Safra
          </label>
          <select
            className="safraSelect"
            value={selectedYear ?? ""}
            onChange={(e) => handleYearChange(Number(e.target.value))}
          >
            {availableYears.map((year) => (
              <option key={year} value={year}>
                {year}
              </option>
            ))}
          </select>
        </div>

        <nav className="nav">
          <NavButton active={view === "dashboard"} icon={<Database />} label="Resultado" onClick={() => navigate("dashboard")} />
          <NavButton active={view === "harvest"} icon={<TrendingUp />} label="Safra" onClick={() => navigate("harvest")} />
          <NavButton active={view === "production"} icon={<BarChart3 />} label="Entradas" onClick={() => navigate("production")} />
          <NavButton active={view === "farms"} icon={<ClipboardList />} label="Cadastro" onClick={() => navigate("farms")} />
          <NavButton active={view === "orders"} icon={<CheckCircle2 />} label="Colheita atual" onClick={() => navigate("orders")} />

          <NavButton active={view === "orderClosure"} icon={<CheckCircle2 />} label="Encerrar OS" onClick={() => navigate("orderClosure")} />
          <NavButton active={view === "integrations"} icon={<Share2 />} label="Integração" onClick={() => navigate("integrations")} />
          <NavButton active={view === "apportionment"} icon={<PieChart />} label="Rateio de OS" onClick={() => navigate("apportionment")} />
          <NavButton active={view === "imports"} icon={<FileSpreadsheet />} label="Validar" onClick={() => navigate("imports")} />
          <NavButton active={view === "history"} icon={<History />} label="Histórico" onClick={() => navigate("history")} />
        </nav>

      </aside>

      <main className="content">
        <div className="portfolioNotice" role="note">DEMONSTRAÇÃO FICTÍCIA · Operações Agrícolas · Dados sintéticos</div>
        <header className="topbar">
          <div className="topbarTitle">
            <h1>{title}</h1>
          </div>
          <div className="topbarActions">
            <a className="secondaryButton launcherButton" href={launcherHref}>
              <ExternalLink size={18} />
              Launcher
            </a>
            <button
              className="secondaryButton"
              onClick={() => {
                setLoading(true);
                refreshCurrentView(true)
                  .catch((error) => setMessage(error.message))
                  .finally(() => setLoading(false));
              }}
            >
              <RefreshCw size={18} />
              {loading ? "Atualizando" : "Atualizar"}
            </button>
          </div>
        </header>

        {message ? <div className="notice">{message}</div> : null}

        {view === "dashboard" ? (
          <Dashboard
            summary={summary}
            farms={farms}
            farmsLoading={dataLoading.farms}
            analysisBatches={analysisBatches}
            filters={dashboardFilters}
            token={token}
            onApplyFilters={applyDashboardFilters}
            onPdfImported={async (batchId) => {
              const nextFilters = batchId ? { batchId } : {};
              setDashboardFilters(nextFilters);
              setLoading(true);

              try {
                await refreshDashboardAfterImport(nextFilters);
              } finally {
                setLoading(false);
              }
            }}
            setMessage={setMessage}
          />
        ) : null}
        {view === "harvest" ? (
          <HarvestDashboardView
            key={selectedYear ?? "loading"}
            token={token}
            selectedYear={selectedYear}
            reloadKey={harvestReloadKey}
            setMessage={setMessage}
          />
        ) : null}
        {view === "production" ? (
          <ProductionView
            key={selectedYear ?? "loading"}
            token={token}
            selectedYear={selectedYear}
            reloadKey={productionReloadKey}
            setMessage={setMessage}
          />
        ) : null}
        {view === "farms" && dataLoading.farms && farms.length === 0 ? <div className="emptyState">Carregando cadastro...</div> : null}
        {view === "farms" && (!dataLoading.farms || farms.length > 0) ? (
          <FarmsView farms={farms} token={token} onSaved={refreshFarmsAfterSave} setMessage={setMessage} />
        ) : null}
        {view === "orders" && (dataLoading.farms || dataLoading.orders) && farms.length === 0 && orders.length === 0 ? (
          <div className="emptyState">Carregando colheita atual...</div>
        ) : null}
        {view === "orders" && (!dataLoading.farms || farms.length > 0 || orders.length > 0) ? (
          <OrdersView
            farms={farms}
            orders={orders}
            orderHistory={orderHistory}
            token={token}
            onSaved={refreshOrdersAfterSave}
            canManage={currentUser?.role === "ADMIN" || currentUser?.role === "ANALYST"}
            setMessage={setMessage}
          />
        ) : null}


        {view === "orderClosure" ? (
          <BulkCloseOrdersView orders={orders} token={token} onSaved={refreshOrdersAfterSave} setMessage={setMessage} />
        ) : null}
        {view === "integrations" ? (
          <PostHarvestIntegrationView
            token={token}
            isAdmin={currentUser?.role === "ADMIN"}
            setMessage={setMessage}
          />
        ) : null}
        {view === "apportionment" ? (
          <ApportionmentView token={token} yearQuerySuffix={yearQuerySuffix} />
        ) : null}
        {view === "imports" ? (
          <ImportsView
            token={token}
            recentBatches={summary?.recentBatches ?? []}
            onImported={refreshDashboardAfterImport}
            setMessage={setMessage}
          />
        ) : null}
        {view === "history" && dataLoading.batches && analysisBatches.length === 0 ? (
          <div className="emptyState">Carregando histórico...</div>
        ) : null}
        {view === "history" && (!dataLoading.batches || analysisBatches.length > 0) ? (
          <HistoryView
            batches={analysisBatches}
            token={token}
            onChanged={refreshDashboardAfterImport}
            onOpenBatch={async (batchId) => {
              const nextFilters = { batchId };
              setDashboardFilters(nextFilters);
              navigate("dashboard");
              setLoading(true);

              try {
                await refreshDashboardAfterImport(nextFilters);
              } finally {
                setLoading(false);
              }
            }}
            setMessage={setMessage}
          />
        ) : null}
        <footer className="appFooter">
          <span>Desenvolvido por</span>
          <strong>Gabriel Barbosa dos Santos</strong>
        </footer>
      </main>
    </div>
  );
}

function Dashboard({
  summary,
  farms,
  farmsLoading,
  analysisBatches,
  filters,
  token,
  onApplyFilters,
  onPdfImported,
  setMessage
}: {
  summary: Summary | null;
  farms: Farm[];
  farmsLoading?: boolean;
  analysisBatches: ImportBatch[];
  filters: DashboardFilters;
  token: string;
  onApplyFilters: (filters: DashboardFilters) => Promise<void>;
  onPdfImported: (batchId?: string) => Promise<void>;
  setMessage: (message: string | null) => void;
}) {
  const [draft, setDraft] = useState<DashboardFilters>(filters);
  const [deletingReportKey, setDeletingReportKey] = useState<string | null>(null);

  useEffect(() => {
    setDraft(filters);
  }, [filters]);

  const availableReports = useMemo(() => buildAvailableReports(analysisBatches), [analysisBatches]);
  const pdfImportTotals = useMemo(() => summarizePdfImportBatches(analysisBatches), [analysisBatches]);

  async function submitFilters(event: FormEvent) {
    event.preventDefault();
    setMessage(null);

    try {
      await onApplyFilters(cleanResultFilters(draft));
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Falha ao filtrar painel.");
    }
  }

  async function exportCsv() {
    setMessage(null);

    try {
      await downloadCsv(
        `/dashboard/divergences.csv${queryString(toQueryFilters(cleanResultFilters(draft)))}`,
        token,
        "divergencias-talhoes.csv"
      );
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Falha ao exportar divergencias.");
    }
  }

  async function exportErrorReport() {
    setMessage(null);

    try {
      await downloadFile(
        `/dashboard/divergences-report.pdf${queryString(toQueryFilters(cleanResultFilters(draft)))}`,
        token,
        "relatorio-divergencias-por-data.pdf"
      );
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Falha ao gerar relatorio de divergencias.");
    }
  }

  async function exportAvailableReport(report: AvailableReport, extension: "csv" | "pdf") {
    setMessage(null);

    const query = queryString(toQueryFilters(reportToFilters(report)));

    try {
      if (extension === "csv") {
        await downloadCsv(`/dashboard/divergences.csv${query}`, token, buildAvailableReportName(report, "csv"));
        return;
      }

      await downloadFile(`/dashboard/divergences-report.pdf${query}`, token, buildAvailableReportName(report, "pdf"));
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Falha ao baixar relatorio.");
    }
  }

  async function deleteAvailableReport(report: AvailableReport) {
    const confirmed = window.confirm(
      `Excluir o grupo de ${report.label}? As ${report.rows} entradas desses PDFs sairao do Resultado, mas cadastros, OS e talhoes continuam iguais.`
    );

    if (!confirmed) {
      return;
    }

    setDeletingReportKey(report.key);
    setMessage(null);

    try {
      const result = await apiRequest<{ deletedBatches: number; deletedRows: number }>(
        `/imports/batch-groups${queryString({ from: report.start, to: report.end })}`,
        token,
        { method: "DELETE" }
      );

      setDraft({});
      await onApplyFilters({});
      setMessage(`Grupo ${report.label} excluido: ${result.deletedBatches} analise(s), ${result.deletedRows} entrada(s).`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Falha ao excluir grupo.");
    } finally {
      setDeletingReportKey(null);
    }
  }

  async function clearPdfResults() {
    const confirmed = window.confirm(
      `Limpar todos os PDFs inseridos no Resultado? Isso remove ${pdfImportTotals.rows} entrada(s) de ${pdfImportTotals.batches} analise(s), mas mantem cadastros, OS e talhoes.`
    );

    if (!confirmed) {
      return;
    }

    setDeletingReportKey("all-pdf-results");
    setMessage(null);

    try {
      const result = await apiRequest<{ deletedBatches: number; deletedRows: number }>("/imports/pdf-batches", token, {
        method: "DELETE"
      });

      setDraft({});
      await onApplyFilters({});
      setMessage(`PDFs inseridos limpos: ${result.deletedBatches} analise(s), ${result.deletedRows} entrada(s).`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Falha ao limpar PDFs inseridos.");
    } finally {
      setDeletingReportKey(null);
    }
  }

  if (!summary) {
    return <div className="emptyState">Carregando painel...</div>;
  }

  const compactDivergences = summary.recentDivergences.slice(0, 8);
  const okRate = summary.totalEntries > 0 ? (summary.okEntries / summary.totalEntries) * 100 : 0;
  const duplicateReportCount = availableReports.filter((report) => report.analyses > 1).length;
  const latestReport = availableReports[0];

  return (
    <div className="stack resultDashboard">
      <PdfHarvestCheck
        token={token}
        onSaved={async (result) => onPdfImported(result?.batch?.id)}
        setMessage={setMessage}
        showInsertButton
        title="Comparar PDF da balança"
        description="Seleciona o PDF diário, confere as divergências e depois permite inserir os dados nos resultados."
      />

      <section className="resultHeroPanel">
        <div className="resultHeroHeader">
          <div>
            <span className="resultEyebrow">Resultado da validação</span>
            <h2>Painel operacional dos PDFs inseridos</h2>
            <p>
              Acompanhe os períodos importados, divergências e área validada com base no PERÍODO destacado nos PDFs.
            </p>
          </div>
          <div className="resultHeroActions">
            <button className="secondaryButton" type="button" onClick={exportCsv}>
              <Download size={18} />
              CSV
            </button>
            <button className="primaryButton" type="button" onClick={exportErrorReport}>
              <FileText size={18} />
              Divergências
            </button>
          </div>
        </div>

        <div className="resultKpiGrid">
          <ResultKpiCard
            icon={<Database size={22} />}
            label="Entradas"
            value={summary.totalEntries}
            detail={`${pdfImportTotals.batches} PDF${pdfImportTotals.batches === 1 ? "" : "s"} inserido${pdfImportTotals.batches === 1 ? "" : "s"}`}
          />
          <ResultKpiCard
            icon={<CheckCircle2 size={22} />}
            label="Corretas"
            value={summary.okEntries}
            detail={`${formatShortNumber(okRate)}% aprovado`}
            tone="ok"
          />
          <ResultKpiCard
            icon={<AlertTriangle size={22} />}
            label="Divergentes"
            value={summary.divergentEntries}
            detail="itens para revisar"
            tone={summary.divergentEntries > 0 ? "danger" : "ok"}
          />
          <ResultKpiCard
            icon={<Layers3 size={22} />}
            label="Alqueires"
            value={formatShortNumber(summary.areaAlq)}
            detail={`${formatShortNumber(summary.areaHa)} ha`}
            tone="info"
          />
        </div>
      </section>

      <section className="panel dashboardFiltersPanel">
        <div className="dashboardSectionHeader">
          <div>
            <h2>Filtros</h2>
            <span className="muted">Refine a análise sem sair da visão geral.</span>
          </div>
        </div>
        <form className="filterGrid" onSubmit={submitFilters}>
          <label>
            Análise
            <select
              value={draft.batchId ?? ""}
              onChange={(event) => setDraft((current) => ({ ...current, batchId: event.target.value || undefined }))}
            >
              <option value="">Todas</option>
              {analysisBatches.map((batch) => (
                <option value={batch.id} key={batch.id}>
                  {formatBatchOption(batch)}
                </option>
              ))}
            </select>
          </label>
          <label>
            Fazenda
            <select
              value={draft.farmId ?? ""}
              onChange={(event) => setDraft((current) => ({ ...current, farmId: event.target.value }))}
            >
              <option value="">Todas</option>
              {farmsLoading && farms.length === 0 ? <option disabled>Carregando fazendas...</option> : null}
              {farms.map((farm) => (
                <option value={farm.id} key={farm.id}>
                  {formatFarmLabel(farm)}
                </option>
              ))}
            </select>
          </label>
          <label>
            Status
            <select
              value={draft.status ?? ""}
              onChange={(event) => setDraft((current) => ({ ...current, status: event.target.value as DashboardFilters["status"] }))}
            >
              <option value="">Todos</option>
              {Object.entries(statusLabels).map(([status, label]) => (
                <option value={status} key={status}>
                  {label}
                </option>
              ))}
            </select>
          </label>
          <label>
            OS
            <input
              value={draft.order ?? ""}
              onChange={(event) => setDraft((current) => ({ ...current, order: event.target.value }))}
            />
          </label>
          <label>
            Arquivo
            <input
              value={draft.fileName ?? ""}
              onChange={(event) => setDraft((current) => ({ ...current, fileName: event.target.value }))}
            />
          </label>
          <div className="filterActions">
            <button className="secondaryButton" type="submit">
              <Filter size={18} />
              Aplicar
            </button>
            <button
              className="secondaryButton"
              type="button"
              onClick={() => {
                setDraft({});
                onApplyFilters({}).catch((error) =>
                  setMessage(error instanceof Error ? error.message : "Falha ao limpar filtros.")
                );
              }}
            >
              Limpar
            </button>
            <button className="primaryButton" type="button" onClick={exportCsv}>
              <Download size={18} />
              Exportar CSV
            </button>
            <button className="primaryButton" type="button" onClick={exportErrorReport}>
              <FileText size={18} />
              Divergências por data
            </button>
          </div>
        </form>
      </section>

      <section className="resultAlertGrid" aria-label="Resumo de atenção">
        <DashboardAlertCard
          icon={<AlertTriangle size={20} />}
          title="Divergências"
          value={summary.divergentEntries}
          detail={summary.divergentEntries > 0 ? "Há itens para conferir." : "Nenhuma pendência nos filtros atuais."}
          tone={summary.divergentEntries > 0 ? "danger" : "ok"}
        />
        <DashboardAlertCard
          icon={<CalendarDays size={20} />}
          title="Último período"
          value={latestReport?.label ?? "-"}
          detail={latestReport ? `${latestReport.rows} linhas importadas` : "Nenhum PDF inserido."}
          tone="info"
        />
        <DashboardAlertCard
          icon={<FileText size={20} />}
          title="PDFs inseridos"
          value={pdfImportTotals.batches}
          detail={`${pdfImportTotals.rows} linhas no resultado`}
        />
        <DashboardAlertCard
          icon={<Gauge size={20} />}
          title="Períodos repetidos"
          value={duplicateReportCount}
          detail={duplicateReportCount > 0 ? "Revise grupos com mais de um PDF." : "Sem repetição por período."}
          tone={duplicateReportCount > 0 ? "warning" : "ok"}
        />
      </section>

      <div className="dashboardContentGrid">
      <section className="panel dashboardReportsPanel">
        <div className="sectionHeader dashboardSectionHeader">
          <div>
            <h2>PDFs por período</h2>
            <span className="muted">
              A data considerada é sempre o PERÍODO destacado no PDF, não a data de emissão no canto direito.
            </span>
          </div>
          <button
            className="secondaryButton compactButton dangerButton"
            type="button"
            onClick={clearPdfResults}
            disabled={pdfImportTotals.batches === 0 || deletingReportKey === "all-pdf-results"}
          >
            <Trash2 size={16} />
            Limpar PDFs inseridos
          </button>
        </div>
        <div className="reportList">
          {availableReports.length === 0 ? (
            <span className="muted">
              {pdfImportTotals.batches > 0
                ? "Existem PDFs antigos sem data interna gravada. Limpe os PDFs inseridos e importe novamente para separar pelo período do PDF."
                : "Nenhum relatório de PDF inserido ainda."}
            </span>
          ) : (
            availableReports.map((report) => (
              <details className="reportItem" key={report.key}>
                <summary className="reportItemSummary">
                  <span className="reportItemMain">
                  <strong>{report.label}</strong>
                  <span>
                    {report.analyses} análise{report.analyses === 1 ? "" : "s"} · {report.rows} linhas · {report.errors} divergente
                    {report.errors === 1 ? "" : "s"}
                  </span>
                  </span>
                  <ChevronDown className="reportDisclosureIcon" size={18} aria-hidden="true" />
                </summary>
                <div className="reportItemDetails">
                  <div className="reportItemMain">
                  <small className="reportMeta">
                    Período considerado: {report.label}
                    {report.reportDates.length > 0 ? ` · Emitido em: ${formatReportDateList(report.reportDates)}` : ""}
                    {report.latestImportedAt ? ` · Importado em: ${formatDateTime(report.latestImportedAt)}` : ""}
                  </small>
                  <small>{formatReportFileList(report.fileNames)}</small>
                </div>
                <div className="rowActions availableReportActions">
                  <button className="secondaryButton compactButton" type="button" onClick={() => exportAvailableReport(report, "pdf")}>
                    <FileText size={16} />
                    PDF
                  </button>
                  <button className="secondaryButton compactButton" type="button" onClick={() => exportAvailableReport(report, "csv")}>
                    <Download size={16} />
                    CSV
                  </button>
                  <button
                    className="secondaryButton compactButton dangerButton"
                    type="button"
                    onClick={() => deleteAvailableReport(report)}
                    disabled={deletingReportKey === report.key}
                  >
                    <Trash2 size={16} />
                    Excluir grupo
                  </button>
                </div>
                </div>
              </details>
            ))
          )}
        </div>
      </section>

      <section className="panel dashboardSidePanel">
        <div className="dashboardSectionHeader">
          <div>
            <h2>Status da validação</h2>
            <span className="muted">Distribuição das entradas importadas.</span>
          </div>
        </div>
        <StatusBreakdown summary={summary} />

        <div className="dashboardSectionHeader recentImportsHeader">
          <div>
            <h2>Últimas importações</h2>
            <span className="muted">Lotes mais recentes no histórico.</span>
          </div>
        </div>
        <div className="recentImportList">
          {summary.recentBatches.length === 0 ? (
            <span className="muted">Nenhuma importação encontrada.</span>
          ) : (
            summary.recentBatches.slice(0, 5).map((batch) => (
              <article className="recentImportItem" key={batch.id}>
                <strong>{formatBatchDateRange(batch)}</strong>
                <span>{batch.fileName}</span>
                <small>
                  {batch.rowCount} linhas · {formatDateTime(batch.importedAt)}
                </small>
              </article>
            ))
          )}
        </div>
      </section>
      </div>

      <div className="dashboardContentGrid balanced">
      <section className="panel dashboardTablePanel">
        <div className="dashboardSectionHeader">
          <div>
            <h2>Alqueires por período</h2>
            <span className="muted">Área diária e acumulada conforme os PDFs inseridos.</span>
          </div>
        </div>
        <div className="tableWrap">
          <table>
            <thead>
              <tr>
                <th>Data PDF</th>
                <th>Talhões</th>
                <th>Alq no dia</th>
                <th>Alq acumulado</th>
                <th>Alq divergente</th>
              </tr>
            </thead>
            <tbody>
              {summary.areaByDate.length === 0 ? (
                <tr>
                  <td colSpan={5}>Nenhum talhão com área encontrado nos filtros atuais.</td>
                </tr>
              ) : (
                summary.areaByDate.map((item) => (
                  <tr key={item.date}>
                    <td>{formatDateOnly(item.date)}</td>
                    <td>{item.fieldCount}</td>
                    <td>{formatShortNumber(item.areaAlq)}</td>
                    <td>{formatShortNumber(item.cumulativeAreaAlq)}</td>
                    <td>{formatShortNumber(item.divergentAreaAlq)}</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </section>

      <section className="panel dashboardDivergencePanel">
        <div className="sectionHeader dashboardSectionHeader">
          <div>
            <h2>Últimas divergências</h2>
            <span className="muted">
              {summary.recentDivergences.length === 0
                ? "Nenhuma divergência encontrada nos filtros atuais."
                : `Mostrando ${compactDivergences.length} de ${summary.recentDivergences.length}.`}
            </span>
          </div>
        </div>
        <div className="compactDivergenceList">
          {compactDivergences.length === 0 ? (
            <span className="muted">Nada para revisar por enquanto.</span>
          ) : (
            compactDivergences.map((entry) => (
              <article className="compactDivergenceItem" key={entry.id}>
                <div className="compactDivergenceHeader">
                  <div>
                    <strong>{entry.farmNameRaw ?? "-"}</strong>
                    <span>
                      Talhão {entry.fieldCodeRaw ?? "-"} · OS {entry.orderNumberRaw ?? "-"} · Nota {entry.ticketNumber ?? "-"}
                    </span>
                  </div>
                  <span className={`statusBadge ${entryStatusClass(entry.status)}`}>{statusLabels[entry.status]}</span>
                </div>
                <p>{entry.notes ?? "Sem observação."}</p>
                <small>{entry.batch.fileName}</small>
              </article>
            ))
          )}
        </div>
      </section>
      </div>

    </div>
  );
}

function ResultKpiCard({
  icon,
  label,
  value,
  detail,
  tone = "neutral"
}: {
  icon: ReactNode;
  label: string;
  value: number | string;
  detail: string;
  tone?: "neutral" | "ok" | "danger" | "info";
}) {
  return (
    <article className={`resultKpiCard ${tone}`}>
      <span className="resultKpiIcon">{icon}</span>
      <div>
        <span>{label}</span>
        <strong>{value}</strong>
        <small>{detail}</small>
      </div>
    </article>
  );
}

function DashboardAlertCard({
  icon,
  title,
  value,
  detail,
  tone = "neutral"
}: {
  icon: ReactNode;
  title: string;
  value: number | string;
  detail: string;
  tone?: "neutral" | "ok" | "warning" | "danger" | "info";
}) {
  return (
    <article className={`dashboardAlertCard ${tone}`}>
      <span className="dashboardAlertIcon">{icon}</span>
      <div>
        <span>{title}</span>
        <strong>{value}</strong>
        <small>{detail}</small>
      </div>
    </article>
  );
}

function StatusBreakdown({ summary }: { summary: Summary }) {
  if (summary.byStatus.length === 0 || summary.totalEntries === 0) {
    return <span className="muted">Sem entradas para calcular status.</span>;
  }

  return (
    <div className="statusBreakdown">
      {summary.byStatus.map((item) => {
        const percent = summary.totalEntries > 0 ? (item.count / summary.totalEntries) * 100 : 0;

        return (
          <div className="statusBreakdownItem" key={item.status}>
            <div>
              <span className={`statusBadge ${entryStatusClass(item.status)}`}>{statusLabels[item.status]}</span>
              <strong>{item.count}</strong>
            </div>
            <div className="statusBreakdownTrack" aria-hidden="true">
              <span style={{ width: `${Math.max(3, percent)}%` }} />
            </div>
          </div>
        );
      })}
    </div>
  );
}

function HarvestDashboardView({
  token,
  selectedYear,
  reloadKey,
  setMessage
}: {
  token: string;
  selectedYear: number | null;
  reloadKey: number;
  setMessage: (message: string | null) => void;
}) {
  const [dashboard, setDashboard] = useState<HarvestExecutiveDashboard | null>(null);
  const [loading, setLoading] = useState(false);
  const [exporting, setExporting] = useState(false);
  const loadRequestIdRef = useRef(0);

  async function loadHarvestDashboard() {
    const requestId = ++loadRequestIdRef.current;

    if (selectedYear === null) {
      setLoading(false);
      return;
    }

    setLoading(true);
    setMessage(null);

    try {
      const payload = await apiRequest<HarvestExecutiveDashboard>(
        dashboardPathForYear("/dashboard/harvest", selectedYear),
        token
      );
      if (requestId === loadRequestIdRef.current) {
        setDashboard(payload);
      }
    } catch (error) {
      if (requestId === loadRequestIdRef.current) {
        setMessage(error instanceof Error ? error.message : "Falha ao carregar painel da safra.");
      }
    } finally {
      if (requestId === loadRequestIdRef.current) {
        setLoading(false);
      }
    }
  }

  useEffect(() => {
    setDashboard(null);
    void loadHarvestDashboard();
    return () => {
      loadRequestIdRef.current += 1;
    };
  }, [reloadKey, selectedYear, token]);

  async function exportHarvestReport() {
    if (selectedYear === null) {
      return;
    }

    setExporting(true);
    setMessage(null);

    try {
      await downloadFile(
        dashboardPathForYear("/dashboard/harvest-report.pdf", selectedYear),
        token,
        `relatorio-fechamento-safra-${selectedYear}.pdf`
      );
      setMessage(`Relatório da safra ${selectedYear} gerado.`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Falha ao gerar relatório da safra.");
    } finally {
      setExporting(false);
    }
  }

  const maxFarmWeight = useMemo(
    () => Math.max(1, ...(dashboard?.topFarms ?? []).map((row) => row.totalNetWeight)),
    [dashboard]
  );
  const maxFieldWeight = useMemo(
    () => Math.max(1, ...(dashboard?.topFields ?? []).map((row) => row.totalNetWeight)),
    [dashboard]
  );
  const maxPeriodWeight = useMemo(
    () => Math.max(1, ...(dashboard?.periods ?? []).map((row) => row.totalNetWeight)),
    [dashboard]
  );

  if (selectedYear === null) {
    return <div className="emptyState">Carregando safras...</div>;
  }

  if (!dashboard) {
    return <div className="emptyState">{loading ? "Carregando painel da safra..." : "Nenhuma base carregada."}</div>;
  }

  const topFarm = dashboard.topFarms[0];
  const periodCard = formatHarvestPeriodCard(dashboard.periodStart, dashboard.periodEnd);

  return (
    <div className="stack harvestDashboard">
      <section className="harvestKpiGrid">
        <HarvestKpi label="Participação de cana própria" value={formatPercent(dashboard.totals.ownPercentage)} tone="blue" />
        <HarvestKpi label="Cana entregue" value={formatShortNumber(dashboard.totals.totalNetWeight)} unit="toneladas" tone="green" />
        <HarvestKpi label="TCH estimado" value={formatShortNumber(dashboard.totals.tch)} unit="t/ha" tone="red" />
        <HarvestKpi label="TCA estimado" value={formatShortNumber(dashboard.totals.tca)} unit="t/alq" tone="orange" />
        <HarvestKpi label="Área cadastrada vinculada" value={formatShortNumber(dashboard.totals.areaAlq)} unit="alqueires" tone="cyan" />
        <HarvestKpi label="Fornecedor" value={formatShortNumber(dashboard.totals.supplierNetWeight)} unit="toneladas" tone="gray" />
        <HarvestKpi label="Fazendas observadas" value={dashboard.totals.farms} tone="teal" />
        <HarvestKpi label="Talhões observados" value={dashboard.totals.fields} tone="pink" />
        <HarvestKpi label="Entradas" value={dashboard.totals.entries} tone="blue" />
        <HarvestKpi label="Peso com pendência" value={formatShortNumber(dashboard.totals.divergentNetWeight)} unit="toneladas" tone="red" />
        <HarvestKpi label="Maior fazenda" value={topFarm ? formatShortNumber(topFarm.totalNetWeight) : "-"} unit="toneladas" subValue={topFarm?.farmCode ?? undefined} tone="green" />
        <HarvestKpi label="Período" value={periodCard.value} subValue={periodCard.subValue} tone="gray" />
      </section>

      <section className="harvestOverviewGrid">
        <section className="panel">
          <div className="sectionHeader">
            <div>
              <h2>Composição da cana</h2>
              <span className="muted">Classificação por código observado: 1xx própria, 2xx fornecedor.</span>
            </div>
            <div className="toolbarActions">
              <button className="secondaryButton compactButton" type="button" onClick={exportHarvestReport} disabled={exporting}>
                <FileText size={16} />
                {exporting ? "Gerando" : "PDF safra"}
              </button>
              <button className="secondaryButton compactButton" type="button" onClick={loadHarvestDashboard} disabled={loading}>
                <RefreshCw size={16} />
                {loading ? "Atualizando" : "Atualizar"}
              </button>
            </div>
          </div>
          <div className="ownershipList">
            {dashboard.ownership.map((item) => (
              <div className="ownershipRow" key={item.type}>
                <div>
                  <OwnershipBadge type={item.type} />
                  <span>{item.farmCount} fazendas observadas</span>
                  <span>{item.fieldCount} talhões observados</span>
                </div>
                <strong>{formatShortNumber(item.totalNetWeight)} t</strong>
                <div className="harvestProgress" style={progressStyle(item.percentage, 100)}>
                  <span />
                </div>
                <small>{formatPercent(item.percentage)}</small>
              </div>
            ))}
          </div>
        </section>

        <section className="panel">
          <div className="sectionHeader">
            <div>
              <h2>Evolução por período</h2>
              <span className="muted">Períodos dos relatórios com maior cana entregue, incluindo intervalos de vários dias.</span>
            </div>
          </div>
          <div className="periodChart">
            {dashboard.periods.length === 0 ? (
              <span className="muted">Sem períodos importados.</span>
            ) : (
              dashboard.periods.map((period) => (
                <div className="periodBar" key={`${period.periodStart ?? "sem-data"}-${period.periodEnd ?? ""}`}>
                  <span>{formatProductionPeriod(period.periodStart, period.periodEnd)}</span>
                  <div className="harvestProgress" style={progressStyle(period.totalNetWeight, maxPeriodWeight)}>
                    <span />
                  </div>
                  <strong>{formatShortNumber(period.totalNetWeight)} t</strong>
                </div>
              ))
            )}
          </div>
        </section>
      </section>

      <section className="harvestOverviewGrid">
        <section className="panel">
          <div className="sectionHeader">
            <div>
              <h2>Fazendas com mais cana</h2>
              <span className="muted">Ranking por peso líquido entregue.</span>
            </div>
          </div>
          <div className="rankingList">
            {dashboard.topFarms.length === 0 ? (
              <span className="muted">Sem fazendas para listar.</span>
            ) : (
              dashboard.topFarms.map((farm, index) => (
                <div className="rankingRow" key={farm.farmId ?? `${farm.farmCode}-${farm.farmName}`}>
                  <span>{index + 1}</span>
                  <div>
                    <strong>{farm.farmName}</strong>
                    <small>
                      {farm.farmCode ?? "-"} · {farm.fieldCount} talhões observados · TCH est. {formatShortNumber(farm.tch)}
                    </small>
                    <div className="harvestProgress" style={progressStyle(farm.totalNetWeight, maxFarmWeight)}>
                      <span />
                    </div>
                  </div>
                  <strong>{formatShortNumber(farm.totalNetWeight)} t</strong>
                </div>
              ))
            )}
          </div>
        </section>

        <section className="panel">
          <div className="sectionHeader">
            <div>
              <h2>Talhões com mais cana</h2>
              <span className="muted">Maior volume acumulado por talhão.</span>
            </div>
          </div>
          <div className="rankingList">
            {dashboard.topFields.length === 0 ? (
              <span className="muted">Sem talhões para listar.</span>
            ) : (
              dashboard.topFields.map((field, index) => (
                <div className="rankingRow" key={`${field.farmCode ?? field.farmName}-${field.fieldCode}`}>
                  <span>{index + 1}</span>
                  <div>
                    <strong>
                      {field.farmCode ?? "-"} · Talhão {field.fieldCode}
                    </strong>
                    <small>
                      {field.farmName} · {formatShortNumber(field.areaAlq)} alq cadastrados · TCH est. {formatShortNumber(field.tch)}
                    </small>
                    <div className="harvestProgress" style={progressStyle(field.totalNetWeight, maxFieldWeight)}>
                      <span />
                    </div>
                  </div>
                  <strong>{formatShortNumber(field.totalNetWeight)} t</strong>
                </div>
              ))
            )}
          </div>
        </section>
      </section>
    </div>
  );
}

function ProductionView({
  token,
  selectedYear,
  reloadKey,
  setMessage
}: {
  token: string;
  selectedYear: number | null;
  reloadKey: number;
  setMessage: (message: string | null) => void;
}) {
  const [dashboard, setDashboard] = useState<ProductionDashboard | null>(null);
  const [search, setSearch] = useState("");
  const [onlyDivergent, setOnlyDivergent] = useState(false);
  const [loading, setLoading] = useState(false);
  const [visibleRowCount, setVisibleRowCount] = useState(initialProductionRowLimit);
  const loadRequestIdRef = useRef(0);

  async function loadProduction() {
    const requestId = ++loadRequestIdRef.current;

    if (selectedYear === null) {
      setLoading(false);
      return;
    }

    setLoading(true);
    setMessage(null);

    try {
      const payload = await apiRequest<ProductionDashboard>(
        dashboardPathForYear("/dashboard/production", selectedYear),
        token
      );
      if (requestId === loadRequestIdRef.current) {
        setDashboard(payload);
      }
    } catch (error) {
      if (requestId === loadRequestIdRef.current) {
        setMessage(error instanceof Error ? error.message : "Falha ao carregar entradas por talhão.");
      }
    } finally {
      if (requestId === loadRequestIdRef.current) {
        setLoading(false);
      }
    }
  }

  useEffect(() => {
    setDashboard(null);
    void loadProduction();
    return () => {
      loadRequestIdRef.current += 1;
    };
  }, [reloadKey, selectedYear, token]);

  const deferredSearch = useDeferredValue(search);
  const searchTerms = useMemo(() => createSearchTerms(deferredSearch), [deferredSearch]);
  const rowSearchIndex = useMemo(
    () =>
      (dashboard?.rows ?? []).map((row) => ({
        row,
        searchText: buildSearchText([row.farmCode, row.farmName, row.fieldCode, row.fieldName])
      })),
    [dashboard]
  );
  const rows = useMemo(() => {
    const source = dashboard?.rows ?? [];

    const searchedRows =
      searchTerms.length === 0
        ? source
        : rowSearchIndex.filter((item) => matchesSearchText(item.searchText, searchTerms)).map((item) => item.row);

    return onlyDivergent
      ? searchedRows.filter((row) => row.divergentCount > 0 || row.divergentNetWeight > 0)
      : searchedRows;
  }, [dashboard, onlyDivergent, rowSearchIndex, searchTerms]);
  const visibleRows = useMemo(() => rows.slice(0, visibleRowCount), [rows, visibleRowCount]);

  useEffect(() => {
    setVisibleRowCount(initialProductionRowLimit);
  }, [dashboard?.rows.length, onlyDivergent, searchTerms]);

  if (selectedYear === null) {
    return <div className="emptyState">Carregando safras...</div>;
  }

  if (!dashboard) {
    return <div className="emptyState">{loading ? "Carregando entradas por talhão..." : "Nenhuma base carregada."}</div>;
  }

  return (
    <div className="stack productionView">
      <section className="metricsGrid productionMetricGrid">
        <Metric label="Fazendas observadas" value={dashboard.totals.farms} />
        <Metric label="Talhões observados" value={dashboard.totals.fields} />
        <Metric label="Entradas" value={dashboard.totals.entries} />
        <Metric label="Cana entregue" value={formatNumber(dashboard.totals.totalNetWeight)} tone="info" />
        <Metric label="Peso com pendência" value={formatNumber(dashboard.totals.divergentNetWeight)} tone="danger" />
      </section>

      <section className="panel productionPeriodPanel">
        <div className="sectionHeader">
          <div>
            <h2>Por data do PDF</h2>
            <span className="muted">Cada linha soma o que entrou naquele período do relatório.</span>
          </div>
          <button className="secondaryButton compactButton" type="button" onClick={loadProduction} disabled={loading}>
            <RefreshCw size={16} />
            {loading ? "Atualizando" : "Atualizar base"}
          </button>
        </div>
        <div className="tableWrap">
          <table className="productionPeriodTable">
            <thead>
              <tr>
                <th>Data PDF</th>
                <th>Fazendas observadas</th>
                <th>Talhões observados</th>
                <th>Entradas</th>
                <th>Cana entregue</th>
                <th>Peso com pendência</th>
              </tr>
            </thead>
            <tbody>
              {dashboard.periods.length === 0 ? (
                <tr>
                  <td colSpan={6}>Insira PDFs no Resultado para formar a base.</td>
                </tr>
              ) : (
                dashboard.periods.map((period) => (
                  <tr key={`${period.periodStart ?? "sem-data"}-${period.periodEnd ?? ""}`}>
                    <td>{formatProductionPeriod(period.periodStart, period.periodEnd)}</td>
                    <td>{period.farmCount}</td>
                    <td>{period.fieldCount}</td>
                    <td>{period.entryCount}</td>
                    <td>{formatNumber(period.totalNetWeight)}</td>
                    <td>{formatNumber(period.divergentNetWeight)}</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </section>

      <section className="panel productionRowsPanel">
        <div className="sectionHeader">
          <div>
            <h2>Base por fazenda e talhão</h2>
            <span className="muted">
              Mostrando {visibleRows.length} de {rows.length} talhão{rows.length === 1 ? "" : "ões"}.
            </span>
          </div>
          <button
            className={`secondaryButton compactButton ${onlyDivergent ? "activeToggle" : ""}`}
            type="button"
            onClick={() => setOnlyDivergent((current) => !current)}
          >
            <AlertTriangle size={16} />
            Somente com pendência
          </button>
          <label className="searchField">
            <Search size={18} />
            <input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Buscar fazenda ou talhão" />
          </label>
        </div>
        <div className="tableWrap">
          <table className="productionTable">
            <thead>
              <tr>
                <th>Fazenda</th>
                <th>Talhão</th>
                <th>Entradas</th>
                <th>Cana entregue</th>
                <th>Peso com pendência</th>
                <th>Alq cadastrados</th>
                <th>Período</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {rows.length === 0 ? (
                <tr>
                  <td colSpan={8}>Nenhum talhão encontrado.</td>
                </tr>
              ) : (
                visibleRows.map((row) => (
                  <tr key={`${row.farmId ?? row.farmName}-${row.fieldId ?? row.fieldCode}`}>
                    <td>
                      <div className="tableCellStack">
                        <strong>{row.farmName}</strong>
                        <span>{row.farmCode ?? "-"}</span>
                      </div>
                    </td>
                    <td>{row.fieldCode}</td>
                    <td>{row.entryCount}</td>
                    <td>{formatNumber(row.totalNetWeight)}</td>
                    <td>{formatNumber(row.divergentNetWeight)}</td>
                    <td>{formatShortNumber(row.areaAlq)}</td>
                    <td>{formatProductionPeriod(row.firstReportDate, row.lastReportDate)}</td>
                    <td>
                      <span className={`statusBadge ${row.divergentCount > 0 ? "warning" : "ok"}`}>
                        {row.divergentCount > 0 ? `${row.divergentCount} pend.` : "OK"}
                      </span>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
        {visibleRows.length < rows.length ? (
          <div className="tableFooter">
            <button
              className="secondaryButton compactButton"
              type="button"
              onClick={() => setVisibleRowCount((count) => Math.min(count + productionRowStep, rows.length))}
            >
              Mostrar mais talhões ({visibleRows.length} de {rows.length})
            </button>
          </div>
        ) : null}
      </section>
    </div>
  );
}

function FarmsView({
  farms,
  token,
  onSaved,
  setMessage
}: {
  farms: Farm[];
  token: string;
  onSaved: () => Promise<void>;
  setMessage: (message: string | null) => void;
}) {
  const [name, setName] = useState("");
  const [code, setCode] = useState("");
  const [ownerName, setOwnerName] = useState("");
  const [municipality, setMunicipality] = useState("");


  const [fieldDrafts, setFieldDrafts] = useState<FieldDraft[]>(() => [createFieldDraft()]);
  const [successToast, setSuccessToast] = useState<string | null>(null);
  const [editingFarmId, setEditingFarmId] = useState<string | null>(null);
  const [editingFarmName, setEditingFarmName] = useState("");
  const [editingFarmCode, setEditingFarmCode] = useState("");
  const [editingFarmOwnerName, setEditingFarmOwnerName] = useState("");
  const [editingFarmMunicipality, setEditingFarmMunicipality] = useState("");


  const [editingFieldId, setEditingFieldId] = useState<string | null>(null);
  const [editingFieldCode, setEditingFieldCode] = useState("");
  const [editingFieldAreaAlq, setEditingFieldAreaAlq] = useState("");
  const [newFieldByFarm, setNewFieldByFarm] = useState<Record<string, string>>({});
  const [newFieldAreaAlqByFarm, setNewFieldAreaAlqByFarm] = useState<Record<string, string>>({});
  const [farmSearch, setFarmSearch] = useState("");
  const [expandedFarmIds, setExpandedFarmIds] = useState<Set<string>>(new Set());
  const [visibleFarmCount, setVisibleFarmCount] = useState(initialFarmRenderLimit);

  const farmOverview = useMemo(() => summarizeFarmRegistry(farms), [farms]);
  const deferredFarmSearch = useDeferredValue(farmSearch);
  const farmSearchTerms = useMemo(() => createSearchTerms(deferredFarmSearch), [deferredFarmSearch]);
  const farmSearchIndex = useMemo(() => farms.map(createFarmSearchEntry), [farms]);
  const filteredFarmEntries = useMemo(
    () =>
      farmSearchTerms.length > 0
        ? farmSearchIndex.filter((entry) => matchesSearchText(entry.fullText, farmSearchTerms))
        : farmSearchIndex,
    [farmSearchIndex, farmSearchTerms]
  );
  const filteredFarms = useMemo(() => filteredFarmEntries.map((entry) => entry.farm), [filteredFarmEntries]);
  const visibleFarmEntries = useMemo(
    () => filteredFarmEntries.slice(0, visibleFarmCount),
    [filteredFarmEntries, visibleFarmCount]
  );
  const filteredOverview = useMemo(() => summarizeFarmRegistry(filteredFarms), [filteredFarms]);

  useEffect(() => {
    setVisibleFarmCount(initialFarmRenderLimit);
  }, [farmSearchTerms, farms.length]);

  useEffect(() => {
    if (!successToast) {
      return undefined;
    }

    const timeout = window.setTimeout(() => setSuccessToast(null), 3600);
    return () => window.clearTimeout(timeout);
  }, [successToast]);

  function updateFieldDraft(id: string, patch: Partial<Omit<FieldDraft, "id">>) {
    setFieldDrafts((current) => current.map((draft) => (draft.id === id ? { ...draft, ...patch } : draft)));
  }

  function addFieldDraft() {
    setFieldDrafts((current) => [...current, createFieldDraft()]);
  }

  function removeFieldDraft(id: string) {
    setFieldDrafts((current) => {
      const next = current.filter((draft) => draft.id !== id);
      return next.length > 0 ? next : [createFieldDraft()];
    });
  }

  function toggleFarmFields(farmId: string) {
    setExpandedFarmIds((current) => {
      const next = new Set(current);

      if (next.has(farmId)) {
        next.delete(farmId);
      } else {
        next.add(farmId);
      }

      return next;
    });
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    setMessage(null);
    setSuccessToast(null);
    const parsedFields = parseFieldDrafts(fieldDrafts);

    if ("error" in parsedFields) {
      setMessage(parsedFields.error);
      return;
    }

    const sectionName = name.trim();







    try {
      await apiRequest("/farms", token, {
        method: "POST",
        body: JSON.stringify({
          name: sectionName,
          code: code.trim(),
          sectionName: sectionName,
          ownerName: ownerName.trim(),
          municipality: municipality.trim(),
          fields: parsedFields.fields
        })
      });
      setName("");
      setCode("");
      setOwnerName("");
      setMunicipality("");


      setFieldDrafts([createFieldDraft()]);
      await onSaved();
      setSuccessToast(`Seção ${sectionName} salva com sucesso.`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Falha ao salvar fazenda.");
    }
  }

  async function saveFarm(farm: Farm) {
    setMessage(null);
    const sectionName = editingFarmName.trim();



    if (!sectionName) {
      setMessage("Informe a seção.");
      return;
    }





    try {
      await apiRequest(`/farms/${farm.id}`, token, {
        method: "PUT",
        body: JSON.stringify({
          name: sectionName,
          code: editingFarmCode.trim(),
          sectionName: sectionName,
          ownerName: editingFarmOwnerName.trim(),
          municipality: editingFarmMunicipality.trim(),
        })
      });
      setEditingFarmId(null);
      await onSaved();
      setSuccessToast(`Seção ${sectionName} atualizada com sucesso.`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Falha ao editar fazenda.");
    }
  }

  async function exportFarmRegistry() {
    setMessage(null);

    try {
      await downloadFile("/farms/export.xlsx", token, "cadastro-fazendas-talhoes.xlsx");
      setMessage("Cadastro de fazendas e talhoes exportado.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Falha ao exportar cadastro.");
    }
  }

  async function addField(farm: Farm) {
    const nextCodes = parseFieldCodes(newFieldByFarm[farm.id] ?? "");
    const areaAlqText = newFieldAreaAlqByFarm[farm.id] ?? "";
    const areaAlq = parseAreaInput(areaAlqText);

    if (nextCodes.length === 0) {
      setMessage("Informe o talhao.");
      return;
    }

    if (areaAlqText.trim() && areaAlq === undefined) {
      setMessage("Informe um valor valido de alqueires.");
      return;
    }

    setMessage(null);

    try {
      for (const code of nextCodes) {
        await apiRequest(`/farms/${farm.id}/fields`, token, {
          method: "POST",
          body: JSON.stringify({ code, ...(areaAlq === undefined ? {} : { areaAlq }) })
        });
      }
      setNewFieldByFarm((current) => ({ ...current, [farm.id]: "" }));
      setNewFieldAreaAlqByFarm((current) => ({ ...current, [farm.id]: "" }));
      await onSaved();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Falha ao adicionar talhao.");
    }
  }

  async function saveField() {
    if (!editingFieldId) {
      return;
    }

    setMessage(null);
    const areaAlq = parseAreaInput(editingFieldAreaAlq);

    if (editingFieldAreaAlq.trim() && areaAlq === undefined) {
      setMessage("Informe um valor valido de alqueires.");
      return;
    }

    try {
      await apiRequest(`/farms/fields/${editingFieldId}`, token, {
        method: "PUT",
        body: JSON.stringify({ code: editingFieldCode, ...(areaAlq === undefined ? {} : { areaAlq }) })
      });
      setEditingFieldId(null);
      setEditingFieldAreaAlq("");
      await onSaved();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Falha ao editar talhao.");
    }
  }

  return (
    <div className="stack farmRegistryView">
      {successToast ? (
        <div className="toastStack" aria-live="polite" aria-atomic="true">
          <div className="toastMessage success" role="status">
            <CheckCircle2 size={18} />
            <span>{successToast}</span>
          </div>
        </div>
      ) : null}

      <div className="splitLayout farmSplitLayout">
        <section className="panel farmCreatePanel">
          <div className="sectionHeader">
            <div>
              <h2>Nova fazenda</h2>
            </div>
          </div>
          <form className="formGrid" onSubmit={submit}>
            <label>
              Seção
              <input value={name} onChange={(event) => setName(event.target.value)} required />
            </label>
            <label>
              Código
              <input value={code} onChange={(event) => setCode(event.target.value)} />
            </label>
            <label>
              Proprietário
              <input value={ownerName} onChange={(event) => setOwnerName(event.target.value)} />
            </label>
            <label>
              Município
              <input value={municipality} onChange={(event) => setMunicipality(event.target.value)} />
            </label>


            <div className="fieldDraftSection full">
              <div className="fieldDraftHeader">
                <span>Talhões</span>
                <button className="secondaryButton compactButton" type="button" onClick={addFieldDraft}>
                  Adicionar talhão
                </button>
              </div>
              <div className="fieldDraftList">
                {fieldDrafts.map((draft, index) => (
                  <div className="fieldDraftBlock" key={draft.id}>
                    <label className="fieldDraftSubBlock">
                      <span>Talhão {index + 1}</span>
                      <input
                        value={draft.code}
                        onChange={(event) => updateFieldDraft(draft.id, { code: event.target.value })}
                        placeholder="Ex.: 1"
                      />
                    </label>
                    <label className="fieldDraftSubBlock">
                      <span>Área alq</span>
                      <input
                        value={draft.areaAlq}
                        onChange={(event) => updateFieldDraft(draft.id, { areaAlq: event.target.value })}
                        inputMode="decimal"
                        placeholder="15,35"
                      />
                    </label>
                    <button
                      className="secondaryButton compactButton dangerButton fieldDraftRemoveButton"
                      type="button"
                      onClick={() => removeFieldDraft(draft.id)}
                      disabled={fieldDrafts.length === 1 && !draft.code.trim() && !draft.areaAlq.trim()}
                      title="Remover talhão"
                    >
                      <Trash2 size={15} />
                    </button>
                  </div>
                ))}
              </div>
            </div>
            <button className="primaryButton" type="submit">
              Salvar fazenda
            </button>
          </form>
        </section>

        <section className="panel registryPanel farmRegistryPanel">
          <div className="sectionHeader registryHeader">
            <div>
              <h2>Fazendas e talhões cadastrados</h2>
              <span className="muted">
                {farmSearchTerms.length > 0
                  ? `${filteredOverview.farmCount} de ${farmOverview.farmCount} fazendas`
                  : `${farmOverview.farmCount} fazendas cadastradas`}
              </span>
            </div>
            <label className="searchField">
              <Search size={17} />
              <input
                value={farmSearch}
                onChange={(event) => setFarmSearch(event.target.value)}
                placeholder="Buscar por fazenda, código ou talhão"
              />
            </label>
            <button className="secondaryButton" type="button" onClick={exportFarmRegistry}>
              <FileSpreadsheet size={17} />
              Exportar Excel
            </button>
          </div>

          <section className="registryStats">
            <div>
              <span>Fazendas</span>
              <strong>{filteredOverview.farmCount}</strong>
            </div>
            <div>
              <span>Talhões</span>
              <strong>{filteredOverview.fieldCount}</strong>
            </div>
            <div>
              <span>Área ha</span>
              <strong>{formatShortNumber(filteredOverview.areaHa)}</strong>
            </div>
            <div>
              <span>Área alq</span>
              <strong>{formatShortNumber(filteredOverview.areaAlq)}</strong>
            </div>
          </section>

          <div className="farmRegistry">
            {filteredFarms.length === 0 ? <span className="muted emptyState">Nenhuma fazenda encontrada.</span> : null}
            {visibleFarmEntries.map((entry) => {
              const farm = entry.farm;
              const termMatchesFarm = farmSearchTerms.length > 0 ? matchesSearchText(entry.headerText, farmSearchTerms) : false;
              const matchingFieldEntries =
                farmSearchTerms.length > 0 && !termMatchesFarm
                  ? entry.fields.filter((fieldEntry) => matchesSearchText(fieldEntry.searchText, farmSearchTerms))
                  : entry.fields;
              const fallbackFieldEntries =
                farmSearchTerms.length > 0 && !termMatchesFarm && matchingFieldEntries.length === 0
                  ? entry.fields.filter((fieldEntry) => matchesAnySearchTerm(fieldEntry.searchText, farmSearchTerms))
                  : [];
              const fieldsForView = (matchingFieldEntries.length > 0 ? matchingFieldEntries : fallbackFieldEntries).map(
                (fieldEntry) => fieldEntry.field
              );
              const isExpanded = expandedFarmIds.has(farm.id);
              const visibleFields = isExpanded ? fieldsForView : fieldsForView.slice(0, collapsedFieldPreviewLimit);
              const hiddenFieldCount = fieldsForView.length - visibleFields.length;
              const farmFieldSummary = summarizeFields(farm.fields);

              return (
                <article className="farmCard" key={farm.id}>
                  {editingFarmId === farm.id ? (
                    <div className="editBlock farmEditBlock">
                      <label>
                        Seção
                        <input value={editingFarmName} onChange={(event) => setEditingFarmName(event.target.value)} />
                      </label>
                      <label>
                        Código
                        <input value={editingFarmCode} onChange={(event) => setEditingFarmCode(event.target.value)} />
                      </label>
                      <label>
                        Proprietário
                        <input value={editingFarmOwnerName} onChange={(event) => setEditingFarmOwnerName(event.target.value)} />
                      </label>
                      <label>
                        Município
                        <input value={editingFarmMunicipality} onChange={(event) => setEditingFarmMunicipality(event.target.value)} />
                      </label>


                      <div className="rowActions">
                        <button className="primaryButton compactButton" type="button" onClick={() => saveFarm(farm)}>
                          Salvar
                        </button>
                        <button className="secondaryButton compactButton" type="button" onClick={() => setEditingFarmId(null)}>
                          Cancelar
                        </button>
                      </div>
                    </div>
                  ) : (
                    <div className="farmCardHeader">
                      <div className="farmIdentity">
                        <span className="farmCode">{farm.code || "sem codigo"}</span>
                        <strong>{farm.name}</strong>
                        <small>{formatFarmMetadataLine(farm)}</small>
                      </div>
                      <div className="farmNumbers">
                        <span>
                          <strong>{farm.fields.length}</strong> talhões
                        </span>
                        <span>{formatShortNumber(farmFieldSummary.areaHa)} ha</span>
                        <span>{formatShortNumber(farmFieldSummary.areaAlq)} alq</span>
                      </div>
                      <button
                        className="secondaryButton compactButton"
                        type="button"
                        onClick={() => {
                          setEditingFarmId(farm.id);
                          setEditingFarmName(farm.name);
                          setEditingFarmCode(farm.code ?? "");
                          setEditingFarmOwnerName(farm.ownerName ?? "");
                          setEditingFarmMunicipality(farm.municipality ?? farm.city ?? "");


                        }}
                      >
                        <Edit3 size={16} />
                        Editar
                      </button>
                    </div>
                  )}

                  <div className="farmFieldSection">
                    <div className="farmFieldSectionHeader">
                      <span>Talhões</span>
                      {farmSearchTerms.length > 0 && fieldsForView.length !== farm.fields.length ? (
                        <small>{fieldsForView.length} encontrados nesta fazenda</small>
                      ) : (
                        <small>{farm.fields.length} cadastrados</small>
                      )}
                    </div>

                    <div className="fieldGrid">
                      {visibleFields.length === 0 ? <span className="muted">Sem talhões cadastrados</span> : null}
                      {visibleFields.map((field) =>
                        editingFieldId === field.id ? (
                          <span className="fieldEditor fieldTileEditor" key={field.id}>
                            <input value={editingFieldCode} onChange={(event) => setEditingFieldCode(event.target.value)} />
                            <input
                              className="fieldAreaInput"
                              value={editingFieldAreaAlq}
                              onChange={(event) => setEditingFieldAreaAlq(event.target.value)}
                              inputMode="decimal"
                              placeholder="Alq"
                            />
                            <button className="primaryButton compactButton" type="button" onClick={saveField}>
                              Salvar
                            </button>
                            <button
                              className="secondaryButton compactButton"
                              type="button"
                              onClick={() => {
                                setEditingFieldId(null);
                                setEditingFieldAreaAlq("");
                              }}
                            >
                              Cancelar
                            </button>
                          </span>
                        ) : (
                          <button
                            className="fieldTile"
                            type="button"
                            key={field.id}
                            title={`Editar talhão ${field.code}`}
                            onClick={() => {
                              setEditingFieldId(field.id);
                              setEditingFieldCode(field.code);
                              setEditingFieldAreaAlq(formatAreaInput(field.areaAlq));
                            }}
                          >
                            <strong>{field.code}</strong>
                            <span>{field.areaHa === null || field.areaHa === undefined ? "sem área" : `${formatShortNumber(field.areaHa)} ha`}</span>
                            {field.areaAlq === null || field.areaAlq === undefined ? null : <small>{formatShortNumber(field.areaAlq)} alq</small>}
                          </button>
                        )
                      )}
                    </div>

                    {hiddenFieldCount > 0 || isExpanded ? (
                      <button className="secondaryButton compactButton expandFieldsButton" type="button" onClick={() => toggleFarmFields(farm.id)}>
                        <ChevronDown size={16} className={isExpanded ? "expandedIcon" : ""} />
                        {isExpanded ? "Mostrar menos" : `Mostrar mais ${hiddenFieldCount}`}
                      </button>
                    ) : null}
                  </div>

                  <div className="addFieldRow fieldDraftBlock addExistingFieldBlock">
                    <label className="fieldDraftSubBlock">
                      <span>Talhão</span>
                      <input
                        value={newFieldByFarm[farm.id] ?? ""}
                        onChange={(event) => setNewFieldByFarm((current) => ({ ...current, [farm.id]: event.target.value }))}
                        placeholder="Novo talhão"
                      />
                    </label>
                    <label className="fieldDraftSubBlock">
                      <span>Área alq</span>
                      <input
                        className="fieldAreaInput"
                        value={newFieldAreaAlqByFarm[farm.id] ?? ""}
                        onChange={(event) => setNewFieldAreaAlqByFarm((current) => ({ ...current, [farm.id]: event.target.value }))}
                        inputMode="decimal"
                        placeholder="Alqueires"
                      />
                    </label>
                    <button className="secondaryButton" type="button" onClick={() => addField(farm)}>
                      Adicionar
                    </button>
                  </div>
                </article>
              );
            })}
            {visibleFarmEntries.length < filteredFarms.length ? (
              <div className="farmRegistryFooter">
                <button
                  className="secondaryButton compactButton"
                  type="button"
                  onClick={() => setVisibleFarmCount((count) => Math.min(count + farmRenderStep, filteredFarms.length))}
                >
                  Mostrar mais fazendas ({visibleFarmEntries.length} de {filteredFarms.length})
                </button>
              </div>
            ) : null}
          </div>
        </section>
      </div>
    </div>
  );
}

function OrdersView({
  farms,
  orders,
  orderHistory,
  token,
  onSaved,
  canManage,
  setMessage
}: {
  farms: Farm[];
  orders: HarvestOrder[];
  orderHistory: HarvestOrderHistory[];
  token: string;
  onSaved: () => Promise<void>;
  canManage: boolean;
  setMessage: (message: string | null) => void;
}) {
  const [osNumber, setOsNumber] = useState("");
  const [frontNumbers, setFrontNumbers] = useState<string[]>([]);
  const [farmId, setFarmId] = useState("");
  const [fieldIds, setFieldIds] = useState<string[]>([]);
  const [farmChangePrompt, setFarmChangePrompt] = useState<{ previousFarmIds: string[]; nextFarmId: string } | null>(null);
  const [editingOrderId, setEditingOrderId] = useState<string | null>(null);
  const [ordersTab, setOrdersTab] = useState<"overview" | "registry" | "check" | "closed">("overview");
  const [busy, setBusy] = useState(false);
  const [fieldSearch, setFieldSearch] = useState("");
  const [farmSearch, setFarmSearch] = useState("");
  const [farmSearchOpen, setFarmSearchOpen] = useState(false);
  const [orderSearch, setOrderSearch] = useState("");
  const [closedOrderSearch, setClosedOrderSearch] = useState("");

























  const harvestFormPanelRef = useRef<HTMLElement | null>(null);



  const selectedFarm = useMemo(() => farms.find((farm) => farm.id === farmId), [farms, farmId]);
  const selectedFarmSummary = useMemo(() => summarizeFields(selectedFarm?.fields ?? []), [selectedFarm]);
  const allFields = useMemo(() => farms.flatMap((farm) => farm.fields), [farms]);
  const editingOrder = useMemo(() => orders.find((o) => o.id === editingOrderId) ?? null, [orders, editingOrderId]);
  const fieldFarmIdById = useMemo(() => new Map(allFields.map((field) => [field.id, field.farmId])), [allFields]);
  const selectedFieldIdSet = useMemo(() => new Set(fieldIds), [fieldIds]);
  const selectedFields = useMemo(
    () => allFields.filter((field) => selectedFieldIdSet.has(field.id)),
    [allFields, selectedFieldIdSet]
  );
  const selectedFarmIdSet = useMemo(() => new Set(selectedFields.map((field) => field.farmId)), [selectedFields]);
  const selectedFarms = useMemo(
    () => farms.filter((farm) => selectedFarmIdSet.has(farm.id)),
    [farms, selectedFarmIdSet]
  );
  const selectedFieldSummary = useMemo(() => summarizeFields(selectedFields), [selectedFields]);
  const deferredFarmSearch = useDeferredValue(farmSearch);
  const farmSearchTerms = useMemo(() => createSearchTerms(deferredFarmSearch), [deferredFarmSearch]);
  const deferredFieldSearch = useDeferredValue(fieldSearch);
  const fieldSearchTerms = useMemo(() => createSearchTerms(deferredFieldSearch), [deferredFieldSearch]);
  const selectedFarmFieldSearchIndex = useMemo(
    () =>
      (selectedFarm?.fields ?? []).map((field) => ({
        field,
        searchText: buildFieldSearchText(field)
      })),
    [selectedFarm]
  );
  const selectableFields = useMemo(
    () =>
      fieldSearchTerms.length > 0
        ? selectedFarmFieldSearchIndex
            .filter((fieldEntry) => matchesSearchText(fieldEntry.searchText, fieldSearchTerms))
            .map((fieldEntry) => fieldEntry.field)
        : selectedFarmFieldSearchIndex.map((fieldEntry) => fieldEntry.field),
    [fieldSearchTerms, selectedFarmFieldSearchIndex]
  );
  const selectableFieldIds = useMemo(() => selectableFields.map((field) => field.id), [selectableFields]);
  const allVisibleFieldsSelected =
    selectableFieldIds.length > 0 && selectableFieldIds.every((id) => selectedFieldIdSet.has(id));
  const selectedFrontNumbers = useMemo(
    () => frontNumbers.map((item) => Number(item)).filter((item) => Number.isInteger(item)).sort((left, right) => left - right),
    [frontNumbers]
  );
  const activeOrders = useMemo(() => {
    return orders
      .filter((order) => order.status === "ACTIVE")
      .sort((left, right) => compareFrontNumbers(getOrderFrontNumbers(left)[0], getOrderFrontNumbers(right)[0]));
  }, [orders]);
  const harvestingOrders = useMemo(() => activeOrders.filter((order) => getOrderFrontNumbers(order).length > 0), [activeOrders]);
  const releasedOrders = useMemo(() => activeOrders.filter((order) => getOrderFrontNumbers(order).length === 0), [activeOrders]);
  const orderSearchTerms = useMemo(() => createSearchTerms(orderSearch), [orderSearch]);
  const filteredHarvestingOrders = useMemo(() => {
    if (orderSearchTerms.length === 0) {
      return harvestingOrders;
    }

    return harvestingOrders.filter((order) =>
      matchesSearchText(
        buildSearchText([
          order.number,
          formatFrontNumbers(getOrderFrontNumbers(order)),
          formatOrderFarmNames(order),
          getOrderFarms(order).map((farm) => formatFarmLabel(farm)).join(" "),
          order.fields.map((item) => item.field.code).join(" ")
        ]),
        orderSearchTerms
      )
    );
  }, [harvestingOrders, orderSearchTerms]);
  const filteredReleasedOrders = useMemo(() => {
    if (orderSearchTerms.length === 0) {
      return releasedOrders;
    }

    return releasedOrders.filter((order) =>
      matchesSearchText(
        buildSearchText([
          order.number,
          "sem frente",
          formatOrderFarmNames(order),
          getOrderFarms(order).map((farm) => formatFarmLabel(farm)).join(" "),
          order.fields.map((item) => item.field.code).join(" ")
        ]),
        orderSearchTerms
      )
    );
  }, [orderSearchTerms, releasedOrders]);
  const closedOrders = useMemo(() => {
    return orders
      .filter((order) => order.status === "CLOSED")
      .sort((left, right) => parseDateSortValue(left.endDate) - parseDateSortValue(right.endDate) || left.number.localeCompare(right.number, "pt-BR", { numeric: true }));
  }, [orders]);
  const deferredClosedOrderSearch = useDeferredValue(closedOrderSearch);
  const closedOrderSearchTerms = useMemo(() => createSearchTerms(deferredClosedOrderSearch), [deferredClosedOrderSearch]);
  const closedOrderRows = useMemo(() => {
    return closedOrders.flatMap((order) =>
      getOrderFarmFieldGroups(order).map((group) => {

        const frontNumbers = formatFrontNumbers(getOrderFrontNumbers(order));
        const fields = group.fields.join(", ");

        return {
          order,
          group,
          searchText: buildSearchText([
            order.number,
            order.endDate,
            order.endDate ? formatDateTime(order.endDate) : undefined,
            frontNumbers,
            formatFarmLabel(group.farm),
            group.farm.code,
            group.farm.name,
            fields
          ])
        };
      })
    );
  }, [closedOrders]);
  const filteredClosedOrderRows = useMemo(() => {
    if (closedOrderSearchTerms.length === 0) {
      return closedOrderRows;
    }

    return closedOrderRows.filter((row) => matchesSearchText(row.searchText, closedOrderSearchTerms));
  }, [closedOrderRows, closedOrderSearchTerms]);
  const activeSummary = useMemo(() => summarizeActiveOrders(harvestingOrders), [harvestingOrders]);












  const sortedHarvestFarms = useMemo(() => [...farms].sort(compareFarmsByCode), [farms]);
  const harvestFarmSearchIndex = useMemo(
    () =>
      sortedHarvestFarms.map((farm) => ({
        farm,
        label: formatFarmLabel(farm),
        searchText: buildFarmHeaderSearchText(farm)
      })),
    [sortedHarvestFarms]
  );
  const filteredHarvestFarmEntries = useMemo(() => {
    const matches =
      farmSearchTerms.length > 0
        ? harvestFarmSearchIndex.filter((entry) => matchesSearchText(entry.searchText, farmSearchTerms))
        : harvestFarmSearchIndex;
    const limitedMatches = matches.slice(0, 12);

    if (!selectedFarm || farmSearchTerms.length > 0 || limitedMatches.some((entry) => entry.farm.id === selectedFarm.id)) {
      return limitedMatches;
    }

    const selectedEntry = harvestFarmSearchIndex.find((entry) => entry.farm.id === selectedFarm.id);
    return selectedEntry ? [selectedEntry, ...limitedMatches].slice(0, 12) : limitedMatches;
  }, [farmSearchTerms, harvestFarmSearchIndex, selectedFarm]);
  const activeFrontConflicts = useMemo(
    () => {
      if (editingOrder?.status === "CLOSED") {
        return [];
      }
      return selectedFrontNumbers
        .map((frontNumber) => ({
          frontNumber,
          order:
            orders.find(
              (order) =>
                order.status === "ACTIVE" && getOrderFrontNumbers(order).includes(frontNumber) && order.id !== editingOrderId
            ) ?? null
        }))
        .filter((item): item is { frontNumber: number; order: HarvestOrder } => Boolean(item.order));
    },
    [editingOrder?.status, editingOrderId, orders, selectedFrontNumbers]
  );
  const fieldReuseWarnings = useMemo(
    () => buildFieldReuseWarnings(orders, fieldIds, selectedFrontNumbers, editingOrderId),
    [editingOrderId, fieldIds, orders, selectedFrontNumbers]
  );



















  async function submit(event: FormEvent) {
    event.preventDefault();
    setMessage(null);

    if (!selectedFarm) {
      setMessage("Selecione a fazenda.");
      return;
    }

    const normalizedOsNumber = osNumber.trim();

    if (!normalizedOsNumber) {
      setMessage("Informe o numero da OS.");
      return;
    }

    const matchingOrder = findActiveOrderByNumber(activeOrders, normalizedOsNumber);

    if (!editingOrderId && matchingOrder) {
      loadOrderIntoForm(matchingOrder);
      setMessage(`OS ${matchingOrder.number} carregada para edicao.`);
      return;
    }

    if (fieldIds.length === 0) {
      setMessage("Selecione pelo menos um talhao.");
      return;
    }

    if (activeFrontConflicts.length > 0) {
      const conflict = activeFrontConflicts[0];
      setMessage(`Frente ${conflict.frontNumber} ja esta em colheita na OS ${conflict.order.number}.`);
      return;
    }

    try {
      setBusy(true);
      const payload = await apiRequest<{ order: HarvestOrder }>(editingOrderId ? `/orders/${editingOrderId}` : "/orders", token, {
        method: editingOrderId ? "PUT" : "POST",
        body: JSON.stringify({
          number: normalizedOsNumber,
          frontNumber: selectedFrontNumbers[0],
          frontNumbers: selectedFrontNumbers,
          farmId: selectedFarms[0]?.id ?? farmId,
          fieldIds
        })
      });
      const savedOrder = payload.order;

      resetOrderForm();
      await onSaved();
      setMessage("Colheita salva com sucesso.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Falha ao salvar talhoes em colheita.");
    } finally {
      setBusy(false);
    }
  }

  function resetOrderForm() {
    setEditingOrderId(null);
    setOsNumber("");
    setFrontNumbers([]);
    setFarmId("");
    setFieldIds([]);
    setFarmChangePrompt(null);
    setFarmSearch("");
    setFarmSearchOpen(false);
    setFieldSearch("");
  }

  function loadOrderIntoForm(order: HarvestOrder) {
    const firstFarm = getOrderFarms(order)[0];

    setMessage(null);
    setEditingOrderId(order.id);
    setOsNumber(order.number);
    setFrontNumbers(getOrderFrontNumbers(order).map(String));
    setFarmId(firstFarm?.id ?? order.farmId);
    setFieldIds(order.fields.map((item) => item.fieldId));
    setFarmChangePrompt(null);
    setFarmSearch(firstFarm ? formatFarmLabel(firstFarm) : "");
    setFarmSearchOpen(false);
    setFieldSearch("");
  }

  function startEdit(order: HarvestOrder, options: { scrollToForm?: boolean } = {}) {
    loadOrderIntoForm(order);

    if (options.scrollToForm) {
      setOrdersTab("registry");
      requestAnimationFrame(() => {
        harvestFormPanelRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
      });
    }
  }

  function changeFarm(nextFarmId: string) {
    const previousFarmIds = Array.from(new Set(selectedFields.map((field) => field.farmId))).filter((id) => id !== nextFarmId);
    const selectedNextFarmFields = selectedFields.some((field) => field.farmId === nextFarmId);

    if (editingOrderId && nextFarmId && previousFarmIds.length > 0 && !selectedNextFarmFields && nextFarmId !== farmId) {
      setFarmChangePrompt({ previousFarmIds, nextFarmId });
    } else {
      setFarmChangePrompt(null);
    }

    setFarmId(nextFarmId);
    setFieldSearch("");
  }

  function selectHarvestFarm(farm: Farm) {
    changeFarm(farm.id);
    setFarmSearch(formatFarmLabel(farm));
    setFarmSearchOpen(false);
  }

  function handleFarmSearchChange(value: string) {
    setFarmSearch(value);
    setFarmSearchOpen(true);

    if (!value.trim()) {
      setFarmId("");
      setFarmChangePrompt(null);
      setFieldSearch("");
      return;
    }

    if (selectedFarm && normalizeSearchText(value) !== normalizeSearchText(formatFarmLabel(selectedFarm))) {
      setFarmId("");
      setFarmChangePrompt(null);
      setFieldSearch("");
    }
  }

  function commitFarmSearch() {
    const normalizedSearch = normalizeSearchText(farmSearch);

    if (!normalizedSearch) {
      setFarmSearchOpen(false);
      return;
    }

    const currentTerms = createSearchTerms(farmSearch);
    const currentMatches =
      currentTerms.length > 0
        ? harvestFarmSearchIndex.filter((entry) => matchesSearchText(entry.searchText, currentTerms))
        : harvestFarmSearchIndex;
    const exactFarm = sortedHarvestFarms.find((farm) =>
      [farm.code, farm.name, formatFarmLabel(farm)].some((value) => value && normalizeSearchText(value) === normalizedSearch)
    );
    const singleMatch = currentMatches.length === 1 ? currentMatches[0].farm : null;
    const nextFarm = exactFarm ?? singleMatch;

    if (nextFarm) {
      selectHarvestFarm(nextFarm);
      return;
    }

    setFarmSearchOpen(false);
  }

  function handleFarmSearchKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === "Enter" && farmSearchOpen && filteredHarvestFarmEntries.length > 0) {
      event.preventDefault();
      selectHarvestFarm(filteredHarvestFarmEntries[0].farm);
      return;
    }

    if (event.key === "Escape") {
      setFarmSearchOpen(false);
    }
  }

  function keepPreviousFarmSelection() {
    setFarmChangePrompt(null);
    setMessage("Fazendas antigas mantidas. Selecione os talhões da nova fazenda para somar nesta OS.");
  }

  function replacePreviousFarmSelection() {
    if (!farmChangePrompt) {
      return;
    }

    setFieldIds((current) =>
      current.filter((fieldId) => fieldFarmIdById.get(fieldId) === farmChangePrompt.nextFarmId)
    );
    setFarmChangePrompt(null);
    setMessage("Fazendas antigas removidas desta OS. Selecione os talhões da fazenda atual.");
  }

  function removeFarmFromOrder(farmIdToRemove: string) {
    setFieldIds((current) => current.filter((fieldId) => fieldFarmIdById.get(fieldId) !== farmIdToRemove));

    if (farmId === farmIdToRemove) {
      setFarmId("");
      setFarmSearch("");
      setFarmSearchOpen(false);
      setFieldSearch("");
    }

    setFarmChangePrompt(null);
  }

  function loadMatchingOrderByNumber() {
    if (editingOrderId) {
      return;
    }

    const matchingOrder = findActiveOrderByNumber(activeOrders, osNumber);

    if (!matchingOrder) {
      return;
    }

    loadOrderIntoForm(matchingOrder);
    setMessage(`OS ${matchingOrder.number} carregada para edicao.`);
  }

  function toggleFrontNumber(value: string, checked: boolean) {
    setFrontNumbers((current) => {
      if (checked) {
        return Array.from(new Set([...current, value])).sort((left, right) => Number(left) - Number(right));
      }

      return current.filter((item) => item !== value);
    });
  }

  function selectAllFields() {
    setFieldIds((current) => Array.from(new Set([...current, ...selectableFieldIds])));
  }

  function clearSelectedFields() {
    setFieldIds([]);
    setFarmChangePrompt(null);
  }

  async function closeHarvestOrder(order: HarvestOrder) {
    const frontNumbersForOrder = getOrderFrontNumbers(order);
    const confirmation = frontNumbersForOrder.length
      ? `Finalizar a colheita da ${formatFrontNumbers(frontNumbersForOrder)} na OS ${order.number}?`
      : `Finalizar a OS liberada ${order.number} sem frente aplicada?`;

    if (!window.confirm(confirmation)) {
      return;
    }

    try {
      setBusy(true);
      await apiRequest(`/orders/${order.id}/close`, token, { method: "PATCH" });
      if (editingOrderId === order.id) {
        resetOrderForm();
      }
      await onSaved();
      setMessage("Colheita finalizada.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Falha ao finalizar colheita.");
    } finally {
      setBusy(false);
    }
  }

  async function reopenHarvestOrder(order: HarvestOrder) {
    const frontNumbersForOrder = getOrderFrontNumbers(order);
    const confirmation = frontNumbersForOrder.length
      ? `Reabrir a OS ${order.number} na ${formatFrontNumbers(frontNumbersForOrder)}?`
      : `Reabrir a OS ${order.number} sem frente aplicada?`;

    if (!window.confirm(confirmation)) {
      return;
    }

    try {
      setBusy(true);
      await apiRequest(`/orders/${order.id}/reopen`, token, { method: "PATCH" });
      await onSaved();
      setOrdersTab("overview");
      setMessage(`OS ${order.number} reaberta.`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Falha ao reabrir OS.");
    } finally {
      setBusy(false);
    }
  }

  async function removeHarvestOrder(order: HarvestOrder) {
    if (!window.confirm(`Excluir a colheita da OS ${order.number}?`)) {
      return;
    }

    try {
      setBusy(true);
      await apiRequest(`/orders/${order.id}`, token, { method: "DELETE" });
      if (editingOrderId === order.id) {
        resetOrderForm();
      }
      await onSaved();
      setMessage("Colheita excluida.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Falha ao excluir colheita.");
    } finally {
      setBusy(false);
    }
  }

  async function removeFrontFromOrder(order: HarvestOrder, frontNumber: number) {
    const currentFrontNumbers = getOrderFrontNumbers(order);
    const nextFrontNumbers = currentFrontNumbers.filter((item) => item !== frontNumber);

    if (currentFrontNumbers.length <= 1) {
      setMessage("Essa OS tem apenas uma frente. Use editar para deixar a OS liberada sem frente ou finalize a colheita.");
      return;
    }

    if (!window.confirm(`Retirar a Frente ${frontNumber} da OS ${order.number}? As demais frentes continuam no mesmo grupo.`)) {
      return;
    }

    try {
      setBusy(true);
      await apiRequest(`/orders/${order.id}`, token, {
        method: "PUT",
        body: JSON.stringify({
          number: order.number,
          frontNumber: nextFrontNumbers[0],
          frontNumbers: nextFrontNumbers,
          farmId: getOrderFarms(order)[0]?.id ?? order.farmId,
          fieldIds: order.fields.map((item) => item.fieldId)
        })
      });

      if (editingOrderId === order.id) {
        setFrontNumbers(nextFrontNumbers.map(String));
      }

      await onSaved();
      setMessage(`Frente ${frontNumber} retirada da OS ${order.number}.`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Falha ao retirar frente da OS.");
    } finally {
      setBusy(false);
    }
  }

  async function clearOrderFronts(order: HarvestOrder) {
    if (!window.confirm(`Retirar todas as frentes da OS ${order.number} e deixar apenas liberada para colher?`)) {
      return;
    }

    try {
      setBusy(true);
      await apiRequest(`/orders/${order.id}`, token, {
        method: "PUT",
        body: JSON.stringify({
          number: order.number,
          frontNumbers: [],
          farmId: getOrderFarms(order)[0]?.id ?? order.farmId,
          fieldIds: order.fields.map((item) => item.fieldId)
        })
      });

      if (editingOrderId === order.id) {
        setFrontNumbers([]);
      }

      await onSaved();
      setMessage(`OS ${order.number} ficou liberada sem frente.`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Falha ao retirar frentes da OS.");
    } finally {
      setBusy(false);
    }
  }

  async function exportHarvestReport() {
    setMessage(null);

    try {
      await downloadFile("/orders/report.pdf", token, "relatorio-fazendas-colheita.pdf");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Falha ao gerar relatorio de fazendas.");
    }
  }

  async function exportHarvestSummaryReport() {
    setMessage(null);

    try {
      await downloadFile("/orders/summary-report.pdf", token, "relatorio-resumido-fazendas.pdf");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Falha ao gerar relatorio resumido.");
    }
  }

  async function exportWhatsAppReport() {
    setMessage(null);
    const lines: string[] = [];

    const sortedOrders = [...harvestingOrders].sort((a, b) => {
      const fA = getOrderFrontNumbers(a)[0] ?? 999;
      const fB = getOrderFrontNumbers(b)[0] ?? 999;
      return fA - fB;
    });

    for (const order of sortedOrders) {
      const fronts = getOrderFrontNumbers(order).map(f => `F${f}`).join(", ");
      const farms = order.farms?.length ? order.farms : (order.farm ? [order.farm] : []);

      for (const farm of farms) {
        lines.push(`*${fronts}* - ${farm.name}`);

        lines.push("");
      }
    }

    const today = new Date();
    const formattedDate = today.toLocaleDateString("pt-BR", { day: "2-digit", month: "2-digit", year: "numeric" });
    const text = `*Frentes Atuais - Colheita - ${formattedDate}*\n\n` + lines.join("\n");

    try {
      await navigator.clipboard.writeText(text);
      setMessage("Relatório copiado! Você também pode colar diretamente se a janela não abrir.");
    } catch (err) {
      // Ignore clipboard error
    }

    window.open('https://api.whatsapp.com/send?text=' + encodeURIComponent(text.trim()), '_blank');
  }













































  return (
    <div className="ordersWorkspace">

      <div className="ordersSubtabs" role="tablist" aria-label="Colheita atual">
        <button
          className={ordersTab === "overview" ? "active" : ""}
          type="button"
          role="tab"
          aria-selected={ordersTab === "overview"}
          onClick={() => setOrdersTab("overview")}
        >
          <span>Frentes atuais</span>
        </button>
        <button
          className={ordersTab === "registry" ? "active" : ""}
          type="button"
          role="tab"
          aria-selected={ordersTab === "registry"}
          onClick={() => setOrdersTab("registry")}
        >
          <span>{editingOrderId ? "Editar OS" : "Cadastro de OS"}</span>
        </button>

        <button
          className={ordersTab === "check" ? "active" : ""}
          type="button"
          role="tab"
          aria-selected={ordersTab === "check"}
          onClick={() => setOrdersTab("check")}
        >
          <span>Conferir PDF</span>
        </button>
        <button
          className={ordersTab === "closed" ? "active" : ""}
          type="button"
          role="tab"
          aria-selected={ordersTab === "closed"}
          onClick={() => setOrdersTab("closed")}
        >
          <span>Encerradas</span>
        </button>
      </div>



      {ordersTab === "registry" ? (
      <section className="panel harvestFormPanel" ref={harvestFormPanelRef}>
        <div className="sectionHeader harvestFormHeader">
          <div>
            <h2>{editingOrderId ? "Editar colheita" : "Registrar colheita atual"}</h2>
            <span className="muted">
              {selectedFarm ? `${selectedFarm.fields.length} talhões disponíveis na fazenda` : "Selecione a fazenda para carregar os talhões"}
            </span>
          </div>
          {editingOrder?.status === "CLOSED" ? (
            <span className="statusBadge closed">Encerrada</span>
          ) : editingOrderId ? (
            <span className="statusBadge open">Editando</span>
          ) : null}
        </div>

        <form className="formGrid harvestForm" onSubmit={submit}>
          <label>
            Numero da OS
            <input
              value={osNumber}
              onChange={(event) => setOsNumber(event.target.value)}
              onBlur={loadMatchingOrderByNumber}
              placeholder="Ex.: 12345"
              required
            />
          </label>
          <div className="frontSelection full">
            <strong>Frentes em colheita</strong>
            <span className="muted">Opcional: sem frente marcada, a OS fica aberta e liberada para colher.</span>
            <div className="frontSelectionGrid">
              {Array.from({ length: 14 }, (_, index) => String(index + 1)).map((item) => {
                const selected = frontNumbers.includes(item);

                return (
                  <label className={`frontCheckTile ${selected ? "selected" : ""}`} key={item}>
                    <input type="checkbox" checked={selected} onChange={(event) => toggleFrontNumber(item, event.target.checked)} />
                    <span>{item}</span>
                  </label>
                );
              })}
            </div>
          </div>
          <div className="full harvestFarmSearchBlock">
            <label htmlFor="harvestFarmSearch">Fazenda para adicionar talhões</label>
            <label className="searchField harvestFarmSearchField" htmlFor="harvestFarmSearch">
              <Search size={16} />
              <input
                id="harvestFarmSearch"
                type="search"
                value={farmSearch}
                onChange={(event) => handleFarmSearchChange(event.target.value)}
                onFocus={() => setFarmSearchOpen(true)}
                onBlur={commitFarmSearch}
                onKeyDown={handleFarmSearchKeyDown}
                placeholder="Buscar por codigo ou nome"
                autoComplete="off"
                aria-expanded={farmSearchOpen}
                aria-controls="harvestFarmResults"
                required
              />
            </label>
            {farmSearchOpen ? (
              <div className="harvestFarmResults" id="harvestFarmResults" role="listbox">
                {filteredHarvestFarmEntries.length === 0 ? (
                  <span className="muted emptyState">Nenhuma fazenda encontrada.</span>
                ) : null}
                {filteredHarvestFarmEntries.map(({ farm }) => {
                  const selected = farm.id === farmId;
                  const summary = summarizeFields(farm.fields);

                  return (
                    <button
                      className={`harvestFarmResult ${selected ? "selected" : ""}`}
                      type="button"
                      role="option"
                      aria-selected={selected}
                      key={farm.id}
                      onMouseDown={(event) => event.preventDefault()}
                      onClick={() => selectHarvestFarm(farm)}
                    >
                      <span className="harvestFarmResultMain">
                        <span className="farmCode">{farm.code || "sem codigo"}</span>
                        <strong>{farm.name}</strong>
                        <small>{formatFarmMetadataLine(farm)}</small>
                      </span>
                      <span className="harvestFarmResultMeta">
                        <span>{farm.fields.length} talhões</span>
                        <span>{formatShortNumber(summary.areaHa)} ha</span>
                      </span>
                    </button>
                  );
                })}
              </div>
            ) : null}
          </div>

          {selectedFarm ? (
            <section className="full selectedHarvestFarm">
              <div>
                <span className="farmCode">{selectedFarm.code || "sem codigo"}</span>
                <strong>{selectedFarm.name}</strong>
              </div>
              <div className="farmNumbers">
                <span>
                  <strong>{selectedFarm.fields.length}</strong> talhões
                </span>
                <span>{formatShortNumber(selectedFarmSummary.areaHa)} ha</span>
                <span>{formatShortNumber(selectedFarmSummary.areaAlq)} alq</span>
              </div>
              <FarmMetadataStrip farm={selectedFarm} />
            </section>
          ) : null}

          {farmChangePrompt && selectedFarm ? (
            <section className="full harvestDecisionBox">
              <div>
                <strong>Essa frente mudou de fazenda?</strong>
                <span>
                  {formatFrontNumbers(selectedFrontNumbers)} ja tem talhões em{" "}
                  {formatFarmListByIds(farms, farmChangePrompt.previousFarmIds)}. Ao selecionar {formatFarmLabel(selectedFarm)}, escolha se
                  ela também está nesse novo local ou se a fazenda anterior fechou.
                </span>
              </div>
              <div className="rowActions">
                <button className="secondaryButton compactButton" type="button" onClick={keepPreviousFarmSelection}>
                  Manter e somar nova fazenda
                </button>
                <button className="secondaryButton compactButton dangerButton" type="button" onClick={replacePreviousFarmSelection}>
                  Fechar antiga e substituir
                </button>
              </div>
            </section>
          ) : null}

          {selectedFarms.length > 0 ? (
            <section className="full selectedOrderFarms">
              <div>
                <strong>Fazendas salvas nesta OS</strong>
                <span>
                  {selectedFarms.length} fazenda{selectedFarms.length === 1 ? "" : "s"} · {fieldIds.length} talhões ·{" "}
                  {formatShortNumber(selectedFieldSummary.areaHa)} ha
                </span>
              </div>
              <div className="selectedOrderFarmList">
                {selectedFarms.map((farm) => {
                  const farmFields = selectedFields.filter((field) => field.farmId === farm.id);

                  return (
                    <div className="selectedOrderFarmItem" key={farm.id} title={`Editar talhões de ${formatFarmLabel(farm)}`}>
                      <button
                        type="button"
                        className="farmItemLabelButton"
                        onClick={() => selectHarvestFarm(farm)}
                      >
                        {farm.code ? `${farm.code} - ` : ""}
                        {farm.name}: {farmFields.length} talhões
                      </button>
                      {editingOrderId ? (
                        <button
                          className="iconTextButton dangerTextButton"
                          type="button"
                          onClick={(e) => {
                            e.stopPropagation();
                            removeFarmFromOrder(farm.id);
                          }}
                          title={`Remover ${formatFarmLabel(farm)} desta OS`}
                        >
                          <Trash2 size={14} />
                          Remover
                        </button>
                      ) : null}
                    </div>
                  );
                })}
              </div>
            </section>
          ) : null}

          <div className="full fieldSelection harvestFieldSelection">
            <div className="fieldSelectionToolbar">
              <div>
                <strong>Talhões</strong>
                <span>
                  {fieldIds.length} selecionados
                  {selectedFields.length > 0
                    ? ` · ${formatShortNumber(selectedFieldSummary.areaHa)} ha · ${formatShortNumber(selectedFieldSummary.areaAlq)} alq`
                    : ""}
                </span>
              </div>
              <label className="searchField fieldSearchField">
                <Search size={16} />
                <input
                  value={fieldSearch}
                  onChange={(event) => setFieldSearch(event.target.value)}
                  placeholder="Buscar talhão"
                  disabled={!selectedFarm}
                />
              </label>
            </div>
            <div className="fieldSelectionActions">
              <button
                className="secondaryButton compactButton"
                type="button"
                onClick={selectAllFields}
                disabled={!selectedFarm || allVisibleFieldsSelected || selectableFieldIds.length === 0}
              >
                Selecionar exibidos
              </button>
              <button className="secondaryButton compactButton" type="button" onClick={clearSelectedFields} disabled={fieldIds.length === 0}>
                Limpar seleção
              </button>
            </div>
            <div className="harvestFieldGrid">
              {!selectedFarm ? <span className="muted emptyState">Selecione uma fazenda para ver os talhões.</span> : null}
              {selectedFarm && selectableFields.length === 0 ? <span className="muted emptyState">Nenhum talhão encontrado.</span> : null}
              {selectableFields.map((field) => {
                const selected = selectedFieldIdSet.has(field.id);

                return (
                  <label className={`harvestFieldTile ${selected ? "selected" : ""}`} key={field.id}>
                    <input
                      type="checkbox"
                      checked={selected}
                      onChange={(event) => {
                        setFieldIds((current) =>
                          event.target.checked ? [...current, field.id] : current.filter((id) => id !== field.id)
                        );
                      }}
                    />
                    <span>{field.code}</span>
                    <small>{field.areaHa === null || field.areaHa === undefined ? "sem área" : `${formatShortNumber(field.areaHa)} ha`}</small>
                  </label>
                );
              })}
            </div>
          </div>
          {activeFrontConflicts.length > 0 ? (
            <div className="notice error full">
              {activeFrontConflicts
                .map((conflict) => `Frente ${conflict.frontNumber} ja esta em colheita na OS ${conflict.order.number}`)
                .join("; ")}
            </div>
          ) : null}
          {fieldReuseWarnings.length > 0 ? (
            <div className="notice full">
              {fieldReuseWarnings.join("; ")}
              {selectedFrontNumbers.length > 0 ? ". Mais de uma frente pode trabalhar na mesma fazenda e no mesmo talhao." : "."}
            </div>
          ) : null}
          <div className="rowActions full">
            <button className="primaryButton" type="submit" disabled={busy}>
              {editingOrder?.status === "CLOSED"
                ? "Corrigir OS encerrada"
                : editingOrderId
                ? "Atualizar colheita"
                : "Salvar colheita atual"}
            </button>
            {editingOrderId ? (
              <button className="secondaryButton" type="button" onClick={resetOrderForm} disabled={busy}>
                Cancelar edição
              </button>
            ) : null}
          </div>
        </form>
      </section>
      ) : null}

      {ordersTab === "overview" ? (
      <section className="panel harvestListPanel ordersListPanel">
        <div className="sectionHeader registryHeader">
          <div>
            <h2>Colheitas atuais</h2>
            <span className="muted">
              {harvestingOrders.length} OS em colheita · {releasedOrders.length} OS liberada{releasedOrders.length === 1 ? "" : "s"} sem frente
            </span>
          </div>
          <label className="searchField orderSearchField">
            <Search size={17} />
            <input value={orderSearch} onChange={(event) => setOrderSearch(event.target.value)} placeholder="Buscar OS, frente ou fazenda" />
          </label>
          <div className="reportButtonStack">
            <button className="primaryButton" type="button" onClick={exportHarvestReport}>
              <FileText size={18} />
              Relatório de fazendas
            </button>
            <button className="secondaryButton" type="button" onClick={exportHarvestSummaryReport}>
              <FileText size={18} />
              Relatório resumido
            </button>
            <button className="secondaryButton" type="button" onClick={exportWhatsAppReport} title="Copiar e abrir no WhatsApp">
              <MessageCircle size={18} />
              WhatsApp
            </button>
          </div>
        </div>

        <section className="registryStats harvestStats">
          <div>
            <span>Frentes colhendo</span>
            <strong>{activeSummary.frontCount}</strong>
          </div>
          <div>
            <span>Fazendas colhendo</span>
            <strong>{activeSummary.farmCount}</strong>
          </div>
          <div>
            <span>Talhões colhendo</span>
            <strong>{activeSummary.fieldCount}</strong>
          </div>
          <div>
            <span>Área colhendo ha</span>
            <strong>{formatShortNumber(activeSummary.areaHa)}</strong>
          </div>
          <div>
            <span>Área colhendo alq</span>
            <strong>{formatShortNumber(activeSummary.areaAlq)}</strong>
          </div>
        </section>

        <div className="harvestOrderGrid">
          {filteredHarvestingOrders.length === 0 ? <span className="muted emptyState">Nenhuma frente em colheita no momento.</span> : null}
          {filteredHarvestingOrders.map((order) => {
            const orderSummary = summarizeOrderFields(order);
            const visibleFields = order.fields.slice(0, 24);
            const hiddenFieldCount = order.fields.length - visibleFields.length;
            const orderFarms = getOrderFarms(order);



            return (
              <article
                className={`harvestOrderCard activeOrderCard orderSummaryCard ${editingOrderId === order.id ? "editing" : ""}`}
                key={order.id}
                role="button"
                tabIndex={0}



              >
                <div className="harvestOrderHeader">
                  <span className="frontPill">{formatFrontNumbers(getOrderFrontNumbers(order))}</span>
                  <span className="statusBadgeGroup">
                    <span className="statusBadge closed">Em colheita</span>

                  </span>
                </div>
                <div className="harvestOrderMain">
                  <strong>{formatOrderFarmNames(order)}</strong>
                  <span>OS {order.number}</span>
                </div>
                <div className="harvestOrderFacts">
                  <span>{orderFarms.length} fazenda{orderFarms.length === 1 ? "" : "s"}</span>
                  <span>{order.fields.length} talhões</span>
                  <span>{formatShortNumber(orderSummary.areaHa)} ha</span>
                  <span>{formatShortNumber(orderSummary.areaAlq)} alq</span>
                </div>
                <div className="orderFieldPreview">
                  {visibleFields.map((item) => (
                    <span key={item.fieldId}>{item.field.code}</span>
                  ))}
                  {hiddenFieldCount > 0 ? <span>+{hiddenFieldCount}</span> : null}
                </div>
                {getOrderFrontNumbers(order).length > 1 ? (
                  <div className="frontRemovalGrid" onClick={(event) => event.stopPropagation()}>
                    {getOrderFrontNumbers(order).map((frontNumber) => (
                      <button
                        className="secondaryButton compactButton"
                        type="button"
                        key={frontNumber}
                        onClick={() => removeFrontFromOrder(order, frontNumber)}
                        disabled={busy}
                      >
                        Retirar F{frontNumber}
                      </button>
                    ))}
                  </div>
                ) : null}
                <div className="rowActions" onClick={(event) => event.stopPropagation()}>
                    <button className="secondaryButton compactButton" type="button" onClick={() => startEdit(order, { scrollToForm: true })} disabled={busy}>
                    <Edit3 size={16} />
                    Editar
                  </button>
                  <button className="secondaryButton compactButton" type="button" onClick={() => clearOrderFronts(order)} disabled={busy}>
                    Liberar sem frente
                  </button>
                  <button className="secondaryButton compactButton" type="button" onClick={() => closeHarvestOrder(order)} disabled={busy}>
                    <CheckCircle2 size={16} />
                    Finalizar
                  </button>
                  <button
                    className="secondaryButton compactButton dangerButton"
                    type="button"
                    onClick={() => removeHarvestOrder(order)}
                    disabled={busy}
                  >
                    <Trash2 size={16} />
                    Excluir
                  </button>
                </div>
              </article>
            );
          })}
        </div>

        <section className="releasedHarvestSection">
          <div className="sectionHeader">
            <div>
              <h2>OS abertas e liberadas sem frente</h2>
              <span className="muted">Liberadas para colher, mas ainda sem frente aplicada.</span>
            </div>
          </div>

          <div className="harvestOrderGrid">
            {filteredReleasedOrders.length === 0 ? <span className="muted emptyState">Nenhuma OS liberada sem frente.</span> : null}
            {filteredReleasedOrders.map((order) => {
              const orderSummary = summarizeOrderFields(order);
              const visibleFields = order.fields.slice(0, 24);
              const hiddenFieldCount = order.fields.length - visibleFields.length;
              const orderFarms = getOrderFarms(order);



              return (
                <article
                  className={`harvestOrderCard releasedOrderCard orderSummaryCard ${editingOrderId === order.id ? "editing" : ""}`}
                  key={order.id}
                  role="button"
                  tabIndex={0}



                >
                  <div className="harvestOrderHeader">
                    <span className="frontPill">Sem frente</span>
                    <span className="statusBadgeGroup">
                      <span className="statusBadge warning">Liberada</span>

                    </span>
                  </div>
                  <div className="harvestOrderMain">
                    <strong>{formatOrderFarmNames(order)}</strong>
                    <span>OS {order.number}</span>
                  </div>
                  <div className="harvestOrderFacts">
                    <span>{orderFarms.length} fazenda{orderFarms.length === 1 ? "" : "s"}</span>
                    <span>{order.fields.length} talhões</span>
                    <span>{formatShortNumber(orderSummary.areaHa)} ha</span>
                    <span>{formatShortNumber(orderSummary.areaAlq)} alq</span>
                  </div>
                  <div className="orderFieldPreview">
                    {visibleFields.map((item) => (
                      <span key={item.fieldId}>{item.field.code}</span>
                    ))}
                    {hiddenFieldCount > 0 ? <span>+{hiddenFieldCount}</span> : null}
                  </div>
                  <div className="rowActions" onClick={(event) => event.stopPropagation()}>
                    <button className="secondaryButton compactButton" type="button" onClick={() => startEdit(order, { scrollToForm: true })} disabled={busy}>
                      <Edit3 size={16} />
                      Aplicar frente
                    </button>
                    <button className="secondaryButton compactButton" type="button" onClick={() => closeHarvestOrder(order)} disabled={busy}>
                      <CheckCircle2 size={16} />
                      Finalizar
                    </button>
                    <button
                      className="secondaryButton compactButton dangerButton"
                      type="button"
                      onClick={() => removeHarvestOrder(order)}
                      disabled={busy}
                    >
                      <Trash2 size={16} />
                      Excluir
                    </button>
                  </div>
                </article>
              );
            })}
          </div>
        </section>
      </section>
      ) : null}

      {ordersTab === "check" ? <PdfHarvestCheck token={token} onSaved={onSaved} setMessage={setMessage} /> : null}

      {ordersTab === "closed" ? (
      <section className="panel harvestListPanel ordersListPanel">
        <section className="closedHarvestSection">
          <div className="sectionHeader closedHarvestHeader">
            <div>
              <h2>Fazendas com datas encerradas</h2>
              <span className="muted">
                {closedOrderRows.length} fazenda{closedOrderRows.length === 1 ? "" : "s"} encerrada{closedOrderRows.length === 1 ? "" : "s"}
                {closedOrderSearchTerms.length > 0
                  ? ` · ${filteredClosedOrderRows.length} resultado${filteredClosedOrderRows.length === 1 ? "" : "s"}`
                  : ""}
              </span>
            </div>
            <label className="searchField closedOrderSearchField">
              <Search size={17} />
              <input
                value={closedOrderSearch}
                onChange={(event) => setClosedOrderSearch(event.target.value)}
                placeholder="Buscar fazenda, OS, frente ou talhão"
              />
            </label>
          </div>

          <div className="tableWrap">
            <table>
              <thead>
                <tr>
                  <th>Fechamento</th>
                  <th>Frente</th>
                  <th>OS</th>
                  <th>Fazenda</th>

                  <th>Talhões</th>
                  <th>Ações</th>
                </tr>
              </thead>
              <tbody>
                {filteredClosedOrderRows.length === 0 ? (
                  <tr>
                    <td colSpan={7}>
                      {closedOrderSearchTerms.length > 0
                        ? "Nenhuma fazenda encerrada encontrada para a busca."
                        : "Nenhuma fazenda encerrada registrada."}
                    </td>
                  </tr>
                ) : (
                  filteredClosedOrderRows.map(({ order, group }) => (
                      <tr key={`${order.id}-${group.farm.id}`}>
                        <td>{order.endDate ? formatDateTime(order.endDate) : "-"}</td>
                        <td>{formatFrontNumbers(getOrderFrontNumbers(order))}</td>
                        <td>{order.number}</td>
                        <td>{formatFarmLabel(group.farm)}</td>

                        <td>{group.fields.join(", ") || "-"}</td>
                        <td className="actionCell">
                          <div style={{ display: "flex", gap: "8px" }}>
                            <button
                              className="secondaryButton compactButton"
                              type="button"
                              onClick={() => startEdit(order, { scrollToForm: true })}
                              disabled={busy}
                              title={`Editar talhões da OS ${order.number}`}
                            >
                              <Edit3 size={14} />
                              Editar
                            </button>
                            <button
                              className="secondaryButton compactButton"
                              type="button"
                              onClick={() => reopenHarvestOrder(order)}
                              disabled={busy}
                              title={`Reabrir OS ${order.number}`}
                            >
                              <RotateCcw size={14} />
                              Reabrir
                            </button>
                          </div>
                        </td>
                      </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </section>

        <section className="orderHistorySection">
          <div className="sectionHeader">
            <div>
              <h2>Histórico de movimentações</h2>
              <span className="muted">Registros criados daqui para frente.</span>
            </div>
          </div>

          <div className="tableWrap">
            <table>
              <thead>
                <tr>
                  <th>Data</th>
                  <th>OS</th>
                  <th>Movimento</th>
                  <th>Frentes</th>
                </tr>
              </thead>
              <tbody>
                {orderHistory.length === 0 ? (
                  <tr>
                    <td colSpan={4}>Nenhuma movimentação registrada ainda.</td>
                  </tr>
                ) : (
                  orderHistory.map((event) => (
                    <tr key={event.id}>
                      <td>{formatDateTime(event.occurredAt)}</td>
                      <td>{event.orderNumber}</td>
                      <td>{formatOrderHistoryEventLabel(event)}</td>
                      <td>{formatOrderHistoryFronts(event)}</td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </section>
      </section>
      ) : null}


    </div>
  );
}

type ImportCommitResponse = {
  batch?: {
    id?: string;
    fileName?: string;
  };
};

type PdfProgressState = {
  title: string;
  step: string;
  detail?: string;
  percent?: number;
};

function PdfHarvestCheck({
  token,
  onSaved,
  setMessage,
  showInsertButton = false,
  title = "Conferir PDF da balança",
  description = "Cruza o PDF com a colheita atual cadastrada"
}: {
  token: string;
  onSaved: (result?: ImportCommitResponse) => Promise<void>;
  setMessage: (message: string | null) => void;
  showInsertButton?: boolean;
  title?: string;
  description?: string;
}) {
  const [pdfFile, setPdfFile] = useState<File | null>(null);
  const [pdfPreview, setPdfPreview] = useState<PreviewImport | null>(null);
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState<PdfProgressState | null>(null);

  async function upload(path: "/imports/preview" | "/imports") {
    if (!pdfFile) {
      setMessage("Selecione o PDF da balanca.");
      return;
    }

    if (path === "/imports") {
      await savePdfComparison();
      return;
    }

    setMessage(null);
    setBusy(true);
    setProgress({
      title: "Conferindo PDF",
      step: "Enviando arquivo",
      percent: 0
    });

    const data = new FormData();
    data.append("file", pdfFile);

    try {
      const preview = await postFormJson<PreviewImport>(path, token, data, {
        onUploadProgress: (item) =>
          setProgress({
            title: "Conferindo PDF",
            step: "Enviando arquivo",
            detail: formatTransferProgress(item),
            percent: scaleTransferProgress(item, 0, 65)
          })
      });

      setProgress({
        title: "Conferindo PDF",
        step: "Resultado pronto",
        percent: 100
      });
      setPdfPreview(preview);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Falha ao conferir PDF.");
    } finally {
      setBusy(false);
      setProgress(null);
    }
  }

  async function savePdfComparison() {
    if (!pdfFile) {
      setMessage("Selecione o PDF da balanca.");
      return;
    }

    const selectedFile = pdfFile;
    setMessage(null);
    setBusy(true);
    setProgress({
      title: "Inserindo dados",
      step: "Enviando PDF para gravação",
      percent: 0
    });

    const data = new FormData();
    data.append("file", selectedFile);
    if (pdfPreview?.fileHash) {
      data.append("previewHash", pdfPreview.fileHash);
    }

    try {
      const result = await postFormJson<ImportCommitResponse>("/imports", token, data, {
        onUploadProgress: (item) =>
          setProgress({
            title: "Inserindo dados",
            step: "Enviando PDF para gravação",
            detail: formatTransferProgress(item),
            percent: scaleTransferProgress(item, 0, 80)
          })
      });

      setProgress({
        title: "Inserindo dados",
        step: "Atualizando dashboard",
        percent: 90
      });
      setPdfPreview(null);
      await onSaved(result);
      setPdfFile(null);
      setMessage("Dados inseridos na tabela de resultados.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Falha ao inserir dados.");
    } finally {
      setBusy(false);
      setProgress(null);
    }
  }

  async function downloadHighlightedPdf() {
    if (!pdfFile) return;

    setMessage(null);
    setBusy(true);

    const data = new FormData();
    data.append("file", pdfFile);

    try {
      await downloadFormFile("/imports/highlight-divergences", token, data, pdfFile.name.replace(/\.pdf$/i, "-marcado.pdf"));
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Falha ao baixar PDF marcado.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="panel harvestPdfPanel">
      {progress ? <PdfProgressOverlay progress={progress} /> : null}
      <div className="sectionHeader harvestPdfHeader">
        <div>
          <h2>{title}</h2>
          <span className="muted">{description}</span>
        </div>
      </div>

      <div className="importRow harvestPdfActions">
        <label className="fileInput">
          <Upload size={20} />
          <span>{pdfFile?.name ?? "Selecionar PDF"}</span>
          <input
            type="file"
            accept=".pdf"
            onChange={(event) => {
              setPdfFile(event.target.files?.[0] ?? null);
              setPdfPreview(null);
            }}
          />
        </label>
        <button className="secondaryButton" type="button" onClick={() => upload("/imports/preview")} disabled={busy}>
          {pdfPreview ? "Comparar novamente" : "Comparar PDF"}
        </button>
        {pdfPreview ? (
          <button className="secondaryButton" type="button" onClick={downloadHighlightedPdf} disabled={busy}>
            Baixar PDF Marcado
          </button>
        ) : null}
        {showInsertButton ? (
          <button className="primaryButton" type="button" onClick={() => upload("/imports")} disabled={busy || !pdfFile}>
            <Database size={18} />
            Inserir dados
          </button>
        ) : null}
      </div>

      {pdfPreview ? (
        <div className="pdfCheckPreview">
          <section className="metricsGrid compactMetrics">
            <Metric label="Linhas" value={pdfPreview.summary.rowCount} />
            <Metric label="Corretas" value={pdfPreview.summary.okCount} tone="ok" />
            <Metric label="Divergentes" value={pdfPreview.summary.errorCount} tone="danger" />
            <Metric label="Alqueires" value={formatShortNumber(pdfPreview.summary.areaAlq)} tone="info" />
            <Metric label="Hectares" value={formatShortNumber(pdfPreview.summary.areaHa)} />
          </section>

          {pdfPreview.summary.areaByDate.length > 0 ? (
            <div className="tableWrap pdfAreaTableWrap">
              <table>
                <thead>
                  <tr>
                    <th>Data PDF</th>
                    <th>Talhões com área</th>
                    <th>Alqueires</th>
                    <th>Hectares</th>
                  </tr>
                </thead>
                <tbody>
                  {pdfPreview.summary.areaByDate.map((item) => (
                    <tr key={item.date}>
                      <td>{formatDateOnly(item.date)}</td>
                      <td>{item.fieldCount}</td>
                      <td>{formatShortNumber(item.areaAlq)}</td>
                      <td>{formatShortNumber(item.areaHa)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : null}

          <div className="statusGrid importStatusGrid">
            {pdfPreview.summary.byStatus.map((item) => (
              <div className="statusItem" key={item.status}>
                <span>{statusLabels[item.status]}</span>
                <strong>{item.count}</strong>
              </div>
            ))}
          </div>

          <div className="tableWrap pdfCheckTableWrap">
            <table>
              <thead>
                <tr>
                  <th>Fazenda</th>
                  <th>Talhão</th>
                  <th>Cana entregue</th>
                  <th>Viagens</th>
                  <th>OS</th>
                  <th>Status</th>
                  <th>Observação</th>
                </tr>
              </thead>
              <tbody>
                {pdfPreview.rows.map((row, index) => (
                  <tr key={`${row.ticketNumber ?? "pdf"}-${index}`}>
                    <td>{row.farmRaw ?? "-"}</td>
                    <td>{row.fieldRaw ?? "-"}</td>
                    <td>{formatNumber(row.netWeight)}</td>
                    <td>{row.tripCount ?? "-"}</td>
                    <td>{row.orderRaw ?? "-"}</td>
                    <td>
                      <span className={`statusBadge ${entryStatusClass(row.status)}`}>{statusLabels[row.status]}</span>
                    </td>
                    <td>{row.notes ?? "-"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      ) : null}
    </section>
  );
}

function PdfProgressOverlay({ progress }: { progress: PdfProgressState }) {
  const percent = progress.percent === undefined ? undefined : Math.max(0, Math.min(100, progress.percent));

  return (
    <div className="progressOverlay" role="status" aria-live="polite">
      <div className="progressCard">
        <div className="progressHeader">
          <FileText size={22} />
          <div>
            <strong>{progress.title}</strong>
            <span>{progress.step}</span>
          </div>
        </div>
        <div className={`progressTrack ${percent === undefined ? "indeterminate" : ""}`}>
          <span style={percent === undefined ? undefined : { width: `${percent}%` }} />
        </div>
        <div className="progressMeta">
          <span>{progress.detail ?? "Processando arquivo"}</span>
          <strong>{percent === undefined ? "" : `${Math.round(percent)}%`}</strong>
        </div>
      </div>
    </div>
  );
}

function scaleTransferProgress(progress: TransferProgress, start: number, end: number) {
  if (progress.percent === undefined) {
    return undefined;
  }

  return Math.round(start + ((end - start) * progress.percent) / 100);
}

function formatTransferProgress(progress: TransferProgress) {
  if (progress.total) {
    return `${formatFileSize(progress.loaded)} de ${formatFileSize(progress.total)}`;
  }

  return formatFileSize(progress.loaded);
}

function formatFileSize(bytes: number) {
  if (bytes >= 1024 * 1024) {
    return `${(bytes / (1024 * 1024)).toFixed(1).replace(".", ",")} MB`;
  }

  if (bytes >= 1024) {
    return `${Math.round(bytes / 1024)} KB`;
  }

  return `${bytes} B`;
}











type FleetMovementForm = {
  movementType: FleetMovementType;
  equipmentCode: string;
  equipmentType: FleetEquipmentType;
  frontNumber: string;
  reserveCode: string;
  replacesCode: string;
  reason: string;
  occurredAt: string;
};

type FleetMovementValidation = {
  tone: "ok" | "warning" | "danger";
  messages: string[];
  blocksSubmit: boolean;
};

function FleetReportsView({ token, setMessage }: { token: string; setMessage: (message: string | null) => void }) {
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<FleetReportPreview | null>(null);
  const [busy, setBusy] = useState(false);
  const [movements, setMovements] = useState<FleetMovement[]>([]);
  const [movementForm, setMovementForm] = useState<FleetMovementForm>(() => createEmptyFleetMovementForm());
  const [movementsLoading, setMovementsLoading] = useState(false);
  const [movementBusy, setMovementBusy] = useState(false);

  const movementSummary = useMemo(
    () => ({
      open: movements.filter((movement) => movement.status === "OPEN").length,
      leftMill: movements.filter((movement) => movement.movementType === "LEFT_MILL").length,
      returnedMill: movements.filter((movement) => movement.movementType === "RETURNED_MILL").length,
      reserves: movements.filter((movement) => movement.movementType === "RESERVE_ACTIVATED").length
    }),
    [movements]
  );
  const movementValidation = useMemo(
    () => validateFleetMovement(movementForm, preview),
    [movementForm, preview]
  );

  useEffect(() => {
    loadMovements().catch((error) => {
      setMessage(error instanceof Error ? error.message : "Falha ao carregar movimentacoes de frota.");
    });
    loadDefaultFleetBase().catch((error) => {
      setMessage(error instanceof Error ? error.message : "Falha ao carregar base padrao de frotas.");
    });
  }, [token]);

  async function loadMovements() {
    setMovementsLoading(true);

    try {
      const payload = await apiRequest<{ movements: FleetMovement[] }>("/fleet-reports/movements", token);
      setMovements(payload.movements);
    } finally {
      setMovementsLoading(false);
    }
  }

  async function loadDefaultFleetBase() {
    setBusy(true);
    setMessage(null);

    try {
      const basePreview = await apiRequest<FleetReportPreview>("/fleet-reports/base/preview", token);
      setPreview(basePreview);
      setFile(null);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Falha ao carregar base padrao de frotas.");
    } finally {
      setBusy(false);
    }
  }

  async function requestFleetPreview(selectedFile: File | null) {
    if (!selectedFile) {
      return apiRequest<FleetReportPreview>("/fleet-reports/base/preview", token);
    }

    const data = new FormData();
    data.append("file", selectedFile);

    return apiRequest<FleetReportPreview>("/fleet-reports/preview", token, { method: "POST", body: data });
  }

  async function refreshFleetPreview() {
    if (!preview) {
      return;
    }

    setPreview(await requestFleetPreview(file));
  }

  async function submitMovement(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    const equipmentCode = movementForm.equipmentCode.trim();

    if (!equipmentCode) {
      setMessage("Informe o equipamento movimentado.");
      return;
    }

    const frontNumber = movementForm.frontNumber.trim() ? Number(movementForm.frontNumber) : undefined;

    if (frontNumber !== undefined && !Number.isFinite(frontNumber)) {
      setMessage("Informe uma frente valida.");
      return;
    }

    if (movementValidation.blocksSubmit) {
      setMessage(movementValidation.messages[0] ?? "Movimentacao nao confere com a base de frotas.");
      return;
    }

    const payload: FleetMovementInput = {
      movementType: movementForm.movementType,
      equipmentCode,
      equipmentType: movementForm.equipmentType,
      frontNumber,
      reserveCode: optionalText(movementForm.reserveCode),
      replacesCode: optionalText(movementForm.replacesCode),
      reason: optionalText(movementForm.reason),
      occurredAt: normalizeDateTimeInput(movementForm.occurredAt),
      status: "OPEN"
    };

    setMovementBusy(true);
    setMessage(null);

    try {
      const result = await apiRequest<{ movement: FleetMovement }>("/fleet-reports/movements", token, {
        method: "POST",
        body: JSON.stringify(payload)
      });
      setMovements((current) => [result.movement, ...current]);
      setMovementForm(createEmptyFleetMovementForm());
      await refreshFleetPreview();
      setMessage("Movimentacao de frota registrada.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Falha ao registrar movimentacao.");
    } finally {
      setMovementBusy(false);
    }
  }

  async function changeMovementStatus(movement: FleetMovement, status: FleetMovementStatus) {
    setMovementBusy(true);
    setMessage(null);

    try {
      const result = await apiRequest<{ movement: FleetMovement }>(`/fleet-reports/movements/${movement.id}/status`, token, {
        method: "PATCH",
        body: JSON.stringify({ status })
      });
      setMovements((current) => current.map((item) => (item.id === movement.id ? result.movement : item)));
      await refreshFleetPreview();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Falha ao atualizar movimentacao.");
    } finally {
      setMovementBusy(false);
    }
  }

  async function removeMovement(movement: FleetMovement) {
    if (!window.confirm(`Excluir a movimentacao do equipamento ${movement.equipmentCode}?`)) {
      return;
    }

    setMovementBusy(true);
    setMessage(null);

    try {
      await apiRequest(`/fleet-reports/movements/${movement.id}`, token, { method: "DELETE" });
      setMovements((current) => current.filter((item) => item.id !== movement.id));
      await refreshFleetPreview();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Falha ao excluir movimentacao.");
    } finally {
      setMovementBusy(false);
    }
  }

  async function previewReport() {
    setBusy(true);
    setMessage(null);

    try {
      setPreview(await requestFleetPreview(file));
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Falha ao analisar planilha de frotas.");
    } finally {
      setBusy(false);
    }
  }

  async function generatePdf() {
    setBusy(true);
    setMessage(null);

    try {
      if (file) {
        const data = new FormData();
        data.append("file", file);
        await downloadFormFile("/fleet-reports/pdf", token, data, buildFleetReportFileName(file.name));
      } else {
        await downloadFile("/fleet-reports/base/pdf", token, buildFleetReportFileName(preview?.fileName ?? "Frotas.xlsx"));
      }
      setMessage("Relatório de frotas gerado.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Falha ao gerar relatório de frotas.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="stack">
      <section className="panel importPanel">
        <h2>Base de frotas</h2>
        <div className="reportActions">
          <label className="fileInput">
            <Upload size={20} />
            <span>{file?.name ?? preview?.fileName ?? "Base padrão Frotas.xlsx"}</span>
            <input
              type="file"
              accept=".xlsx"
              onChange={(event) => {
                setFile(event.target.files?.[0] ?? null);
                setPreview(null);
              }}
            />
          </label>
          <button className="secondaryButton" type="button" onClick={loadDefaultFleetBase} disabled={busy}>
            <Database size={18} />
            Base padrão
          </button>
          <button className="secondaryButton" type="button" onClick={previewReport} disabled={busy}>
            <Eye size={18} />
            {preview ? "Atualizar relatório" : "Carregar relatório"}
          </button>
          <button className="primaryButton" type="button" onClick={generatePdf} disabled={busy}>
            <Download size={18} />
            {busy ? "Processando" : "Gerar PDF"}
          </button>
        </div>
        {preview ? (
          <p className="muted importNotice">
            Base extraída: {preview.equipment.length} equipamentos. Coberturas/substituições: {preview.substitutions.length}.
          </p>
        ) : null}
        {preview?.movementSummary.warnings.length ? (
          <div className="notice importNotice">
            {preview.movementSummary.warnings.map((warning) => (
              <p key={warning}>{warning}</p>
            ))}
          </div>
        ) : null}
        {preview?.observations.length ? (
          <div className="notice importNotice">
            <strong>Observações da base oficial</strong>
            {preview.observations.map((observation) => (
              <p key={observation}>{observation}</p>
            ))}
          </div>
        ) : null}
      </section>

      <section className="panel fleetMovementPanel">
        <div className="sectionHeader">
          <div>
            <h2>Movimentação e pendências</h2>
            <span className="muted">Controle de saída, retorno e uso de equipamentos reserva.</span>
          </div>
          <button className="secondaryButton compactButton" type="button" onClick={loadMovements} disabled={movementsLoading || movementBusy}>
            <RefreshCw size={16} />
            Atualizar
          </button>
        </div>

        <div className="movementSummaryGrid">
          <article>
            <span>Abertas</span>
            <strong>{movementSummary.open}</strong>
          </article>
          <article>
            <span>Saíram da operacao</span>
            <strong>{movementSummary.leftMill}</strong>
          </article>
          <article>
            <span>Voltaram</span>
            <strong>{movementSummary.returnedMill}</strong>
          </article>
          <article>
            <span>Reservas usados</span>
            <strong>{movementSummary.reserves}</strong>
          </article>
        </div>

        <form className="formGrid movementForm" onSubmit={submitMovement}>
          <label>
            Fluxo
            <select
              value={movementForm.movementType}
              onChange={(event) =>
                setMovementForm((current) => ({ ...current, movementType: event.target.value as FleetMovementType }))
              }
            >
              {fleetMovementTypeOptions.map((type) => (
                <option key={type} value={type}>
                  {fleetMovementTypeLabels[type]}
                </option>
              ))}
            </select>
          </label>
          <label>
            Equipamento
            <input
              value={movementForm.equipmentCode}
              onChange={(event) => setMovementForm((current) => ({ ...current, equipmentCode: event.target.value }))}
              placeholder="Ex.: TB-120, CH-03"
              required
            />
          </label>
          <label>
            Tipo
            <select
              value={movementForm.equipmentType}
              onChange={(event) =>
                setMovementForm((current) => ({ ...current, equipmentType: event.target.value as FleetEquipmentType }))
              }
            >
              {fleetEquipmentTypeOptions.map((type) => (
                <option key={type} value={type}>
                  {fleetEquipmentTypeLabels[type]}
                </option>
              ))}
            </select>
          </label>
          <label>
            Frente
            <input
              type="number"
              min="1"
              max="99"
              value={movementForm.frontNumber}
              onChange={(event) => setMovementForm((current) => ({ ...current, frontNumber: event.target.value }))}
              placeholder="Ex.: 1"
            />
          </label>
          <label>
            Reserva usado
            <input
              value={movementForm.reserveCode}
              onChange={(event) => setMovementForm((current) => ({ ...current, reserveCode: event.target.value }))}
              placeholder="Ex.: RES-04"
            />
          </label>
          <label>
            Substitui
            <input
              value={movementForm.replacesCode}
              onChange={(event) => setMovementForm((current) => ({ ...current, replacesCode: event.target.value }))}
              placeholder="Equipamento substituído"
            />
          </label>
          <label>
            Data e hora
            <input
              type="datetime-local"
              value={movementForm.occurredAt}
              onChange={(event) => setMovementForm((current) => ({ ...current, occurredAt: event.target.value }))}
            />
          </label>
          <label className="full">
            Observação
            <textarea
              rows={3}
              value={movementForm.reason}
              onChange={(event) => setMovementForm((current) => ({ ...current, reason: event.target.value }))}
              placeholder="Motivo, destino, oficina, operador ou detalhe do fluxo"
            />
          </label>
          {movementValidation.messages.length > 0 ? (
            <div className={`movementValidation ${movementValidation.tone} full`}>
              {movementValidation.messages.map((message) => (
                <p key={message}>{message}</p>
              ))}
            </div>
          ) : null}
          <div className="rowActions full">
            <button className="primaryButton" type="submit" disabled={movementBusy || movementValidation.blocksSubmit}>
              Registrar fluxo
            </button>
            <button className="secondaryButton" type="button" onClick={() => setMovementForm(createEmptyFleetMovementForm())} disabled={movementBusy}>
              <RotateCcw size={16} />
              Limpar
            </button>
          </div>
        </form>

        <div className="tableWrap movementTableWrap">
          <table>
            <thead>
              <tr>
                <th>Status</th>
                <th>Fluxo</th>
                <th>Equipamento</th>
                <th>Tipo</th>
                <th>Frente</th>
                <th>Reserva usado</th>
                <th>Substitui</th>
                <th>Data/hora</th>
                <th>Observação</th>
                <th>Ações</th>
              </tr>
            </thead>
            <tbody>
              {movements.length === 0 ? (
                <tr>
                  <td colSpan={10}>{movementsLoading ? "Carregando movimentacoes..." : "Nenhuma movimentacao registrada."}</td>
                </tr>
              ) : (
                movements.map((movement) => (
                  <tr key={movement.id}>
                    <td>
                      <span className={`statusBadge ${movement.status === "OPEN" ? "open" : "closed"}`}>
                        {fleetMovementStatusLabels[movement.status]}
                      </span>
                    </td>
                    <td>{fleetMovementTypeLabels[movement.movementType]}</td>
                    <td>{movement.equipmentCode}</td>
                    <td>{fleetEquipmentTypeLabels[movement.equipmentType]}</td>
                    <td>{movement.frontNumber ? `Frente ${movement.frontNumber}` : "-"}</td>
                    <td>{movement.reserveCode || "-"}</td>
                    <td>{movement.replacesCode || "-"}</td>
                    <td>{formatDateTime(movement.occurredAt)}</td>
                    <td>{movement.reason || "-"}</td>
                    <td>
                      <div className="rowActions">
                        {movement.status === "OPEN" ? (
                          <button
                            className="secondaryButton compactButton"
                            type="button"
                            onClick={() => changeMovementStatus(movement, "CLOSED")}
                            disabled={movementBusy}
                          >
                            <CheckCircle2 size={16} />
                            Concluir
                          </button>
                        ) : (
                          <button
                            className="secondaryButton compactButton"
                            type="button"
                            onClick={() => changeMovementStatus(movement, "OPEN")}
                            disabled={movementBusy}
                          >
                            <RotateCcw size={16} />
                            Reabrir
                          </button>
                        )}
                        <button
                          className="secondaryButton compactButton dangerButton"
                          type="button"
                          onClick={() => removeMovement(movement)}
                          disabled={movementBusy}
                        >
                          <Trash2 size={16} />
                          Excluir
                        </button>
                      </div>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </section>

      {preview ? (
        <>
          <section className="reportMetricsGrid">
            <Metric label="Base produtiva" value={preview.productive.total} />
            <Metric label="Em operação" value={preview.productive.operating} tone="ok" />
            <Metric label="Mudanças" value={preview.productive.moved} tone="info" />
            <Metric label="Fora de operação" value={preview.productive.outOfOperation} tone="danger" />
            <Metric label="Eficiência" value={formatPercent(preview.productive.efficiency)} />
          </section>

          <section className="reportMetricsGrid">
            <Metric label="Outros implementos" value={preview.support.total} />
            <Metric label="Apoio em operação" value={preview.support.operating} tone="ok" />
            <Metric label="Apoio mudanças" value={preview.support.moved} tone="info" />
            <Metric label="Apoio fora" value={preview.support.outOfOperation} tone="danger" />
            <Metric label="Disponibilidade" value={formatPercent(preview.support.efficiency)} />
          </section>

          <section className="panel">
            <div className="sectionHeader">
              <div>
                <h2>Resumo dos implementos</h2>
                <span className="muted">
                  {preview.frontCount} frentes, {preview.busCount} ônibus de linha
                </span>
              </div>
            </div>
            <div className="tableWrap">
              <table>
                <thead>
                  <tr>
                    <th>Tipo</th>
                    <th>Em operação</th>
                    <th>Mudanças</th>
                    <th>Fora de operação</th>
                    <th>Total</th>
                    <th>Disponibilidade</th>
                  </tr>
                </thead>
                <tbody>
                  {preview.supportByType.map((item) => (
                    <tr key={item.type}>
                      <td>{item.label}</td>
                      <td>{item.operating}</td>
                      <td>{item.moved}</td>
                      <td>{item.outOfOperation}</td>
                      <td>{item.total}</td>
                      <td>{formatPercent(item.efficiency)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          <section className="panel">
            <h2>Frentes</h2>
            <div className="tableWrap">
              <table>
                <thead>
                  <tr>
                    <th>Frente</th>
                    <th>Colhedoras</th>
                    <th>Transbordos</th>
                    <th>Base produtiva</th>
                    <th>Em operação</th>
                    <th>Mudanças</th>
                    <th>Fora</th>
                    <th>Eficiência</th>
                    <th>Apoio em operação</th>
                    <th>Apoio mudanças</th>
                    <th>Apoio fora</th>
                  </tr>
                </thead>
                <tbody>
                  {preview.fronts.map((front) => (
                    <tr key={front.name}>
                      <td>{front.name}</td>
                      <td>{front.productive.harvesters}</td>
                      <td>{front.productive.transbordos}</td>
                      <td>{front.productive.total}</td>
                      <td>{front.productive.operating}</td>
                      <td>{front.productive.moved}</td>
                      <td>{front.productive.outOfOperation}</td>
                      <td>{formatPercent(front.productive.efficiency)}</td>
                      <td>{front.support.operating}</td>
                      <td>{front.support.moved}</td>
                      <td>{front.support.outOfOperation}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        </>
      ) : null}
    </div>
  );
}





function BulkCloseOrdersView({
  orders,
  token,
  onSaved,
  setMessage
}: {
  orders: HarvestOrder[];
  token: string;
  onSaved: () => Promise<void>;
  setMessage: (message: string | null) => void;
}) {
  const [value, setValue] = useState("");
  const [busy, setBusy] = useState(false);
  const [results, setResults] = useState<BulkCloseOrderResult[]>([]);
  const orderNumbers = useMemo(() => parseBulkCloseOrderNumbers(value), [value]);
  const activeOrderCount = orders.filter((order) => order.status === "ACTIVE").length;
  const summary = summarizeBulkCloseResults(results);

  function handleChange(nextValue: string) {
    if (nextValue.length < value.length) {
      setValue(nextValue);
      return;
    }

    setValue(formatBulkCloseOrderInput(nextValue));
  }

  async function submit(event: FormEvent) {
    event.preventDefault();

    if (orderNumbers.length === 0) {
      setMessage("Informe pelo menos uma OS para encerrar.");
      return;
    }

    try {
      setBusy(true);
      const payload = await apiRequest<{
        results: BulkCloseOrderResult[];
        summary: { total: number; closed: number; alreadyClosed: number; notFound: number };
      }>("/orders/bulk-close", token, {
        method: "POST",
        body: JSON.stringify({ numbers: orderNumbers })
      });

      setResults(payload.results);
      await onSaved();
      setMessage(
        `Encerramento verificado: ${payload.summary.closed} fechada(s), ${payload.summary.alreadyClosed} ja estava(m) fechada(s), ${payload.summary.notFound} nao encontrada(s).`
      );
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Falha ao encerrar OS em massa.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="bulkCloseView">
      <form className="panel bulkClosePanel" onSubmit={submit}>
        <div className="sectionHeader">
          <div>
            <h2>Encerramento em massa</h2>
            <span className="muted">{activeOrderCount} OS ativa(s) na colheita atual</span>
          </div>
        </div>

        <label className="bulkCloseInputLabel">
          OS para encerrar
          <textarea
            className="bulkCloseInput"
            rows={7}
            value={value}
            onChange={(event) => handleChange(event.target.value)}
            placeholder="25074; 25075; 25076"
          />
        </label>

        <div className="bulkClosePreview">
          <span>{orderNumbers.length} OS pronta(s)</span>
          <span>{orderNumbers.slice(0, 8).join("; ") || "Nenhuma OS informada"}</span>
          {orderNumbers.length > 8 ? <span>+{orderNumbers.length - 8}</span> : null}
        </div>

        <div className="rowActions">
          <button className="primaryButton" type="submit" disabled={busy || orderNumbers.length === 0}>
            <CheckCircle2 size={18} />
            {busy ? "Encerrando" : "Verificar e encerrar"}
          </button>
          <button
            className="secondaryButton"
            type="button"
            disabled={busy || (!value && results.length === 0)}
            onClick={() => {
              setValue("");
              setResults([]);
              setMessage(null);
            }}
          >
            Limpar
          </button>
        </div>
      </form>

      {results.length > 0 ? (
        <section className="panel bulkCloseResultsPanel">
          <div className="bulkCloseSummary">
            <span className="bulkCloseStatus closed">Fechadas: {summary.closed}</span>
            <span className="bulkCloseStatus alreadyClosed">Ja fechadas: {summary.alreadyClosed}</span>
            <span className="bulkCloseStatus notFound">Nao encontradas: {summary.notFound}</span>
          </div>

          <div className="bulkCloseResultList">
            {results.map((result) => (
              <article className="bulkCloseResultItem" key={`${result.number}-${result.status}`}>
                <div>
                  <strong>OS {result.number}</strong>
                  <span>{formatBulkCloseResultDetails(result)}</span>
                </div>
                <span className={`bulkCloseStatus ${bulkCloseStatusClass(result.status)}`}>
                  {bulkCloseStatusLabel(result.status)}
                </span>
              </article>
            ))}
          </div>
        </section>
      ) : null}
    </section>
  );
}

type PostHarvestStatusFilter = PostHarvestIntegrationStatus | "ALL";

function PostHarvestIntegrationView({
  token,
  isAdmin,
  setMessage
}: {
  token: string;
  isAdmin: boolean;
  setMessage: (message: string | null) => void;
}) {
  const [events, setEvents] = useState<PostHarvestIntegrationEvent[]>([]);
  const [connection, setConnection] = useState<PostHarvestIntegrationConnection | null>(null);
  const [summary, setSummary] = useState({ pending: 0, processing: 0, sent: 0, error: 0, dead: 0 });
  const [statusFilter, setStatusFilter] = useState<PostHarvestStatusFilter>("ALL");
  const [loadingEvents, setLoadingEvents] = useState(false);
  const [sendingId, setSendingId] = useState<string | null>(null);
  const [sendingPending, setSendingPending] = useState(false);

  async function loadEvents() {
    setLoadingEvents(true);

    try {
      const payload = await apiRequest<{
        events: PostHarvestIntegrationEvent[];
        total: number;
        summary: { pending: number; processing: number; sent: number; error: number; dead: number };
        connection: PostHarvestIntegrationConnection;
      }>(
        `/post-harvest-integrations${queryString({
          status: statusFilter === "ALL" ? undefined : statusFilter,
          limit: "100"
        })}`,
        token
      );
      setEvents(payload.events);
      setSummary(payload.summary);
      setConnection(payload.connection);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Falha ao carregar integracao pos-colheita.");
    } finally {
      setLoadingEvents(false);
    }
  }

  useEffect(() => {
    void loadEvents();
  }, [token, statusFilter]);

  async function sendEvent(event: PostHarvestIntegrationEvent) {
    setMessage(null);
    setSendingId(event.id);

    try {
      await apiRequest(`/post-harvest-integrations/${event.id}/send`, token, { method: "POST" });
      await loadEvents();
      setMessage("Evento reenviado para o sistema destino.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Falha ao reenviar evento.");
    } finally {
      setSendingId(null);
    }
  }

  async function sendPendingEvents() {
    setMessage(null);
    setSendingPending(true);

    try {
      const payload = await apiRequest<{
        summary: { total: number; sent: number; skipped: number; error: number };
      }>("/post-harvest-integrations/send-pending", token, {
        method: "POST",
        body: JSON.stringify({ limit: 50 })
      });
      await loadEvents();
      setMessage(`${payload.summary.sent} evento(s) enviado(s), ${payload.summary.error} com erro, ${payload.summary.skipped} sem destino configurado.`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Falha ao enviar pendencias.");
    } finally {
      setSendingPending(false);
    }
  }

  return (
    <div className="stack integrationView">
      {isAdmin ? <OperationalHealthPanel token={token} /> : null}

      <section className="metricsGrid compactMetrics">
        <Metric label="Pendentes" value={formatShortNumber(summary.pending)} tone="info" />
        <Metric label="Processando" value={formatShortNumber(summary.processing)} tone="info" />
        <Metric label="Enviados" value={formatShortNumber(summary.sent)} tone="ok" />
        <Metric label="Erros" value={formatShortNumber(summary.error)} tone="danger" />
        <Metric label="Dead-letter" value={formatShortNumber(summary.dead)} tone="danger" />
      </section>

      <section className="panel">
        <div className="sectionHeader">
          <div>
            <h2>Conexao pos-colheita</h2>
            <span className="muted">
              {connection?.configured ? "Destino configurado para envio automatico." : "Aguardando URL do sistema destino para envio automatico."}
            </span>
          </div>
          <button className="secondaryButton compactButton" type="button" onClick={() => void loadEvents()} disabled={loadingEvents}>
            <RefreshCw size={16} />
            Atualizar
          </button>
        </div>

        <div className="statusGrid">
          <article className="statusItem">
            <span>Modo</span>
            <strong>{connection?.mode ?? "OUTGOING_WEBHOOK"}</strong>
          </article>
          <article className="statusItem">
            <span>URL destino</span>
            <strong>{connection?.targetUrlConfigured ? "Configurada" : "Nao configurada"}</strong>
          </article>
          <article className="statusItem">
            <span>Token</span>
            <strong>{connection?.tokenConfigured ? "Configurado" : "Nao configurado"}</strong>
          </article>
          <article className="statusItem">
            <span>Timeout</span>
            <strong>{connection ? `${connection.timeoutMs} ms` : "-"}</strong>
          </article>
        </div>

        <div className="tableWrap">
          <table>
            <thead>
              <tr>
                <th>Variavel</th>
                <th>Uso</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td>{connection?.env.url ?? "POST_HARVEST_WEBHOOK_URL"}</td>
                <td>URL POST que o outro sistema deve disponibilizar.</td>
              </tr>
              <tr>
                <td>{connection?.env.token ?? "POST_HARVEST_WEBHOOK_TOKEN"}</td>
                <td>Token bearer combinado com o outro programador.</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <section className="panel">
        <div className="sectionHeader">
          <div>
            <h2>Eventos gerados</h2>
            <span className="muted">Cada linha representa um talhao liberado depois do encerramento da OS.</span>
          </div>
          <div className="filterActions">
            <select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value as PostHarvestStatusFilter)}>
              <option value="ALL">Todos</option>
              <option value="PENDING">Pendentes</option>
              <option value="PROCESSING">Processando</option>
              <option value="ERROR">Com erro</option>
              <option value="DEAD">Dead-letter</option>
              <option value="SENT">Enviados</option>
            </select>
            {isAdmin ? (
              <button
                className="secondaryButton compactButton"
                type="button"
                onClick={() => void sendPendingEvents()}
                disabled={sendingPending || !connection?.configured}
                title={connection?.configured ? undefined : "Configure o destino antes do envio."}
              >
                <Share2 size={16} />
                {sendingPending ? "Enviando" : "Enviar pendentes"}
              </button>
            ) : null}
          </div>
        </div>

        <div className="tableWrap">
          <table>
            <thead>
              <tr>
                <th>Status</th>
                <th>Evento</th>
                <th>OS</th>
                <th>Fazenda</th>
                <th>Talhao</th>
                <th>Frente</th>
                <th>Tentativas</th>
                <th>Ultimo erro</th>
                <th>Acoes</th>
              </tr>
            </thead>
            <tbody>
              {events.length === 0 ? (
                <tr>
                  <td colSpan={9} className="emptyState">
                    {loadingEvents ? "Carregando eventos..." : "Nenhum evento pos-colheita gerado ainda."}
                  </td>
                </tr>
              ) : (
                events.map((event) => (
                  <tr key={event.id}>
                    <td>
                      <span className={`statusBadge ${postHarvestStatusClass(event.status)}`}>{postHarvestStatusLabel(event.status)}</span>
                    </td>
                    <td>
                      <strong>{event.eventId}</strong>
                      <br />
                      <small>{formatDateTime(event.createdAt)}</small>
                    </td>
                    <td>{event.orderNumber}</td>
                    <td>{formatFarmCodeName(event.farmCode, event.farmName)}</td>
                    <td>{event.fieldCode}</td>
                    <td>{formatFrontNumbers(event.frontNumbers)}</td>
                    <td>{event.attemptCount}</td>
                    <td>{event.lastError ?? (event.sentAt ? `Enviado em ${formatDateTime(event.sentAt)}` : "-")}</td>
                    <td>
                      {isAdmin && (event.status === "PENDING" || event.status === "ERROR") ? (
                        <button
                          className="secondaryButton compactButton"
                          type="button"
                          onClick={() => void sendEvent(event)}
                          disabled={sendingId === event.id || !connection?.configured}
                          title={connection?.configured ? undefined : "Configure o destino antes do envio."}
                        >
                          <Share2 size={16} />
                          {sendingId === event.id ? "Enviando" : "Enviar"}
                        </button>
                      ) : (
                        <span className="muted">{postHarvestActionLabel(event.status, isAdmin)}</span>
                      )}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}

function ImportsView({
  token,
  recentBatches,
  onImported,
  setMessage
}: {
  token: string;
  recentBatches: Summary["recentBatches"];
  onImported: () => Promise<void>;
  setMessage: (message: string | null) => void;
}) {
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<PreviewImport | null>(null);
  const [mapping, setMapping] = useState<PreviewImport["mapping"]>({});

  async function upload(path: string) {
    if (!file) {
      setMessage("Selecione um arquivo.");
      return;
    }

    setMessage(null);
    const data = new FormData();
    data.append("file", file);

    if (Object.values(mapping).some(Boolean)) {
      data.append("mapping", JSON.stringify(mapping));
    }

    try {
      const result = await apiRequest<PreviewImport | { batch: unknown }>(path, token, {
        method: "POST",
        body: data
      });

      if (path === "/imports/preview") {
        const nextPreview = result as PreviewImport;
        setPreview(nextPreview);
        setMapping(nextPreview.mapping);
      } else {
        setPreview(null);
        setFile(null);
        setMapping({});
        await onImported();
      }
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Falha ao importar arquivo.");
    }
  }

  return (
    <div className="stack validationView">
      <section className="validationSteps" aria-label="Fluxo de validacao">
        <article className={file ? "active" : ""}>
          <span>1</span>
          <strong>Arquivo</strong>
          <small>{file ? "Selecionado" : "Escolha o PDF ou planilha"}</small>
        </article>
        <article className={preview ? "active" : ""}>
          <span>2</span>
          <strong>Conferencia</strong>
          <small>{preview ? `${preview.summary.errorCount} divergencias` : "Gere a previa"}</small>
        </article>
        <article className={preview ? "ready" : ""}>
          <span>3</span>
          <strong>Salvar</strong>
          <small>{preview ? "Liberado para gravar" : "Aguardando previa"}</small>
        </article>
      </section>

      <section className="panel importPanel validationImportPanel">
        <div className="sectionHeader">
          <div>
            <h2>Arquivo para validar</h2>
            <span className="muted">Compare primeiro, revise os alertas e depois salve a validacao.</span>
          </div>
        </div>
        <div className="importRow">
          <label className="fileInput">
            <Upload size={20} />
            <span>{file?.name ?? "Selecionar arquivo da balança ou PDF"}</span>
            <input
              type="file"
              accept=".xlsx,.csv,.pdf"
              onChange={(event) => {
                setFile(event.target.files?.[0] ?? null);
                setPreview(null);
                setMapping({});
              }}
            />
          </label>
          <button className="secondaryButton" type="button" onClick={() => upload("/imports/preview")}>
            {preview ? "Atualizar prévia" : "Prévia"}
          </button>
          {preview ? (
            <button className="primaryButton" type="button" onClick={() => upload("/imports")}>
              Salvar validação
            </button>
          ) : null}
        </div>
      </section>

      {preview ? (
        <section className="panel validationPreviewPanel">
          <h2>Prévia da validação</h2>
          <section className="metricsGrid compactMetrics">
            <Metric label="Linhas" value={preview.summary.rowCount} />
            <Metric label="Corretas" value={preview.summary.okCount} tone="ok" />
            <Metric label="Divergentes" value={preview.summary.errorCount} tone="danger" />
          </section>

          <div className="statusGrid importStatusGrid">
            {preview.summary.byStatus.map((item) => (
              <div className="statusItem" key={item.status}>
                <span>{statusLabels[item.status]}</span>
                <strong>{item.count}</strong>
              </div>
            ))}
          </div>

          {preview.sourceType === "SPREADSHEET" ? (
            <>
              <h3>Mapeamento</h3>
              <div className="mappingGrid">
                {mappingFields.map((field) => (
                  <label key={field.key}>
                    {field.label}
                    <select
                      value={mapping[field.key] ?? ""}
                      onChange={(event) =>
                        setMapping((current) => ({ ...current, [field.key]: event.target.value || undefined }))
                      }
                    >
                      <option value="">Ignorar</option>
                      {preview.columns.map((column) => (
                        <option value={column} key={column}>
                          {column}
                        </option>
                      ))}
                    </select>
                  </label>
                ))}
              </div>
            </>
          ) : (
            <div className="notice importNotice">
              PDF de resumo por talhão detectado. A conferência usa a fazenda e os talhões em colheita cadastrados no sistema.
            </div>
          )}

          <h3>Linhas analisadas</h3>
          <div className="tableWrap">
            <table>
              <thead>
                <tr>
                  <th>Nota</th>
                  <th>Fazenda</th>
                  <th>Talhão</th>
                  <th>Cana entregue</th>
                  <th>Viagens</th>
                  <th>OS</th>
                  <th>Status</th>
                  <th>Observação</th>
                </tr>
              </thead>
              <tbody>
                {preview.rows.map((row, index) => (
                  <tr key={`${row.ticketNumber ?? "linha"}-${index}`}>
                    <td>{row.ticketNumber ?? "-"}</td>
                    <td>{row.farmRaw ?? "-"}</td>
                    <td>{row.fieldRaw ?? "-"}</td>
                    <td>{formatNumber(row.netWeight)}</td>
                    <td>{row.tripCount ?? "-"}</td>
                    <td>{row.orderRaw ?? "-"}</td>
                    <td>
                      <span className={`statusBadge ${entryStatusClass(row.status)}`}>{statusLabels[row.status]}</span>
                    </td>
                    <td>{row.notes ?? "-"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      ) : null}

      <section className="panel recentImportsPanel">
        <h2>Últimas importações</h2>
        <div className="list">
          {recentBatches.length === 0 ? (
            <span className="muted">Nenhuma importação registrada.</span>
          ) : (
            recentBatches.map((batch) => (
              <article className="listItem" key={batch.id}>
                <div>
                  <strong>{batch.fileName}</strong>
                  <span>{formatDateTime(batch.importedAt)}</span>
                </div>
                <p>
                  {batch.rowCount} linhas, {batch.okCount} OK, {batch.errorCount} divergentes
                </p>
              </article>
            ))
          )}
        </div>
      </section>
    </div>
  );
}

function HistoryView({
  batches,
  token,
  onChanged,
  onOpenBatch,
  setMessage
}: {
  batches: ImportBatch[];
  token: string;
  onChanged: () => Promise<void>;
  onOpenBatch: (batchId: string) => Promise<void>;
  setMessage: (message: string | null) => void;
}) {
  const [selectedBatchId, setSelectedBatchId] = useState<string>(batches[0]?.id ?? "");
  const [entries, setEntries] = useState<ImportBatchEntry[]>([]);
  const [loadingEntries, setLoadingEntries] = useState(false);
  const [busyBatchId, setBusyBatchId] = useState<string | null>(null);
  const [historySearch, setHistorySearch] = useState("");

  const selectedBatch = batches.find((batch) => batch.id === selectedBatchId) ?? null;
  const duplicateKeys = useMemo(() => findDuplicateBatchKeys(batches), [batches]);
  const historySearchTerms = useMemo(() => createSearchTerms(historySearch), [historySearch]);
  const visibleBatches = useMemo(() => {
    if (historySearchTerms.length === 0) {
      return batches;
    }

    return batches.filter((batch) =>
      matchesSearchText(
        buildSearchText([batch.fileName, formatBatchDateRange(batch), formatDateTime(batch.importedAt), batch.sourceType]),
        historySearchTerms
      )
    );
  }, [batches, historySearchTerms]);
  const totals = useMemo(
    () =>
      batches.reduce(
        (total, batch) => ({
          analyses: total.analyses + 1,
          rows: total.rows + batch.rowCount,
          ok: total.ok + batch.okCount,
          errors: total.errors + batch.errorCount
        }),
        { analyses: 0, rows: 0, ok: 0, errors: 0 }
      ),
    [batches]
  );

  useEffect(() => {
    if (selectedBatchId && batches.some((batch) => batch.id === selectedBatchId)) {
      return;
    }

    setSelectedBatchId(batches[0]?.id ?? "");
  }, [batches, selectedBatchId]);

  useEffect(() => {
    if (!selectedBatchId) {
      setEntries([]);
      return;
    }

    let active = true;
    setLoadingEntries(true);
    apiRequest<{ entries: ImportBatchEntry[] }>(`/imports/batches/${selectedBatchId}/entries`, token)
      .then((payload) => {
        if (active) {
          setEntries(payload.entries);
        }
      })
      .catch((error) => {
        if (active) {
          setMessage(error instanceof Error ? error.message : "Falha ao carregar analise.");
          setEntries([]);
        }
      })
      .finally(() => {
        if (active) {
          setLoadingEntries(false);
        }
      });

    return () => {
      active = false;
    };
  }, [selectedBatchId, token, setMessage]);

  async function downloadOriginal(batch: ImportBatch) {
    if (!batch.storedFileName) {
      setMessage("Essa analise foi salva antes do arquivamento de PDFs no sistema.");
      return;
    }

    setMessage(null);

    try {
      await downloadFile(`/imports/batches/${batch.id}/file`, token, batch.fileName);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Falha ao baixar PDF original.");
    }
  }

  async function downloadHighlightedOriginal(batch: ImportBatch) {
    if (!batch.storedFileName) {
      setMessage("Essa analise foi salva antes do arquivamento de PDFs no sistema.");
      return;
    }

    setMessage(null);

    try {
      await downloadFile(`/imports/batches/${batch.id}/highlighted-file`, token, batch.fileName.replace(/\.pdf$/i, "-marcado.pdf"));
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Falha ao baixar PDF marcado.");
    }
  }

  async function deleteBatch(batch: ImportBatch) {
    const confirmed = window.confirm(
      `Excluir a analise "${batch.fileName}" de ${formatDateTime(batch.importedAt)}? As entradas desse lote tambem serao removidas do painel.`
    );

    if (!confirmed) {
      return;
    }

    setBusyBatchId(batch.id);
    setMessage(null);

    try {
      await apiRequest<void>(`/imports/batches/${batch.id}`, token, { method: "DELETE" });
      setEntries([]);
      setSelectedBatchId("");
      await onChanged();
      setMessage("Analise excluida do historico.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Falha ao excluir analise.");
    } finally {
      setBusyBatchId(null);
    }
  }

  async function exportBatchCsv() {
    if (!selectedBatch) {
      return;
    }

    try {
      await downloadCsv(
        `/dashboard/divergences.csv${queryString({ batchId: selectedBatch.id })}`,
        token,
        buildAnalysisExportName(selectedBatch, "csv")
      );
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Falha ao exportar divergencias.");
    }
  }

  async function exportBatchReport() {
    if (!selectedBatch) {
      return;
    }

    try {
      await downloadFile(
        `/dashboard/divergences-report.pdf${queryString({ batchId: selectedBatch.id })}`,
        token,
        buildAnalysisExportName(selectedBatch, "pdf")
      );
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Falha ao gerar relatorio da analise.");
    }
  }

  return (
    <div className="stack historyView">
      <section className="metricsGrid compactMetrics historyMetricGrid">
        <Metric label="Análises" value={totals.analyses} />
        <Metric label="Entradas" value={totals.rows} />
        <Metric label="Corretas" value={totals.ok} tone="ok" />
        <Metric label="Divergentes" value={totals.errors} tone="danger" />
      </section>

      <section className="panel">
        <div className="sectionHeader">
          <div>
            <h2>Histórico salvo</h2>
            <span className="muted">Cada validação fica separada para consulta, exportação e auditoria.</span>
          </div>
        </div>
          <label className="searchField historySearchField">
            <Search size={17} />
            <input value={historySearch} onChange={(event) => setHistorySearch(event.target.value)} placeholder="Buscar arquivo ou data" />
          </label>
        <div className="tableWrap">
          <table className="historyTable">
            <thead>
              <tr>
                <th>Data PDF</th>
                <th>Arquivo</th>
                <th>Salvo em</th>
                <th>Linhas</th>
                <th>OK</th>
                <th>Divergentes</th>
                <th>PDF</th>
                <th>Ações</th>
              </tr>
            </thead>
            <tbody>
              {visibleBatches.length === 0 ? (
                <tr>
                  <td colSpan={8}>Nenhuma análise registrada.</td>
                </tr>
              ) : (
                visibleBatches.map((batch) => {
                  const duplicate = duplicateKeys.has(batchDuplicateKey(batch));

                  return (
                    <tr key={batch.id} className={selectedBatchId === batch.id ? "selectedRow" : undefined}>
                      <td>{formatBatchDateRange(batch)}</td>
                      <td>
                        <div className="tableCellStack">
                          <strong>{batch.fileName}</strong>
                          {duplicate ? <span className="statusBadge warning">Possível duplicado</span> : null}
                        </div>
                      </td>
                      <td>{formatDateTime(batch.importedAt)}</td>
                      <td>{batch.rowCount}</td>
                      <td>{batch.okCount}</td>
                      <td>{batch.errorCount}</td>
                      <td>{batch.storedFileName ? formatFileSize(batch.fileSize ?? 0) : "Nao arquivado"}</td>
                      <td>
                        <div className="rowActions">
                          <button className="secondaryButton compactButton" type="button" onClick={() => setSelectedBatchId(batch.id)}>
                            <Eye size={16} />
                            Detalhes
                          </button>
                          <button className="secondaryButton compactButton" type="button" onClick={() => onOpenBatch(batch.id)}>
                            <Filter size={16} />
                            Resultado
                          </button>
                          <button
                            className="secondaryButton compactButton"
                            type="button"
                            onClick={() => downloadOriginal(batch)}
                            disabled={!batch.storedFileName}
                          >
                            <Download size={16} />
                            PDF Original
                          </button>
                          <button
                            className="secondaryButton compactButton"
                            type="button"
                            onClick={() => downloadHighlightedOriginal(batch)}
                            disabled={!batch.storedFileName}
                            title="Baixar PDF com as divergências destacadas em amarelo"
                          >
                            <Download size={16} />
                            PDF Marcado
                          </button>
                          <button
                            className="secondaryButton compactButton dangerButton"
                            type="button"
                            onClick={() => deleteBatch(batch)}
                            disabled={busyBatchId === batch.id}
                          >
                            <Trash2 size={16} />
                            Excluir
                          </button>
                        </div>
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      </section>

      <section className="panel">
        <div className="sectionHeader">
          <div>
            <h2>Detalhe da análise</h2>
            <span className="muted">{selectedBatch ? formatBatchOption(selectedBatch) : "Selecione uma análise no histórico."}</span>
          </div>
          {selectedBatch ? (
            <div className="rowActions">
              <button className="secondaryButton compactButton" type="button" onClick={exportBatchCsv}>
                <Download size={16} />
                CSV
              </button>
              <button className="secondaryButton compactButton" type="button" onClick={exportBatchReport}>
                <FileText size={16} />
                Relatório
              </button>
            </div>
          ) : null}
        </div>

        <div className="tableWrap">
          <table>
            <thead>
              <tr>
                <th>Data</th>
                <th>Nota</th>
                <th>Fazenda</th>
                <th>Talhão</th>
                <th>OS</th>
                <th>Cana entregue</th>
                <th>Status</th>
                <th>Observação</th>
              </tr>
            </thead>
            <tbody>
              {loadingEntries ? (
                <tr>
                  <td colSpan={8}>Carregando análise...</td>
                </tr>
              ) : entries.length === 0 ? (
                <tr>
                  <td colSpan={8}>Nenhuma linha para exibir.</td>
                </tr>
              ) : (
                entries.map((entry) => (
                  <tr key={entry.id}>
                    <td>{entry.entryDate ? formatDateOnly(entry.entryDate) : "-"}</td>
                    <td>{entry.ticketNumber ?? "-"}</td>
                    <td>{entry.farmNameRaw ?? "-"}</td>
                    <td>{entry.fieldCodeRaw ?? "-"}</td>
                    <td>{entry.orderNumberRaw ?? "-"}</td>
                    <td>{formatNumber(entry.netWeight)}</td>
                    <td>
                      <span className={`statusBadge ${entryStatusClass(entry.status)}`}>{statusLabels[entry.status]}</span>
                    </td>
                    <td>{entry.notes ?? "-"}</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}

function NavButton({ active, icon, label, onClick }: { active: boolean; icon: ReactNode; label: string; onClick: () => void }) {
  return (
    <button className={active ? "navButton active" : "navButton"} onClick={onClick}>
      {icon}
      {label}
    </button>
  );
}

function Metric({ label, value, tone }: { label: string; value: number | string; tone?: "ok" | "danger" | "info" }) {
  return (
    <article className={`metric ${tone ?? ""}`}>
      <span>{label}</span>
      <strong>{value}</strong>
    </article>
  );
}

function HarvestKpi({
  label,
  value,
  tone,
  unit,
  subValue
}: {
  label: string;
  value: number | string;
  tone: "blue" | "cyan" | "green" | "orange" | "red" | "pink" | "teal" | "gray";
  unit?: string;
  subValue?: string;
}) {
  return (
    <article className={`harvestKpi ${tone}`}>
      <span>{label}</span>
      <div className="harvestKpiValue">
        <strong>{value}</strong>
        {unit ? <em>{unit}</em> : null}
      </div>
      {subValue ? <small>{subValue}</small> : <small aria-hidden="true" />}
    </article>
  );
}

function OwnershipBadge({ type }: { type: HarvestOwnershipType }) {
  return <span className={`ownershipBadge ${type.toLowerCase()}`}>{ownershipLabels[type]}</span>;
}

function hasFullAccess(user: User | null) {
  return user?.role === "ADMIN" || user?.role === "ANALYST";
}

function cleanFilters(filters: DashboardFilters): DashboardFilters {
  return Object.fromEntries(
    Object.entries(filters).filter(([, value]) => value !== undefined && value !== "")
  ) as DashboardFilters;
}

function cleanResultFilters(filters: DashboardFilters): DashboardFilters {
  const { from: _from, to: _to, ...visibleFilters } = filters;
  return cleanFilters(visibleFilters);
}

function toQueryFilters(filters: DashboardFilters) {
  return {
    batchId: filters.batchId,
    status: filters.status,
    farmId: filters.farmId,
    from: filters.from,
    to: filters.to,
    order: filters.order,
    fileName: filters.fileName
  };
}

function formatDateTime(value: string) {
  const date = new Date(value);

  if (Number.isNaN(date.getTime())) {
    return value;
  }

  return new Intl.DateTimeFormat("pt-BR", {
    dateStyle: "short",
    timeStyle: "short"
  }).format(date);
}

function parseDateSortValue(value: string | null | undefined) {
  const timestamp = value ? new Date(value).getTime() : Number.MAX_SAFE_INTEGER;
  return Number.isNaN(timestamp) ? Number.MAX_SAFE_INTEGER : timestamp;
}

function formatDateOnly(value: string) {
  const dateOnly = /^(\d{4})-(\d{2})-(\d{2})/.exec(value);

  if (dateOnly) {
    return `${dateOnly[3]}/${dateOnly[2]}/${dateOnly[1]}`;
  }

  return value;
}

function formatBatchDateRange(batch: ImportBatch) {
  const isPdf = isPdfReportBatch(batch);
  const startDate = isPdf ? batch.periodStart ?? batch.reportDate : batch.periodStart ?? batch.entryDateFrom;
  const endDate = isPdf ? batch.periodEnd ?? batch.reportDate : batch.periodEnd ?? batch.entryDateTo;

  if (!startDate) {
    return isPdf ? "Sem data do PDF" : "-";
  }

  if (!endDate || endDate === startDate) {
    return formatDateOnly(startDate);
  }

  return `${formatDateOnly(startDate)} a ${formatDateOnly(endDate)}`;
}

function formatBatchOption(batch: ImportBatch) {
  const date = formatBatchDateRange(batch);
  return `${date} - ${batch.fileName} (${batch.rowCount} linhas)`;
}

function buildAvailableReports(batches: ImportBatch[]) {
  const reports = new Map<string, AvailableReport>();

  for (const batch of batches) {
    if (!isPdfReportBatch(batch)) {
      continue;
    }

    const start = batch.periodStart ?? batch.reportDate;
    if (!start) {
      continue;
    }

    const end = batch.periodEnd ?? batch.reportDate ?? start;
    const key = `${start}|${end}`;
    const current =
      reports.get(key) ??
      ({
        key,
        start,
        end,
        label: formatPeriodLabel(start, end),
        analyses: 0,
        rows: 0,
        ok: 0,
        errors: 0,
        fileNames: [],
        reportDates: [],
        latestImportedAt: undefined
      } satisfies AvailableReport);

    current.analyses += 1;
    current.rows += batch.rowCount;
    current.ok += batch.okCount;
    current.errors += batch.errorCount;

    if (!current.fileNames.includes(batch.fileName)) {
      current.fileNames.push(batch.fileName);
    }

    if (batch.reportDate && !current.reportDates.includes(batch.reportDate)) {
      current.reportDates.push(batch.reportDate);
      current.reportDates.sort();
    }

    if (!current.latestImportedAt || batch.importedAt.localeCompare(current.latestImportedAt) > 0) {
      current.latestImportedAt = batch.importedAt;
    }

    reports.set(key, current);
  }

  return Array.from(reports.values()).sort((left, right) => right.start.localeCompare(left.start) || right.end.localeCompare(left.end));
}

function summarizePdfImportBatches(batches: ImportBatch[]) {
  return batches.reduce(
    (total, batch) => {
      if (!isPdfReportBatch(batch)) {
        return total;
      }

      return {
        batches: total.batches + 1,
        rows: total.rows + batch.rowCount
      };
    },
    { batches: 0, rows: 0 }
  );
}

function isPdfReportBatch(batch: ImportBatch) {
  return batch.sourceType === "SCS0110P_PDF" || /\.pdf$/i.test(batch.fileName);
}

function reportToFilters(report: AvailableReport): DashboardFilters {
  return {
    from: report.start,
    to: report.end
  };
}

function buildAvailableReportName(report: AvailableReport, extension: "csv" | "pdf") {
  const datePart = report.start === report.end ? report.start : `${report.start}-a-${report.end}`;
  return `divergencias-${datePart.replaceAll("-", "")}.${extension}`;
}

function formatReportFileList(fileNames: string[]) {
  if (fileNames.length === 0) {
    return "Sem arquivo vinculado";
  }

  const visible = fileNames.slice(0, 2).join(" · ");
  const hiddenCount = fileNames.length - 2;
  return hiddenCount > 0 ? `${visible} · +${hiddenCount}` : visible;
}

function formatReportDateList(reportDates: string[]) {
  if (reportDates.length === 0) {
    return "Sem data de emissão";
  }

  const visible = reportDates.slice(0, 2).map(formatDateOnly).join(", ");
  const hiddenCount = reportDates.length - 2;
  return hiddenCount > 0 ? `${visible}, +${hiddenCount}` : visible;
}

function formatProductionPeriod(start: string | null | undefined, end: string | null | undefined) {
  if (!start) {
    return "Sem data do PDF";
  }

  return formatPeriodLabel(start, end ?? start);
}

function formatHarvestPeriodCard(start: string | null | undefined, end: string | null | undefined) {
  const startDate = parseDateParts(start);
  const endDate = parseDateParts(end ?? start);

  if (!startDate) {
    return { value: "Sem data", subValue: "PDF" };
  }

  if (!endDate || start === end) {
    return { value: `${startDate.day}/${startDate.month}`, subValue: startDate.year };
  }

  if (startDate.year === endDate.year) {
    return { value: `${startDate.day}/${startDate.month} a ${endDate.day}/${endDate.month}`, subValue: endDate.year };
  }

  return {
    value: `${startDate.day}/${startDate.month}/${startDate.year.slice(-2)}`,
    subValue: `a ${endDate.day}/${endDate.month}/${endDate.year.slice(-2)}`
  };
}

function parseDateParts(value: string | null | undefined) {
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(value ?? "");

  return match ? { year: match[1], month: match[2], day: match[3] } : null;
}

function formatPeriodLabel(start: string, end: string) {
  return start === end ? formatDateOnly(start) : `${formatDateOnly(start)} a ${formatDateOnly(end)}`;
}

function batchDuplicateKey(batch: ImportBatch) {
  if (batch.fileHash) {
    return `hash:${batch.fileHash}`;
  }

  return [batch.fileName, batch.entryDateFrom ?? "", batch.entryDateTo ?? "", batch.rowCount, batch.okCount, batch.errorCount].join("|");
}

function findDuplicateBatchKeys(batches: ImportBatch[]) {
  const counts = new Map<string, number>();

  for (const batch of batches) {
    const key = batchDuplicateKey(batch);
    counts.set(key, (counts.get(key) ?? 0) + 1);
  }

  return new Set(Array.from(counts.entries()).filter((entry) => entry[1] > 1).map((entry) => entry[0]));
}

function buildAnalysisExportName(batch: ImportBatch, extension: "csv" | "pdf") {
  const date =
    (isPdfReportBatch(batch) ? batch.periodStart ?? batch.reportDate : batch.periodStart ?? batch.entryDateFrom)?.replaceAll("-", "") ??
    (isPdfReportBatch(batch) ? "sem-data-pdf" : "analise");
  const base = batch.fileName.replace(/\.[^.]+$/, "").replace(/[^\w.-]+/g, "-").replace(/^-+|-+$/g, "");
  return `${date}-${base || "balanca"}.${extension}`;
}

function formatNumber(value: number | null | undefined) {
  if (value === undefined || value === null) {
    return "-";
  }

  return new Intl.NumberFormat("pt-BR", {
    minimumFractionDigits: 3,
    maximumFractionDigits: 3
  }).format(value);
}

function formatShortNumber(value: number | null | undefined) {
  if (value === null || value === undefined) {
    return "-";
  }

  return new Intl.NumberFormat("pt-BR", {
    minimumFractionDigits: value % 1 === 0 ? 0 : 2,
    maximumFractionDigits: 2
  }).format(value);
}

function formatAreaInput(value: number | null | undefined) {
  return value === null || value === undefined ? "" : String(value).replace(".", ",");
}

function parseAreaInput(value: string) {
  const trimmed = value.trim();

  if (!trimmed) {
    return undefined;
  }

  const number = Number(trimmed.replace(",", "."));
  return Number.isFinite(number) && number >= 0 ? number : undefined;
}



function createFieldDraft(): FieldDraft {
  const id =
    typeof crypto !== "undefined" && "randomUUID" in crypto
      ? crypto.randomUUID()
      : `${Date.now()}-${Math.random().toString(16).slice(2)}`;

  return { id, code: "", areaAlq: "" };
}

function parseFieldDrafts(drafts: FieldDraft[]): { fields: Array<string | { code: string; areaAlq: number }> } | { error: string } {
  const fields: Array<string | { code: string; areaAlq: number }> = [];
  const seenCodes = new Set<string>();

  for (const draft of drafts) {
    const code = draft.code.trim();
    const areaText = draft.areaAlq.trim();

    if (!code && !areaText) {
      continue;
    }

    if (!code && areaText) {
      return { error: "Informe o talhao antes da area." };
    }

    const areaAlq = parseAreaInput(areaText);

    if (areaText && areaAlq === undefined) {
      return { error: "Informe um valor valido de alqueires." };
    }

    const normalizedCode = code.toLocaleLowerCase("pt-BR");
    if (seenCodes.has(normalizedCode)) {
      continue;
    }

    seenCodes.add(normalizedCode);
    fields.push(areaAlq === undefined ? code : { code, areaAlq });
  }

  return { fields };
}

function formatPercent(value: number) {
  return `${value.toFixed(1).replace(".", ",")}%`;
}

function progressStyle(value: number, total: number): CSSProperties {
  const percent = total > 0 ? Math.max(2, Math.min(100, (value / total) * 100)) : 0;

  return { "--bar-size": `${percent}%` } as CSSProperties;
}

function buildFleetReportFileName(fileName: string) {
  const base = fileName.replace(/\.[^.]+$/, "") || "frotas";
  return `${base}-relatorio-frotas.pdf`;
}

function createEmptyFleetMovementForm(): FleetMovementForm {
  return {
    movementType: "LEFT_MILL",
    equipmentCode: "",
    equipmentType: "OUTRO",
    frontNumber: "",
    reserveCode: "",
    replacesCode: "",
    reason: "",
    occurredAt: toDateTimeLocalValue(new Date())
  };
}

function optionalText(value: string) {
  const trimmed = value.trim();
  return trimmed || undefined;
}

function normalizeDateTimeInput(value: string) {
  if (!value.trim()) {
    return undefined;
  }

  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? undefined : date.toISOString();
}

function toDateTimeLocalValue(date: Date) {
  const timezoneOffset = date.getTimezoneOffset() * 60_000;
  return new Date(date.getTime() - timezoneOffset).toISOString().slice(0, 16);
}

function validateFleetMovement(form: FleetMovementForm, preview: FleetReportPreview | null): FleetMovementValidation {
  const equipmentCode = form.equipmentCode.trim();
  const reserveCode = form.reserveCode.trim();
  const replacesCode = form.replacesCode.trim();
  const frontNumber = form.frontNumber.trim() ? Number(form.frontNumber) : null;
  const isReserveMovement = form.movementType === "RESERVE_ACTIVATED" || form.movementType === "RESERVE_RELEASED";
  const effectiveCode = isReserveMovement ? reserveCode || equipmentCode : equipmentCode;

  if (!equipmentCode) {
    return { tone: "warning", messages: ["Informe a frota para validar contra a base."], blocksSubmit: false };
  }

  if (!preview) {
    return {
      tone: "danger",
      messages: ["Carregue a base de frotas antes de lançar movimentação."],
      blocksSubmit: true
    };
  }

  const equipment = findFleetEquipment(preview, effectiveCode);
  const replacement = replacesCode ? findFleetEquipment(preview, replacesCode) : null;
  const messages: string[] = [];
  let blocksSubmit = false;
  let tone: FleetMovementValidation["tone"] = "ok";

  if (equipment) {
    messages.push(
      `Frota ${effectiveCode} encontrada na ${equipment.frontName}: ${equipment.typeLabel}, status ${equipment.statusLabel.toLowerCase()}.`
    );

    if (frontNumber && equipment.frontNumber && equipment.frontNumber !== frontNumber && form.movementType !== "RESERVE_ACTIVATED") {
      messages.push(`Essa frota nao faz parte da Frente ${frontNumber}; ela esta na Frente ${equipment.frontNumber}.`);
      blocksSubmit = true;
      tone = "danger";
    }

    if (form.movementType === "LEFT_MILL") {
      messages.push(`Ao registrar, a frota ${effectiveCode} fica verde no relatório.`);
    }

    if (form.movementType === "RETURNED_MILL" || form.movementType === "RESERVE_RELEASED") {
      messages.push(`Ao registrar, a frota ${effectiveCode} fica vermelha no relatório.`);
    }
  } else if (isReserveMovement) {
    messages.push(`Frota ${effectiveCode} nao esta na base; ela sera tratada como reserva lançada na frente informada.`);
    tone = "warning";

    if (!frontNumber) {
      messages.push("Informe a frente para o sistema posicionar essa frota reserva no relatório.");
      blocksSubmit = true;
      tone = "danger";
    }

    if (!fleetEquipmentTypeAffectsReport(form.equipmentType)) {
      messages.push("Escolha o tipo da frota reserva para ela entrar na coluna correta do relatório.");
      blocksSubmit = true;
      tone = "danger";
    }
  } else {
    messages.push(`Frota ${effectiveCode} nao foi encontrada na base. Se for reserva, use o fluxo "Reserva usado".`);
    blocksSubmit = true;
    tone = "danger";
  }

  if (replacesCode) {
    if (replacement) {
      messages.push(`Substituição informada: ${effectiveCode} substitui ${replacesCode} (${replacement.frontName}).`);

      if (frontNumber && replacement.frontNumber && replacement.frontNumber !== frontNumber) {
        messages.push(`A frota substituída ${replacesCode} nao faz parte da Frente ${frontNumber}; ela esta na Frente ${replacement.frontNumber}.`);
        blocksSubmit = true;
        tone = "danger";
      }
    } else {
      messages.push(`A frota substituída ${replacesCode} nao foi encontrada na base.`);
      tone = tone === "danger" ? "danger" : "warning";
    }
  } else if (form.movementType === "RESERVE_ACTIVATED") {
    messages.push("Sem frota substituída: o reserva será somado à frente como entrada extra.");
    tone = tone === "danger" ? "danger" : "warning";
  }

  return { tone, messages, blocksSubmit };
}

function fleetEquipmentTypeAffectsReport(type: FleetEquipmentType) {
  return type !== "ONIBUS" && type !== "OUTRO";
}

function findFleetEquipment(preview: FleetReportPreview, code: string) {
  const normalizedCode = normalizeFleetCode(code);
  return preview.equipment.find((item) => normalizeFleetCode(item.code) === normalizedCode) ?? null;
}

function normalizeFleetCode(value: string) {
  return value
    .normalize("NFD")
    .replace(/\p{Diacritic}/gu, "")
    .replace(/[^a-zA-Z0-9]/g, "")
    .toUpperCase();
}

function buildFieldReuseWarnings(
  orders: HarvestOrder[],
  fieldIds: string[],
  _selectedFrontNumbers: number[],
  ignoredOrderId?: string | null
) {
  const warnings = new Map<string, string>();

  for (const order of orders) {
    if (order.status !== "ACTIVE" || order.id === ignoredOrderId) {
      continue;
    }

    for (const item of order.fields) {
      if (!fieldIds.includes(item.fieldId)) {
        continue;
      }

      const frontNumbers = getOrderFrontNumbers(order);
      const location = frontNumbers.length ? formatFrontNumbers(frontNumbers) : `OS ${order.number} sem frente`;
      const state = frontNumbers.length ? "em colheita" : "liberado";
      warnings.set(item.fieldId, `Talhão ${item.field.code} ja esta ${state} na ${location}`);
    }
  }

  return [...warnings.values()];
}

function parseBulkCloseOrderNumbers(value: string) {
  const seen = new Set<string>();
  const numbers: string[] = [];

  for (const item of value.split(/[\s,;]+/)) {
    const number = item.trim();
    const normalized = normalizeBulkCloseOrderNumber(number);

    if (!number || seen.has(normalized)) {
      continue;
    }

    seen.add(normalized);
    numbers.push(number);
  }

  return numbers;
}

function formatBulkCloseOrderInput(value: string) {
  const numbers = parseBulkCloseOrderNumbers(value);

  if (numbers.length === 0) {
    return "";
  }

  const shouldTerminate = /[\s,;]+$/.test(value);
  return `${numbers.join("; ")}${shouldTerminate ? "; " : ""}`;
}

function normalizeBulkCloseOrderNumber(value: string) {
  return value.trim().toUpperCase();
}

function summarizeBulkCloseResults(results: BulkCloseOrderResult[]) {
  return {
    closed: results.filter((result) => result.status === "CLOSED").length,
    alreadyClosed: results.filter((result) => result.status === "ALREADY_CLOSED").length,
    notFound: results.filter((result) => result.status === "NOT_FOUND").length
  };
}

function bulkCloseStatusClass(status: BulkCloseOrderResult["status"]) {
  return {
    CLOSED: "closed",
    ALREADY_CLOSED: "alreadyClosed",
    NOT_FOUND: "notFound"
  }[status];
}

function bulkCloseStatusLabel(status: BulkCloseOrderResult["status"]) {
  return {
    CLOSED: "Fechada",
    ALREADY_CLOSED: "Ja fechada",
    NOT_FOUND: "Nao encontrada"
  }[status];
}

function formatBulkCloseResultDetails(result: BulkCloseOrderResult) {
  const details = [
    result.message,
    result.fronts?.length ? formatFrontNumbers(result.fronts) : null,
    result.farms?.length ? result.farms.slice(0, 2).join("; ") : null,
    result.farms && result.farms.length > 2 ? `+${result.farms.length - 2} fazenda(s)` : null
  ].filter(Boolean);

  return details.join(" - ");
}

function formatOrderLabel(order: HarvestOrder) {
  return `OS ${order.number} - ${formatFrontNumbers(getOrderFrontNumbers(order))} - ${formatOrderFarmNames(order)} - talhões ${order.fields.map((item) => item.field.code).join(", ")}`;
}

function getOrderFrontNumbers(order: HarvestOrder) {
  return order.frontNumbers?.length ? order.frontNumbers : order.frontNumber ? [order.frontNumber] : [];
}

function formatFrontNumbers(frontNumbers: number[]) {
  if (frontNumbers.length === 0) {
    return "Sem frente";
  }

  if (frontNumbers.length === 1) {
    return `Frente ${frontNumbers[0]}`;
  }

  return `Frentes ${frontNumbers.join(", ")}`;
}

function formatOrderHistoryEventLabel(event: HarvestOrderHistory) {
  if (event.eventType === "STARTED") {
    return "Iniciada";
  }

  if (event.eventType === "RELEASED") {
    return "Liberada sem frente";
  }

  if (event.eventType === "CLOSED") {
    return "Fechada";
  }

  if (event.eventType === "REOPENED") {
    return "Reaberta";
  }

  return "Frente alterada";
}

function formatOrderHistoryFronts(event: HarvestOrderHistory) {
  if (event.eventType === "FRONTS_CHANGED") {
    return `${formatFrontNumbers(event.frontNumbersBefore)} -> ${formatFrontNumbers(event.frontNumbersAfter)}`;
  }

  const frontNumbers = event.eventType === "CLOSED" || event.eventType === "REOPENED" ? event.frontNumbersBefore : event.frontNumbersAfter;

  return formatFrontNumbers(frontNumbers);
}

function getOrderFarms(order: HarvestOrder) {
  return order.farms?.length ? order.farms : [order.farm].filter(Boolean);
}



function getOrderFarmFieldGroups(order: HarvestOrder) {
  return getOrderFarms(order).map((farm) => ({
    farm,
    fields: order.fields.filter((item) => item.field.farmId === farm.id).map((item) => item.field.code)
  }));
}

function formatOrderFarmNames(order: HarvestOrder) {
  const farms = getOrderFarms(order);

  if (farms.length === 0) {
    return "Fazenda nao informada";
  }

  if (farms.length === 1) {
    return formatFarmLabel(farms[0]);
  }

  const visibleNames = farms.slice(0, 3).map(formatFarmLabel).join(", ");
  const hiddenCount = farms.length - 3;

  return hiddenCount > 0 ? `${visibleNames} +${hiddenCount}` : visibleNames;
}

function formatFarmListByIds(farms: Farm[], farmIds: string[]) {
  const names = farmIds
    .map((farmId) => farms.find((farm) => farm.id === farmId))
    .filter((farm): farm is Farm => Boolean(farm))
    .map(formatFarmLabel);

  if (names.length === 0) {
    return "fazendas anteriores";
  }

  if (names.length <= 2) {
    return names.join(" e ");
  }

  return `${names.slice(0, 2).join(", ")} +${names.length - 2}`;
}

function findActiveOrderByNumber(orders: HarvestOrder[], osNumber: string) {
  const normalizedOsNumber = normalizeOrderNumberForMatch(osNumber);

  if (!normalizedOsNumber) {
    return null;
  }

  return orders.find((order) => normalizeOrderNumberForMatch(order.number) === normalizedOsNumber) ?? null;
}

function normalizeOrderNumberForMatch(value: string) {
  return normalizeSearchText(value).toUpperCase();
}

function formatFarmLabel(farm: Farm) {
  return farm.code ? `${farm.code} - ${farm.name}` : farm.name;
}

function formatFarmCodeName(code: string | null | undefined, name: string) {
  return code ? `${code} - ${name}` : name;
}

function postHarvestStatusLabel(status: PostHarvestIntegrationStatus) {
  if (status === "SENT") {
    return "Enviado";
  }

  if (status === "ERROR") {
    return "Erro";
  }

  if (status === "PROCESSING") {
    return "Processando";
  }

  if (status === "DEAD") {
    return "Dead-letter";
  }

  return "Pendente";
}

function postHarvestStatusClass(status: PostHarvestIntegrationStatus) {
  if (status === "SENT") {
    return "ok";
  }

  if (status === "ERROR") {
    return "danger";
  }

  if (status === "PROCESSING") {
    return "info";
  }

  if (status === "DEAD") {
    return "danger";
  }

  return "warning";
}

function postHarvestActionLabel(status: PostHarvestIntegrationStatus, isAdmin: boolean) {
  if (!isAdmin) {
    return "Somente administrador";
  }

  if (status === "SENT") {
    return "Concluido";
  }

  if (status === "PROCESSING") {
    return "Em processamento";
  }

  if (status === "DEAD") {
    return "Intervencao necessaria";
  }

  return "Sem acao";
}

function normalizeFarmCodeForCompare(code: string | null | undefined) {
  return String(code ?? "").replace(/\D/g, "").replace(/^0+(?=\d)/, "");
}


function compareFarmsByCode(left: Farm, right: Farm) {
  const leftCode = parseFarmCodeForSort(left.code);
  const rightCode = parseFarmCodeForSort(right.code);

  if (leftCode.group !== rightCode.group) {
    return leftCode.group - rightCode.group;
  }

  if (leftCode.number !== rightCode.number) {
    return leftCode.number - rightCode.number;
  }

  return formatFarmLabel(left).localeCompare(formatFarmLabel(right), "pt-BR", { numeric: true, sensitivity: "base" });
}

function parseFarmCodeForSort(code: string | null | undefined) {
  if (!code) {
    return { group: Number.MAX_SAFE_INTEGER, number: Number.MAX_SAFE_INTEGER };
  }

  const normalized = code.trim();
  const groups = normalized.match(/\d+/g) ?? [];

  if (groups.length >= 2) {
    return {
      group: Number(groups[0]),
      number: Number(groups[1])
    };
  }

  if (groups.length === 1 && groups[0].length > 3) {
    return {
      group: Number(groups[0].slice(0, 3)),
      number: Number(groups[0].slice(3))
    };
  }

  if (groups.length === 1) {
    return {
      group: Number(groups[0]),
      number: 0
    };
  }

  return { group: Number.MAX_SAFE_INTEGER, number: Number.MAX_SAFE_INTEGER };
}

function compareFieldCodeText(left: string, right: string) {
  const leftNumber = /^\d+$/.test(left) ? Number(left) : null;
  const rightNumber = /^\d+$/.test(right) ? Number(right) : null;

  if (leftNumber !== null && rightNumber !== null && leftNumber !== rightNumber) {
    return leftNumber - rightNumber;
  }

  return left.localeCompare(right, "pt-BR", { numeric: true, sensitivity: "base" });
}

function summarizeFarmRegistry(farms: Farm[]) {
  return farms.reduce(
    (summary, farm) => {
      const fieldSummary = summarizeFields(farm.fields);

      return {
        farmCount: summary.farmCount + 1,
        fieldCount: summary.fieldCount + farm.fields.length,
        areaHa: summary.areaHa + fieldSummary.areaHa,
        areaAlq: summary.areaAlq + fieldSummary.areaAlq
      };
    },
    { farmCount: 0, fieldCount: 0, areaHa: 0, areaAlq: 0 }
  );
}

function summarizeFields(fields: Farm["fields"]) {
  return fields.reduce(
    (summary, field) => ({
      areaHa: summary.areaHa + (field.areaHa ?? 0),
      areaAlq: summary.areaAlq + (field.areaAlq ?? 0)
    }),
    { areaHa: 0, areaAlq: 0 }
  );
}

function summarizeActiveOrders(orders: HarvestOrder[]) {
  const summary = orders.reduce(
    (summary, order) => {
      const orderSummary = summarizeOrderFields(order);

      return {
        frontCount: summary.frontCount + getOrderFrontNumbers(order).length,
        fieldCount: summary.fieldCount + order.fields.length,
        areaHa: summary.areaHa + orderSummary.areaHa,
        areaAlq: summary.areaAlq + orderSummary.areaAlq,
        farmIds: new Set([...summary.farmIds, ...getOrderFarms(order).map((farm) => farm.id)])
      };
    },
    { frontCount: 0, fieldCount: 0, areaHa: 0, areaAlq: 0, farmIds: new Set<string>() }
  );

  return {
    frontCount: summary.frontCount,
    farmCount: summary.farmIds.size,
    fieldCount: summary.fieldCount,
    areaHa: summary.areaHa,
    areaAlq: summary.areaAlq
  };
}

function summarizeOrderFields(order: HarvestOrder) {
  return order.fields.reduce(
    (summary, item) => ({
      areaHa: summary.areaHa + (item.field.areaHa ?? 0),
      areaAlq: summary.areaAlq + (item.field.areaAlq ?? 0)
    }),
    { areaHa: 0, areaAlq: 0 }
  );
}

function normalizeSearchText(value: string) {
  return value
    .normalize("NFD")
    .replace(/\p{Diacritic}/gu, "")
    .toLowerCase()
    .trim();
}

type FieldSearchEntry = {
  field: Farm["fields"][number];
  searchText: string;
};

type FarmSearchEntry = {
  farm: Farm;
  headerText: string;
  fullText: string;
  fields: FieldSearchEntry[];
};

function createFarmSearchEntry(farm: Farm): FarmSearchEntry {
  const headerText = buildFarmHeaderSearchText(farm);
  const fields = farm.fields.map((field) => ({
    field,
    searchText: buildFieldSearchText(field)
  }));

  return {
    farm,
    headerText,
    fullText: [headerText, ...fields.map((field) => field.searchText)].join(" "),
    fields
  };
}

function buildFarmHeaderSearchText(farm: Farm) {
  return buildSearchText([
    farm.code,
    compactNumericCode(farm.code),
    farm.name,
    farm.city,
    farm.propertyNumber,
    farm.sequenceNumber,
    farm.sectionName,
    farm.ownerName,
    farm.municipality
  ]);
}

function compactNumericCode(value: string | null | undefined) {
  const compacted = value?.replace(/\D/g, "") ?? "";
  return compacted && compacted !== value ? compacted : undefined;
}

function formatFarmMetadataLine(farm: Farm) {
  const parts = [farm.ownerName, farm.municipality ?? farm.city].filter((value): value is string => Boolean(value));
  return parts.length > 0 ? parts.join(" - ") : "Município não informado";
}

function buildFieldSearchText(field: Farm["fields"][number]) {
  return buildSearchText([field.code, field.name, field.cropYear, field.areaType]);
}

function createSearchTerms(value: string) {
  const normalized = normalizeSearchText(value);

  if (!normalized) {
    return [];
  }

  return Array.from(new Set(normalized.split(/\s+/).filter(Boolean)));
}

function buildSearchText(values: Array<string | number | null | undefined>) {
  const parts: string[] = [];

  for (const value of values) {
    if (value === null || value === undefined) {
      continue;
    }

    const normalized = normalizeSearchText(String(value));

    if (!normalized) {
      continue;
    }

    parts.push(normalized);

    for (const token of normalized.split(/\s+/)) {
      const numericToken = normalizeNumericSearchToken(token);

      if (numericToken && numericToken !== token) {
        parts.push(numericToken);
      }
    }
  }

  return Array.from(new Set(parts)).join(" ");
}

function matchesSearchText(searchText: string, terms: string[]) {
  return terms.every((term) => matchesSearchTerm(searchText, term));
}

function matchesAnySearchTerm(searchText: string, terms: string[]) {
  return terms.some((term) => matchesSearchTerm(searchText, term));
}

function matchesSearchTerm(searchText: string, term: string) {
  if (searchText.includes(term)) {
    return true;
  }

  const numericTerm = normalizeNumericSearchToken(term);
  return Boolean(numericTerm && numericTerm !== term && searchText.includes(numericTerm));
}

function normalizeNumericSearchToken(value: string) {
  return /^\d+$/.test(value) ? String(Number(value)) : null;
}

function entryStatusClass(status: EntryStatus) {
  if (status === "OK") {
    return "ok";
  }

  if (status === "MISSING_DATA" || status === "OS_NOT_FOUND") {
    return "warning";
  }

  return "danger";
}

function compareFrontNumbers(left?: number | null, right?: number | null) {
  return (left ?? Number.MAX_SAFE_INTEGER) - (right ?? Number.MAX_SAFE_INTEGER);
}





function isOrderVisibleInCurrentYear(order: HarvestOrder, currentYear: number) {
  if (order.status === "ACTIVE") {
    return true;
  }

  return [order.startDate, order.endDate].some((value) => {
    if (!value) {
      return false;
    }

    const date = new Date(value);
    return !Number.isNaN(date.getTime()) && date.getFullYear() === currentYear;
  });
}







function getDateTime(value: string | null | undefined) {
  if (!value) {
    return 0;
  }

  const timestamp = Date.parse(value);
  return Number.isNaN(timestamp) ? 0 : timestamp;
}

























function FarmMetadataStrip({ farm, compact = false }: { farm: Farm; compact?: boolean }) {
  const items = [{ label: "Área", value: `${formatNumber(farm.areaHa ?? 0)} ha` }];

  if (items.length === 0) {
    return null;
  }

  return (
    <div className={`farmMetadataStrip ${compact ? "compact" : ""}`}>
      {items.map((item) => (
        <span key={item.label}>
          <strong>{item.label}</strong> {item.value}
        </span>
      ))}
    </div>
  );
}





















































































































function parseFieldCodes(value: string) {
  return Array.from(
    new Set(
      value
        .split(/[\s,;]+/)
        .map((item) => item.trim())
        .filter(Boolean)
    )
  );
}

















export type ApportionmentResult = {
  orderId: string;
  orderNumber: string;
  farmName: string;
  farmCode: string;
  weightUnit: "t";
  totalAreaHa: number;
  totalWeight: number;
  allocatedWeight: number;
  unassignedWeight: number;
  farms: Array<{
    farmId: string;
    farmCode: string;
    farmName: string;
    totalAreaHa: number;
    totalWeight: number;
  }>;
  fields: Array<{
    fieldId: string;
    fieldCode: string;
    farmId: string;
    farmCode: string;
    farmName: string;
    areaHa: number;
    percentage: number;
    farmPercentage: number;
    proratedWeight: number;
    harvested: boolean;
  }>;
};

function ApportionmentView({ token, yearQuerySuffix = "" }: { token: string; yearQuerySuffix?: string }) {
  const [data, setData] = useState<ApportionmentResult[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selectedOrder, setSelectedOrder] = useState<ApportionmentResult | null>(null);

  useEffect(() => {
    setData(null);
    setSelectedOrder(null);
    const controller = new AbortController();
    const qs = yearQuerySuffix ? `?${yearQuerySuffix}` : "";
    apiRequest<ApportionmentResult[]>(`/apportionment${qs}`, token, { signal: controller.signal })
      .then((d) => {
        if (controller.signal.aborted) return;
        d.sort((a, b) => parseInt(b.orderNumber, 10) - parseInt(a.orderNumber, 10));
        setData(d);
      })
      .catch((err) => {
        if (!controller.signal.aborted) {
          setError(err instanceof Error ? err.message : "Erro ao carregar rateios.");
        }
      });
    return () => controller.abort();
  }, [token, yearQuerySuffix]);

  if (error) return <div className="emptyState error">{error}</div>;
  if (!data) return <div className="emptyState">Carregando dados de rateio...</div>;

  return (
    <div style={{ display: "flex", flexDirection: "row", height: "100%", width: "100%", overflow: "hidden" }}>
      <div className="sidebar" style={{ width: "320px", flexShrink: 0, borderRight: "1px solid var(--border-color)", overflowY: "auto", backgroundColor: "var(--card-bg)" }}>
        <h2 style={{ padding: "15px", margin: 0, color: "var(--text-color)" }}>Ordens de Serviço</h2>
        <div style={{ padding: "0 15px 15px 15px", display: "flex", flexDirection: "column", gap: "10px" }}>
          <button
            className="secondaryButton"
            onClick={() => downloadFile(`/apportionment/export/all/excel${yearQuerySuffix ? `?${yearQuerySuffix}` : ""}`, token, `Rateio_Geral_Todas_OS.xlsx`)}
            style={{ width: "100%", justifyContent: "center" }}
          >
            <Download size={16} /> Exportar Todas (Excel)
          </button>
          <button
            className="secondaryButton"
            onClick={() => downloadFile(`/apportionment/export/all/pdf${yearQuerySuffix ? `?${yearQuerySuffix}` : ""}`, token, `Rateio_Geral_Todas_OS.pdf`)}
            style={{ width: "100%", justifyContent: "center" }}
          >
            <Download size={16} /> Exportar Todas (PDF)
          </button>
        </div>
        <div className="list">
          {data.length === 0 ? (
            <span className="muted">Nenhuma OS encontrada.</span>
          ) : (
            data.map(item => (
              <article
                key={item.orderId}
                className={`listItem ${selectedOrder?.orderId === item.orderId ? 'active' : ''}`}
                onClick={() => setSelectedOrder(item)}
                style={{ cursor: "pointer", padding: "15px 10px", borderBottom: "1px solid var(--border-color)", fontSize: "16px", color: "#333" }}
              >
                <strong style={{ color: "inherit" }}>OS {item.orderNumber}</strong>
              </article>
            ))
          )}
        </div>
      </div>

      <div style={{ flex: 1, padding: "20px", overflowY: "auto", backgroundColor: "#fff", color: "#000", display: "block" }}>
        {!selectedOrder ? (
          <div className="emptyState">Selecione uma OS na lista ao lado para ver o rateio.</div>
        ) : (
          <div>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "20px" }}>
              <div>
                <h1 style={{ margin: "0 0 5px 0" }}>OS {selectedOrder.orderNumber}</h1>
                <p className="muted" style={{ margin: 0 }}>
                  Fazendas: {selectedOrder.farms.map((farm) => `${farm.farmCode || "S/C"} - ${farm.farmName}`).join(" | ")} <br />
                  Total de Hectares: {selectedOrder.totalAreaHa.toFixed(2)} | Total Recebido: {selectedOrder.totalWeight.toFixed(2)} t
                </p>
                {selectedOrder.unassignedWeight > 0 ? (
                  <p style={{ margin: "8px 0 0", color: "#b71c1c", fontWeight: 700 }}>
                    Peso sem fazenda identificada: {selectedOrder.unassignedWeight.toFixed(2)} t
                  </p>
                ) : null}
              </div>
              <div style={{ display: "flex", gap: "10px" }}>
                <button
                  className="secondaryButton"
                  onClick={() => downloadFile(`/apportionment/${selectedOrder.orderId}/export/excel`, token, `Rateio_OS_${selectedOrder.orderNumber}.xlsx`)}
                >
                  <Download size={16} /> Excel
                </button>
                <button
                  className="secondaryButton"
                  onClick={() => downloadFile(`/apportionment/${selectedOrder.orderId}/export/pdf`, token, `Rateio_OS_${selectedOrder.orderNumber}.pdf`)}
                >
                  <Download size={16} /> PDF
                </button>
              </div>
            </div>

            <table className="dataTable" style={{ width: "100%", color: "#000" }}>
              <thead>
                <tr>
                  <th>Fazenda</th>
                  <th>Talhão</th>
                  <th style={{ textAlign: "right" }}>Área (ha)</th>
                  <th style={{ textAlign: "right" }}>Participação (%)</th>
                  <th style={{ textAlign: "right" }}>Peso Rateado (t)</th>
                </tr>
              </thead>
              <tbody>
                {selectedOrder.fields.map(f => (
                  <tr key={`${f.farmId}:${f.fieldId}`}>
                    <td>{f.farmCode || "S/C"} - {f.farmName}</td>
                    <td>{f.fieldCode}</td>
                    <td style={{ textAlign: "right" }}>{f.areaHa.toFixed(2)}</td>
                    <td style={{ textAlign: "right" }}>{(f.percentage * 100).toFixed(2)}%</td>
                    <td style={{ textAlign: "right" }}>{f.proratedWeight.toFixed(2)}</td>
                  </tr>
                ))}
              </tbody>
              <tfoot>
                <tr>
                  <th colSpan={2}>TOTAL RATEADO</th>
                  <th style={{ textAlign: "right" }}>{selectedOrder.totalAreaHa.toFixed(2)}</th>
                  <th style={{ textAlign: "right" }}>
                    {selectedOrder.totalWeight > 0 ? ((selectedOrder.allocatedWeight / selectedOrder.totalWeight) * 100).toFixed(2) : "0.00"}%
                  </th>
                  <th style={{ textAlign: "right" }}>{selectedOrder.allocatedWeight.toFixed(2)}</th>
                </tr>
              </tfoot>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
