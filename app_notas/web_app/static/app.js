const tabStorageKey = "notas.activeTab";
const validTabs = new Set(["lancamento", "historico", "relatorios", "cadastros"]);

function initialActiveTab() {
  const stored = window.localStorage.getItem(tabStorageKey);
  return validTabs.has(stored) ? stored : "lancamento";
}

const state = {
  currentHistoryUsePeriod: false,
  lastSubmitPayload: null,
  reportPeriodInitialized: false,
  reportPeriodTouched: false,
  referenceCache: new Map(),
  activeTab: initialActiveTab(),
  loadedTabs: new Set(["lancamento"]),
  dirtyTabs: new Set(),
  historyController: null,
  dashboardController: null,
  correctionPreviewToken: "",
};

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => Array.from(document.querySelectorAll(selector));

function configureLauncherLinks() {
  const host = window.location.hostname || "127.0.0.1";
  const url = `${window.location.protocol}//${host}:8890/`;
  document.querySelectorAll("[data-launcher-link]").forEach((link) => {
    link.href = url;
  });
}

const today = () => new Date().toISOString().slice(0, 10);
const daysAgo = (days) => {
  const date = new Date();
  date.setDate(date.getDate() - days);
  return date.toISOString().slice(0, 10);
};

function toast(message) {
  const node = $("#toast");
  node.textContent = message;
  node.classList.add("show");
  clearTimeout(node._timer);
  node._timer = setTimeout(() => node.classList.remove("show"), 3200);
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    cache: "no-store",
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok || data.ok === false) {
    const error = new Error(data.message || "Falha na operacao.");
    error.status = response.status;
    error.data = data;
    throw error;
  }
  return data;
}

function setBusy(button, busy, text) {
  if (!button) return;
  if (busy) {
    button.dataset.originalText = button.textContent;
    button.disabled = true;
    button.textContent = text || "Aguarde...";
  } else {
    button.disabled = false;
    if (button.dataset.originalText) button.textContent = button.dataset.originalText;
  }
}

function markTabsDirty(...tabs) {
  tabs.forEach((tab) => state.dirtyTabs.add(tab));
}

function isAbortError(error) {
  return error?.name === "AbortError";
}

async function switchTab(name, options = {}) {
  const tabName = validTabs.has(name) ? name : "lancamento";
  $$(".tab-button").forEach((button) => button.classList.toggle("active", button.dataset.tab === tabName));
  $$(".tab-panel").forEach((panel) => panel.classList.toggle("active", panel.id === `tab-${tabName}`));
  state.activeTab = tabName;
  window.localStorage.setItem(tabStorageKey, tabName);

  const shouldLoad = options.force || state.dirtyTabs.has(tabName) || !state.loadedTabs.has(tabName);
  if (!shouldLoad) return;

  try {
    if (tabName === "historico") await loadHistory(state.currentHistoryUsePeriod);
    if (tabName === "relatorios") await loadDashboard();
    if (tabName === "cadastros") await loadCadastros();
  } catch (error) {
    if (!isAbortError(error)) toast(error.message);
  }
}

function fillDatalist(id, items) {
  const list = $(id);
  list.innerHTML = items.map((item) => `<option value="${escapeHtml(item.label)}"></option>`).join("");
}

function referenceListSelector(table) {
  return {
    motoristas: "#motoristasList",
    fazendas: "#fazendasList",
    talhoes: "#talhoesList",
    variedades: "#variedadesList",
  }[table] || "#variedadesList";
}

function currentTalhaoFarm() {
  return $("#fazMuda").value || $("#fazPlantio").value || "";
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function debounce(fn, delay = 220) {
  let timer;
  return (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn(...args), delay);
  };
}

function runIdle(task, delay = 600) {
  if ("requestIdleCallback" in window) {
    window.requestIdleCallback(task, { timeout: 2200 });
  } else {
    window.setTimeout(task, delay);
  }
}

async function loadReferences(table, query = "") {
  const normalizedQuery = String(query || "").trim();
  const farmQuery = table === "talhoes" ? currentTalhaoFarm() : "";
  const cacheKey = `${table}|${farmQuery.toLowerCase()}|${normalizedQuery.toLowerCase()}`;
  if (state.referenceCache.has(cacheKey)) {
    const cached = state.referenceCache.get(cacheKey);
    const target = referenceListSelector(table);
    fillDatalist(target, cached);
    return;
  }
  const params = new URLSearchParams({
    tabela: table,
    q: normalizedQuery,
    limit: "40",
  });
  if (farmQuery) params.set("fazenda", farmQuery);
  const data = await api(`/api/references?${params.toString()}`);
  const target = referenceListSelector(table);
  state.referenceCache.set(cacheKey, data.items);
  fillDatalist(target, data.items);
}

async function loadStatus() {
  const data = await api("/api/status");
  $("#todayBadge").textContent = `Hoje: ${data.metrics.hoje}`;
  $("#totalBadge").textContent = `Total: ${data.metrics.total}`;
  $("#serverBadge").textContent = "Online";
  applyDefaultReportPeriod(data.defaultPeriod);
  if (data.references) {
    renderSyncStatus(data.references);
  } else {
    loadSyncStatus();
  }
  if (data.colaboradores) {
    renderPeopleStatus(data.colaboradores);
  } else {
    loadColaboradoresStatus();
  }
}

async function loadSyncStatus() {
  try {
    const data = await api("/api/sync/status");
    renderSyncStatus(data);
  } catch (error) {
    if (error.data) {
      renderSyncStatus(error.data);
      return;
    }
    renderSyncStatus({
      ok: false,
      message: "Nao foi possivel consultar o status da sincronizacao.",
      issues: [error.message],
    });
  }
}

function renderSyncStatus(data) {
  const badge = $("#syncBadge");
  const sync = data.sync || data || {};
  const source = sync.source ? ` via ${sync.source}` : "";
  const age = typeof sync.ageHours === "number" ? `${sync.ageHours}h` : "-";
  badge.textContent = data.ok ? `Sync: OK${source}` : "Sync: alerta";
  badge.classList.toggle("ok", Boolean(data.ok));
  badge.classList.toggle("alert", !data.ok);
  const issues = Array.isArray(data.issues) ? data.issues : [];
  const commands = data.recommendedCommands || {};
  badge.title = [
    data.message || "",
    `Ultima: ${sync.syncedAt || "-"}`,
    `Idade: ${age}`,
    `Fazendas: ${data.counts?.fazendasBalanca ?? 0}`,
    `Talhoes: ${data.counts?.talhoesBalanca ?? 0}`,
    issues.length ? `Alertas:\n- ${issues.join("\n- ")}` : "",
    commands.dryRun ? `Revisar: ${commands.dryRun}` : "",
    commands.apply ? `Executar: ${commands.apply}` : "",
    data.log?.path ? `Log: ${data.log.path}` : "",
  ].filter(Boolean).join("\n");
}

async function loadColaboradoresStatus() {
  try {
    const data = await api("/api/colaboradores/status");
    renderPeopleStatus(data);
  } catch (error) {
    if (error.data) {
      renderPeopleStatus(error.data);
      return;
    }
    renderPeopleStatus({
      ok: false,
      message: "Nao foi possivel consultar o status do Portal Colaboradores.",
      issues: [error.message],
    });
  }
}

function renderPeopleStatus(data) {
  const badge = $("#peopleBadge");
  if (!badge) return;
  const total = typeof data.totalReferences === "number" ? data.totalReferences : 0;
  badge.textContent = data.ok ? `Colab: OK (${total})` : "Colab: alerta";
  badge.classList.toggle("ok", Boolean(data.ok));
  badge.classList.toggle("alert", !data.ok);
  const issues = Array.isArray(data.issues) ? data.issues : [];
  const actions = Array.isArray(data.recommendedActions) ? data.recommendedActions : [];
  badge.title = [
    data.message || "",
    `Fonte: ${data.source || "portal_colaboradores"}`,
    `Configuracao: ${data.configPath || "-"}`,
    `PostgreSQL: ${data.targetConfigured ? "configurado" : "nao configurado"}`,
    `psql.exe: ${data.psqlFound ? "encontrado" : "nao encontrado"}`,
    `Timeout: ${data.timeoutSeconds || "-"}s`,
    issues.length ? `Alertas:\n- ${issues.join("\n- ")}` : "",
    actions.length ? `Acoes:\n- ${actions.join("\n- ")}` : "",
  ].filter(Boolean).join("\n");
}

function applyDefaultReportPeriod(period) {
  if (!period || state.reportPeriodInitialized || state.reportPeriodTouched) return;
  $("#reportStart").value = period.start || today();
  $("#reportEnd").value = period.end || today();
  state.reportPeriodInitialized = true;
}

function collectNotePayload(extra = {}) {
  return {
    numero: $("#numero").value,
    motorista: $("#motorista").value,
    caminhao: $("#caminhao").value,
    operador: $("#operador").value,
    colhedora: $("#colhedora").value,
    faz_muda: $("#fazMuda").value,
    talhao: $("#talhao").value,
    faz_plantio: $("#fazPlantio").value,
    variedade: $("#variedade").value,
    data_colheita: $("#dataColheita").value,
    data_plantio: $("#dataPlantio").value,
    edit_original: $("#editOriginal").value,
    ...extra,
  };
}

function clearNoteForm(options = {}) {
  const keepLoad = $("#keepLoad").checked;
  const kept = {
    fazMuda: $("#fazMuda").value,
    fazPlantio: $("#fazPlantio").value,
    variedade: $("#variedade").value,
    dataColheita: $("#dataColheita").value,
    dataPlantio: $("#dataPlantio").value,
  };
  $("#noteForm").reset();
  $("#editOriginal").value = "";
  $("#numero").readOnly = false;
  $("#saveButton").textContent = "Lancar nota";
  $("#dataColheita").value = today();
  $("#dataPlantio").value = today();
  if (keepLoad && !options.forceClearLoad) {
    $("#keepLoad").checked = true;
    $("#fazMuda").value = kept.fazMuda;
    $("#fazPlantio").value = kept.fazPlantio;
    $("#variedade").value = kept.variedade;
    $("#dataColheita").value = kept.dataColheita || today();
    $("#dataPlantio").value = kept.dataPlantio || today();
  }
  applyKeepLoad();
  $("#numero").focus();
}

function applyKeepLoad() {
  const locked = $("#keepLoad").checked;
  ["#fazMuda", "#fazPlantio", "#variedade", "#dataColheita", "#dataPlantio"].forEach((selector) => {
    const input = $(selector);
    input.readOnly = locked;
    input.classList.toggle("locked", locked);
  });
  if (locked && ["fazMuda", "fazPlantio", "variedade", "dataColheita", "dataPlantio"].includes(document.activeElement?.id)) {
    $("#talhao").focus();
  }
}

async function submitNote(strategy = "") {
  const button = $("#saveButton");
  setBusy(button, true, "Salvando...");
  try {
    const payload = collectNotePayload(strategy ? { strategy } : {});
    state.lastSubmitPayload = payload;
    const data = await api("/api/notas", { method: "POST", body: JSON.stringify(payload) });
    toast(data.message);
    clearNoteForm();
    markTabsDirty("historico", "relatorios");
    await loadStatus();
    if ($("#tab-historico").classList.contains("active")) await loadHistory(state.currentHistoryUsePeriod);
  } catch (error) {
    if (error.status === 409 && error.data?.code === "DUPLICATE") {
      showDuplicateDialog(error.data);
    } else {
      toast(error.message);
    }
  } finally {
    setBusy(button, false);
  }
}

function showDuplicateDialog(data) {
  const dialog = $("#duplicateDialog");
  $("#duplicateMessage").textContent = `A nota ${data.existente.numero} ja existe. Para preservar o historico, lance uma copia como ${data.numeroDuplicado} ou cancele.`;
  dialog.showModal();
}

async function copyNoteToNewLaunch(numero) {
  const data = await api(`/api/notas/${encodeURIComponent(numero)}`);
  const n = data.nota;
  switchTab("lancamento");
  $("#editOriginal").value = "";
  $("#numero").value = "";
  $("#numero").readOnly = false;
  $("#motorista").value = n.motorista_label || "";
  $("#caminhao").value = n.caminhao || "";
  $("#operador").value = n.operador_label || "";
  $("#colhedora").value = n.colhedora || "";
  $("#fazMuda").value = n.faz_muda_label || "";
  $("#talhao").value = n.talhao || "";
  $("#fazPlantio").value = n.faz_plantio_label || "";
  $("#variedade").value = n.variedade_label || "";
  $("#dataColheita").value = n.data_colheita || today();
  $("#dataPlantio").value = n.data_plantio || today();
  $("#keepLoad").checked = false;
  applyKeepLoad();
  $("#saveButton").textContent = "Lancar nota";
  toast(`Nota ${numero} copiada. Informe o novo numero para lancar.`);
  $("#numero").focus();
}

const auditLabels = {
  motorista: "Motorista",
  operador: "Operador",
  fazendaMuda: "Fazenda muda",
  fazendaPlantio: "Fazenda plantio",
  talhao: "Talhao",
  variedade: "Variedade",
};

function auditItemSummary(item) {
  const parts = [];
  if (item?.codigo) parts.push(`#${item.codigo}`);
  if (item?.nome) parts.push(item.nome);
  if (item?.fazendaNome) parts.push(`Fazenda: ${item.fazendaNome}`);
  if (item?.fazendaCodigo) parts.push(`Cod. fazenda: ${item.fazendaCodigo}`);
  return parts.length ? parts.join(" | ") : "-";
}

function renderReferenceAudit(items) {
  if (!items.length) {
    return `<p class="dialog-empty">Esta nota nao possui rastro de origem das referencias. Isso e esperado para notas antigas lancadas antes da auditoria.</p>`;
  }
  return items.map((entry) => {
    const refs = entry.referencias || {};
    const rows = Object.entries(auditLabels).map(([key, label]) => {
      const item = refs[key] || {};
      return `
        <tr>
          <th>${escapeHtml(label)}</th>
          <td>${escapeHtml(item.fonte || "-")}</td>
          <td>${escapeHtml(auditItemSummary(item))}</td>
        </tr>
      `;
    }).join("");
    return `
      <section class="audit-entry">
        <header>
          <strong>${escapeHtml(entry.evento || "nota.save")}</strong>
          <span>${escapeHtml(entry.registrado_em || "")}</span>
        </header>
        <table class="audit-table">
          <thead>
            <tr><th>Referencia</th><th>Fonte</th><th>Valor usado</th></tr>
          </thead>
          <tbody>${rows}</tbody>
        </table>
      </section>
    `;
  }).join("");
}

async function showReferenceAudit(numero) {
  const dialog = $("#referenceAuditDialog");
  $("#referenceAuditTitle").textContent = `Origem da nota ${numero}`;
  $("#referenceAuditContent").innerHTML = `<p class="dialog-empty">Carregando...</p>`;
  dialog.showModal();
  try {
    const data = await api(`/api/notas/${encodeURIComponent(numero)}/referencias-auditoria`);
    $("#referenceAuditContent").innerHTML = renderReferenceAudit(data.items || []);
  } catch (error) {
    $("#referenceAuditContent").innerHTML = `<p class="dialog-empty">${escapeHtml(error.message)}</p>`;
  }
}

function historyUrl(usePeriod) {
  const params = new URLSearchParams();
  params.set("q", $("#historySearch").value);
  params.set("field", $("#historyField").value);
  params.set("limit", "1000");
  if (usePeriod) {
    params.set("start", $("#historyStart").value);
    params.set("end", $("#historyEnd").value);
  }
  return `/api/historico?${params.toString()}`;
}

async function loadHistory(usePeriod = false) {
  state.currentHistoryUsePeriod = usePeriod;
  state.historyController?.abort();
  const controller = new AbortController();
  state.historyController = controller;
  let data;
  try {
    data = await api(historyUrl(usePeriod), { signal: controller.signal });
  } catch (error) {
    if (isAbortError(error)) return;
    toast(error.message);
    return;
  } finally {
    if (state.historyController === controller) state.historyController = null;
  }
  state.loadedTabs.add("historico");
  state.dirtyTabs.delete("historico");
  $("#historyCount").textContent = `${data.total} registro${data.total === 1 ? "" : "s"}`;
  const rows = data.items.map((row) => `
    <tr>
      <td>${escapeHtml(row.numero)}</td>
      <td>${escapeHtml(row.motorista_nome || "")}</td>
      <td>${escapeHtml(row.caminhao || "")}</td>
      <td>${escapeHtml(row.operador_nome || "")}</td>
      <td>${escapeHtml(row.colhedora || "")}</td>
      <td>${escapeHtml(row.faz_muda_nome || "")}</td>
      <td>${escapeHtml(row.talhao || "")}</td>
      <td>${escapeHtml(row.faz_plantio_nome || "")}</td>
      <td>${escapeHtml(row.variedade_nome || "")}</td>
      <td>${escapeHtml(row.data_colheita || "")}</td>
      <td>
        <div class="row-actions">
          <button class="secondary" data-copy="${escapeHtml(row.numero)}" type="button">Copiar</button>
          <button class="secondary" data-origin="${escapeHtml(row.numero)}" type="button">Origem</button>
        </div>
      </td>
    </tr>
  `).join("");
  $("#historyBody").innerHTML = rows || `<tr><td colspan="11">Nenhuma nota encontrada.</td></tr>`;
}

function rankingCard(title, items) {
  const max = Math.max(...items.map((item) => item.qtd), 1);
  const rows = items.map((item) => `
    <div class="bar-row">
      <strong title="${escapeHtml(item.nome)}">${escapeHtml(item.nome)}</strong>
      <div class="bar"><span style="display:block;width:${Math.max(6, item.qtd / max * 100)}%"></span></div>
      <em>${item.qtd}</em>
    </div>
  `).join("");
  return `<article class="ranking-card"><span>${escapeHtml(title)}</span>${rows || "<p>Sem dados no periodo.</p>"}</article>`;
}

async function loadDashboard() {
  const params = new URLSearchParams({ start: $("#reportStart").value, end: $("#reportEnd").value });
  state.dashboardController?.abort();
  const controller = new AbortController();
  state.dashboardController = controller;
  let data;
  try {
    data = await api(`/api/dashboard?${params.toString()}`, { signal: controller.signal });
  } catch (error) {
    if (isAbortError(error)) return;
    toast(error.message);
    return;
  } finally {
    if (state.dashboardController === controller) state.dashboardController = null;
  }
  state.loadedTabs.add("relatorios");
  state.dirtyTabs.delete("relatorios");
  $("#kpiTotal").textContent = data.metrics.total;
  $("#kpiMedia").textContent = `${data.metrics.media}/dia`;
  $("#kpiDias").textContent = data.metrics.diasAtivos;
  const titles = {
    motoristas: "Top motoristas",
    operadores: "Top operadores",
    colhedoras: "Top colhedoras",
    variedades: "Variedades",
    origens: "Fazendas origem",
    destinos: "Fazendas destino",
  };
  $("#rankingGrid").innerHTML = Object.entries(titles)
    .map(([key, title]) => rankingCard(title, data.rankings[key] || []))
    .join("");
}

function downloadReport(kind, type) {
  const start = $("#reportStart").value;
  const end = $("#reportEnd").value;
  const path = kind === "pdf"
    ? `/api/relatorios/pdf?type=${encodeURIComponent(type)}&start=${start}&end=${end}`
    : `/api/relatorios/export?type=${encodeURIComponent(type)}&start=${start}&end=${end}`;
  window.open(path, "_blank", "noreferrer");
}

async function loadCadastro(table, q = "") {
  const data = await api(`/api/cadastros/${table}?q=${encodeURIComponent(q)}`);
  const box = table === "motoristas" ? $("#motoristasListBox") : table === "fazendas" ? $("#fazendasListBox") : $("#variedadesListBox");
  box.innerHTML = data.items.slice(0, 250).map((item) => `
    <div class="mini-row">
      <span>${escapeHtml(item.label)}</span>
      <button class="danger" data-cad-del="${table}" data-id="${escapeHtml(item.id)}" type="button">Excluir</button>
    </div>
  `).join("") || `<div class="mini-row"><span>Nenhum item encontrado.</span></div>`;
}

async function loadCadastros() {
  await Promise.all([
    loadCadastro("motoristas"),
    loadCadastro("fazendas"),
    loadCadastro("variedades"),
    loadBackups(),
  ]);
  state.loadedTabs.add("cadastros");
  state.dirtyTabs.delete("cadastros");
}

async function createCadastro(table) {
  const payload = {};
  if (table === "motoristas") {
    payload.codigo = $("#motCodigo").value;
    payload.nome = $("#motNome").value;
  } else if (table === "fazendas") {
    payload.codigo = $("#fazCodigo").value;
    payload.nome = $("#fazNome").value;
  } else {
    payload.nome = $("#varNome").value;
  }
  await api(`/api/cadastros/${table}`, { method: "POST", body: JSON.stringify(payload) });
  toast("Cadastro salvo.");
  if (table === "motoristas") {
    $("#motCodigo").value = "";
    $("#motNome").value = "";
  } else if (table === "fazendas") {
    $("#fazCodigo").value = "";
    $("#fazNome").value = "";
  } else {
    $("#varNome").value = "";
  }
  await loadCadastro(table);
  await loadReferences(table);
}

async function deleteCadastro(table, id) {
  if (!confirm("Excluir o cadastro selecionado?")) return;
  await api(
    `/api/cadastros/${table}/${encodeURIComponent(id)}`,
    { method: "DELETE", body: JSON.stringify({ confirmDelete: true }) },
  );
  toast("Cadastro excluido.");
  await loadCadastro(table);
}

async function loadBackups() {
  const data = await api("/api/backups");
  $("#backupSelect").innerHTML = data.items.map((item) => (
    `<option value="${escapeHtml(item.id)}">${escapeHtml(item.origem)} | ${escapeHtml(item.data)} | ${escapeHtml(item.nome)}</option>`
  )).join("");
  $("#backupInfo").textContent = data.items.length ? `${data.items.length} backup(s) disponiveis.` : "Nenhum backup encontrado.";
}

async function createBackup() {
  const button = $("#backupCreate");
  setBusy(button, true, "Criando...");
  try {
    const data = await api("/api/backups/create", { method: "POST", body: "{}" });
    toast(data.message);
    await loadBackups();
  } finally {
    setBusy(button, false);
  }
}

async function restoreBackup() {
  const backupId = $("#backupSelect").value;
  if (!backupId) return toast("Selecione um backup.");
  if (!confirm("Restaurar esse backup? Os dados atuais serao substituidos.")) return;
  const data = await api(
    "/api/backups/restore",
    { method: "POST", body: JSON.stringify({ backupId, confirmRestore: true }) },
  );
  const rollback = data.rollbackBackup?.nome ? ` Rollback: ${data.rollbackBackup.nome}.` : "";
  toast(`${data.message || "Backup restaurado."}${rollback}`);
  await loadStatus();
  await loadHistory(false);
  await loadCadastros();
  await loadBackups();
}

function parseCorrectionNotes() {
  return ($("#correctionNotes").value.match(/\d+/g) || []).map(Number);
}

async function previewCorrection() {
  const payload = {
    numeros: parseCorrectionNotes(),
    acao: $("#correctionAction").value,
    nova_data: $("#correctionDate").value,
    motivo: $("#correctionReason").value,
  };
  const data = await api("/api/correcoes/preview", { method: "POST", body: JSON.stringify(payload) });
  state.correctionPreviewToken = data.previewToken || "";
  const rows = data.preview.map((item) => `
    <div class="mini-row">
      <span>Nota ${item.numero}: ${escapeHtml(item.data_colheita_atual || "-")} -> ${escapeHtml(item.data_colheita_nova || "-")} | ${item.alterado ? "altera" : "sem alteracao"}</span>
    </div>
  `).join("");
  $("#correctionResult").innerHTML = rows || `<div class="mini-row"><span>Nenhuma nota encontrada.</span></div>`;
  if (data.faltantes?.length) toast(`Notas nao encontradas: ${data.faltantes.join(", ")}`);
}

async function applyCorrection() {
  if (!confirm("Aplicar correcao? Um backup sera gerado antes da alteracao.")) return;
  const payload = {
    numeros: parseCorrectionNotes(),
    acao: $("#correctionAction").value,
    nova_data: $("#correctionDate").value,
    motivo: $("#correctionReason").value,
    confirmCorrection: true,
    previewToken: state.correctionPreviewToken,
  };
  const data = await api("/api/correcoes/apply", { method: "POST", body: JSON.stringify(payload) });
  toast(data.message);
  await previewCorrection();
  await loadStatus();
}

function bindEvents() {
  $$(".tab-button").forEach((button) => button.addEventListener("click", () => {
    switchTab(button.dataset.tab).catch((error) => toast(error.message));
  }));
  $("#noteForm").addEventListener("submit", (event) => {
    event.preventDefault();
    submitNote();
  });
  $("#clearButton").addEventListener("click", () => clearNoteForm({ forceClearLoad: true }));
  $("#keepLoad").addEventListener("change", applyKeepLoad);
  $("#duplicateDialog").addEventListener("close", () => {
    const value = $("#duplicateDialog").returnValue;
    if (value === "duplicate") submitNote(value);
  });
  $("#historyFilter").addEventListener("click", () => loadHistory(true));
  $("#historyAll").addEventListener("click", () => loadHistory(false));
  $("#historySearch").addEventListener("input", debounce(() => loadHistory(state.currentHistoryUsePeriod), 300));
  $("#historyField").addEventListener("change", () => loadHistory(state.currentHistoryUsePeriod));
  $("#historyBody").addEventListener("click", (event) => {
    const copy = event.target.closest("[data-copy]");
    const origin = event.target.closest("[data-origin]");
    if (copy) copyNoteToNewLaunch(copy.dataset.copy);
    if (origin) showReferenceAudit(origin.dataset.origin);
  });
  $("#reportRefresh").addEventListener("click", loadDashboard);
  ["#reportStart", "#reportEnd"].forEach((selector) => {
    $(selector).addEventListener("input", () => {
      state.reportPeriodTouched = true;
    });
  });
  $("#exportRaw").addEventListener("click", () => downloadReport("export", "bruto"));
  $("#exportFlow").addEventListener("click", () => downloadReport("export", "fluxo"));
  $$(".pdf-button").forEach((button) => button.addEventListener("click", () => downloadReport("pdf", button.dataset.type)));
  $$("[data-create]").forEach((button) => button.addEventListener("click", () => createCadastro(button.dataset.create)));
  $$(".cadastro-filter").forEach((input) => input.addEventListener("input", debounce(() => loadCadastro(input.dataset.table, input.value), 250)));
  $(".admin-grid").addEventListener("click", (event) => {
    const del = event.target.closest("[data-cad-del]");
    if (del) deleteCadastro(del.dataset.cadDel, del.dataset.id);
  });
  $("#backupCreate").addEventListener("click", createBackup);
  $("#backupRefresh").addEventListener("click", loadBackups);
  $("#backupRestore").addEventListener("click", restoreBackup);
  $("#correctionPreview").addEventListener("click", previewCorrection);
  $("#correctionApply").addEventListener("click", applyCorrection);
  ["#motorista", "#operador"].forEach((selector) => $(selector).addEventListener("input", debounce((e) => loadReferences("motoristas", e.target.value), 180)));
  ["#fazMuda", "#fazPlantio"].forEach((selector) => $(selector).addEventListener("input", debounce((e) => {
    loadReferences("fazendas", e.target.value);
    loadReferences("talhoes", $("#talhao").value).catch(() => {});
  }, 180)));
  $("#talhao").addEventListener("input", debounce((e) => loadReferences("talhoes", e.target.value), 180));
  $("#variedade").addEventListener("input", debounce((e) => loadReferences("variedades", e.target.value), 180));
}

async function init() {
  configureLauncherLinks();
  const t = today();
  $("#dataColheita").value = t;
  $("#dataPlantio").value = t;
  $("#historyEnd").value = t;
  $("#historyStart").value = daysAgo(6);
  $("#reportEnd").value = t;
  $("#reportStart").value = t;
  $("#correctionDate").value = t;
  bindEvents();
  await loadStatus();
  await switchTab(state.activeTab);
  runIdle(() => {
    Promise.allSettled([
      loadReferences("motoristas"),
      loadReferences("fazendas"),
      loadReferences("talhoes"),
      loadReferences("variedades"),
    ]);
  });
}

init().catch((error) => toast(error.message));
setInterval(() => loadStatus().catch(() => {}), 15000);
