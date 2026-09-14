const tabStorageKey = "colaboradores.activeTab";
const validTabs = new Set(["cnh", "consulta", "cadastro", "escala", "relatorios", "auditoria"]);

function initialActiveTab() {
  const stored = window.localStorage.getItem(tabStorageKey);
  return validTabs.has(stored) ? stored : "cnh";
}

const state = {
  opcoes: {},
  selectedCodigo: "",
  colaboradores: [],
  cnhRows: [],
  selectedCnhCodes: new Set(),
  cnhExtraFilter: "",
  dashboard: null,
  loadedTabs: new Set(),
  activeTab: initialActiveTab(),
  consultaVisible: 120,
  consultaTotal: 0,
  cnhVisible: 120,
  cnhTotal: 0,
  pendingRequests: 0,
  consultaSort: { key: null, dir: "asc" },
  controllers: {
    cnh: null,
    colaboradores: null,
  },
};

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => Array.from(document.querySelectorAll(selector));

function debounce(fn, delay = 320) {
  let timer;
  return (...args) => {
    window.clearTimeout(timer);
    timer = window.setTimeout(() => fn(...args), delay);
  };
}

function shouldRunSearch(value) {
  const query = String(value || "").trim();
  return query.length === 0 || query.length >= 2;
}

function isAbortError(error) {
  return error?.name === "AbortError";
}

function configureLauncherLinks() {
  const host = window.location.hostname || "127.0.0.1";
  const url = `${window.location.protocol}//${host}:8890/`;
  document.querySelectorAll("[data-launcher-link]").forEach((link) => {
    link.href = url;
  });
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function text(value, fallback = "-") {
  const clean = String(value ?? "").trim();
  return clean || fallback;
}

function formatDate(value) {
  if (!value) return "-";
  const raw = String(value).slice(0, 10);
  const parts = raw.split("-");
  if (parts.length === 3) return `${parts[2]}/${parts[1]}/${parts[0]}`;
  return raw;
}

function daysUntil(value) {
  if (!value) return null;
  const raw = String(value).slice(0, 10);
  const date = new Date(`${raw}T00:00:00`);
  if (Number.isNaN(date.getTime())) return null;
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  return Math.ceil((date - today) / 86400000);
}

function dateTone(value) {
  const days = daysUntil(value);
  if (days === null) return "neutral";
  if (days < 0) return "danger";
  if (days <= 30) return "warning";
  return "success";
}

function dueText(value) {
  const days = daysUntil(value);
  if (days === null) return "sem validade";
  if (days < 0) {
    const overdue = Math.abs(days);
    return `vencida há ${overdue} ${overdue === 1 ? "dia" : "dias"}`;
  }
  if (days === 0) return "vence hoje";
  return `vence em ${days} ${days === 1 ? "dia" : "dias"}`;
}

function showToast(message) {
  const toast = $("#toast");
  toast.textContent = message;
  toast.classList.add("show");
  clearTimeout(showToast.timer);
  showToast.timer = setTimeout(() => toast.classList.remove("show"), 3000);
}

async function fetchJson(url, options = {}) {
  const { timeoutMs = 18000, ...fetchOptions } = options;
  const timeoutController = new AbortController();
  const timer = window.setTimeout(() => timeoutController.abort(), timeoutMs);
  let signal = fetchOptions.signal || timeoutController.signal;
  if (fetchOptions.signal && "any" in AbortSignal) {
    signal = AbortSignal.any([fetchOptions.signal, timeoutController.signal]);
  }
  state.pendingRequests += 1;
  document.body.classList.add("is-loading");
  try {
    const response = await fetch(url, {
      cache: "no-store",
      ...fetchOptions,
      signal,
      headers: fetchOptions.body instanceof FormData
        ? fetchOptions.headers
        : { "Content-Type": "application/json", ...(fetchOptions.headers || {}) },
    });
    const data = await response.json();
    if (!response.ok || data.ok === false) {
      throw new Error(data.message || "Não foi possível concluir a operação.");
    }
    return data;
  } finally {
    window.clearTimeout(timer);
    state.pendingRequests = Math.max(0, state.pendingRequests - 1);
    if (state.pendingRequests === 0) document.body.classList.remove("is-loading");
  }
}

function fillSelect(selector, values = [], allLabel = "Todos") {
  const select = $(selector);
  if (!select) return;
  const options = [`<option value="">${escapeHtml(allLabel)}</option>`];
  for (const item of values) {
    const value = typeof item === "object" ? item.value : item;
    const label = typeof item === "object" ? item.label : item;
    options.push(`<option value="${escapeHtml(value)}">${escapeHtml(label)}</option>`);
  }
  select.innerHTML = options.join("");
}

function getFormObject(form) {
  const data = {};
  for (const [key, value] of new FormData(form).entries()) {
    if (value instanceof File) continue;
    data[key] = value;
  }
  return data;
}

function setActiveTab(tabName, options = {}) {
  const nextTab = validTabs.has(tabName) ? tabName : "cnh";
  $$(".tab").forEach((button) => button.classList.toggle("active", button.dataset.tab === nextTab));
  $$(".tab-panel").forEach((panel) => panel.classList.toggle("active", panel.id === nextTab));
  state.activeTab = nextTab;
  window.localStorage.setItem(tabStorageKey, nextTab);
  window.scrollTo({ top: 0, behavior: "smooth" });
  return ensureTabData(nextTab, Boolean(options.force));
}

async function ensureTabData(tabName, force = false) {
  if (!force && state.loadedTabs.has(tabName)) return;
  try {
    if (tabName === "dashboard") await loadDashboard();
    if (tabName === "pendencias") await loadPendencias();
    if (tabName === "cnh") await loadCnh();
    if (tabName === "consulta") await loadColaboradores();
    if (tabName === "escala") await loadEscala();
    if (tabName === "auditoria") await loadAuditoria();
    state.loadedTabs.add(tabName);
  } catch (error) {
    if (!isAbortError(error)) showToast(error.message);
  }
}

function badge(label, className = "neutral") {
  return `<span class="badge ${escapeHtml(className)}">${escapeHtml(label)}</span>`;
}

function priorityTone(label) {
  const normalized = String(label || "").toLowerCase();
  if (normalized.includes("alta")) return "danger";
  if (normalized.includes("média") || normalized.includes("media")) return "warning";
  if (normalized.includes("planejamento")) return "caution";
  if (normalized.includes("ok")) return "success";
  return "neutral";
}

function cnhIssueSummary(row) {
  const issues = Array.isArray(row.inconsistencias)
    ? row.inconsistencias
    : String(row.inconsistencias_texto || "").split("|").map((item) => item.trim()).filter(Boolean);
  if (!issues.length) return `<span class="table-subtext">sem inconsistências</span>`;
  return `
    <span class="issue-count">${issues.length}</span>
    <span class="table-subtext">${escapeHtml(issues.slice(0, 2).join(" | "))}${issues.length > 2 ? "..." : ""}</span>
  `;
}

function lastCnhAction(row) {
  const parts = [
    row.ultima_acao_cnh || row.status_acompanhamento_label || row.status_acompanhamento,
    row.ultimo_contato_cnh ? `contato ${formatDate(row.ultimo_contato_cnh)}` : "",
    row.data_prevista_regularizacao_cnh ? `prev. ${formatDate(row.data_prevista_regularizacao_cnh)}` : "",
  ].filter(Boolean);
  if (!parts.length) return `<span class="table-subtext">sem ação</span>`;
  return `
    <strong class="table-name muted">${escapeHtml(parts[0])}</strong>
    <span class="table-subtext">${escapeHtml(parts.slice(1).join(" | ") || row.responsavel_ultimo_contato_cnh || "")}</span>
  `;
}

function turnoHorarioText(row) {
  const turno = String(row?.turno_safra || "").trim();
  const horario = String(row?.horario || "").trim();
  if (turno && horario) return `${turno} - ${horario}`;
  return turno || horario || "sem turno";
}

function escalaTurnoResumo(group) {
  const turnos = group.turnos || {};
  const horarios = group.horariosPorTurno || {};
  return Object.keys(turnos)
    .sort((a, b) => a.localeCompare(b, "pt-BR", { numeric: true }))
    .map((turno) => {
      const horario = horarios[turno] ? ` - ${horarios[turno]}` : "";
      return `${turno}: ${turnos[turno]}${horario}`;
    })
    .join(" | ");
}

function updateCnhBulkBar() {
  const count = state.selectedCnhCodes.size;
  const countEl = $("#cnhSelectedCount");
  if (countEl) countEl.textContent = `${count} selecionado${count === 1 ? "" : "s"}`;
  const applyBtn = $("[data-action='apply-cnh-bulk']");
  if (applyBtn) applyBtn.disabled = count === 0 || !$("#cnhBulkStatus")?.value;
  const visibleCodes = state.cnhRows.slice(0, state.cnhVisible).map((row) => String(row.codigo_colaborador));
  const selectAll = $("#cnhSelectAll");
  if (selectAll) {
    selectAll.checked = visibleCodes.length > 0 && visibleCodes.every((code) => state.selectedCnhCodes.has(code));
    selectAll.indeterminate = visibleCodes.some((code) => state.selectedCnhCodes.has(code)) && !selectAll.checked;
  }
}

function renderCnhDocumentsDue(docs = []) {
  const container = $("#cnhDocumentsDueList");
  if (!container) return;
  if ($("#cnhDocsCount")) $("#cnhDocsCount").textContent = `${docs.length} itens`;
  container.innerHTML = docs.length
    ? docs.slice(0, 5).map((doc) => `
      <button class="queue-mini-card" data-codigo="${escapeHtml(doc.codigo_colaborador || "")}" type="button">
        <strong>${escapeHtml(doc.nome || doc.colaborador_nome || doc.codigo_colaborador || "Documento")}</strong>
        <span>${escapeHtml(doc.nome_documento || "Documento")} - ${formatDate(doc.data_validade)} (${escapeHtml(dueText(doc.data_validade))})</span>
      </button>
    `).join("")
    : `<div class="empty-state compact">Nenhum documento vencendo nos próximos 30 dias.</div>`;
}

function renderCnhOperationalSummary(rows = []) {
  const cnhStats = state.dashboard?.cnh?.contagem_tecnica || {};
  const semValidade = (cnhStats["SEM_VALIDADE"] || 0) + (cnhStats["DATA_INVALIDA"] || 0);

  if ($("#cnhCountVencida")) $("#cnhCountVencida").textContent = cnhStats["VENCIDA"] || 0;
  if ($("#cnhCountSemValidade")) $("#cnhCountSemValidade").textContent = cnhStats["SEM_VALIDADE"] || 0;
  if ($("#cnhCountDataInvalida")) $("#cnhCountDataInvalida").textContent = cnhStats["DATA_INVALIDA"] || 0;
  if ($("#cnhCountCritica")) $("#cnhCountCritica").textContent = cnhStats["CRITICA_7_DIAS"] || 0;
  if ($("#cnhCountAlerta")) $("#cnhCountAlerta").textContent = cnhStats["ALERTA_30_DIAS"] || 0;
  if ($("#cnhCountInconsistencias")) $("#cnhCountInconsistencias").textContent = state.dashboard?.cnh?.inconsistencias || 0;

  const queueRows = rows
    .filter((row) => row.pendencia_operacional || row.prioridade_label !== "OK")
    .slice(0, 6);
  if ($("#cnhActionCount")) $("#cnhActionCount").textContent = `${queueRows.length} itens`;
  const queue = $("#cnhActionQueue");
  if (!queue) return;
  queue.innerHTML = queueRows.length
    ? queueRows.map((row) => `
      <button class="queue-mini-card" data-codigo="${escapeHtml(row.codigo_colaborador)}" type="button">
        <strong>${escapeHtml(row.nome)}</strong>
        <span>${escapeHtml(row.status_tecnico_label || row.status_tecnico)} - ${escapeHtml(row.status_tecnico_descricao || dueText(row.validade_cnh))}</span>
      </button>
    `).join("")
    : `<div class="empty-state compact">Nenhuma ação crítica no filtro atual.</div>`;
}

// ── Cor de avatar baseada no código do colaborador ──────────
function avatarHue(codigo) {
  const num = parseInt(String(codigo).replace(/\D/g, "") || "0", 10);
  const hues = [10, 30, 55, 90, 152, 190, 220, 255, 285, 320];
  return hues[num % hues.length];
}

// ── Atualiza badge de filtros ativos ────────────────────────
function updateConsultaFilterBadge() {
  const filterBtn = $("#consultaFilterBtn");
  const clearBtn = $("#consultaClearBtn");
  if (!filterBtn || !clearBtn) return;
  const active = [
    $("#consultaSearch")?.value.trim(),
    $("#consultaSituacao")?.value,
    $("#consultaFuncao")?.value,
    $("#consultaCidade")?.value,
    $("#consultaTurno")?.value,
    $("#consultaCnhVencida")?.checked ? "1" : "",
  ].filter(Boolean).length;
  if (active > 0) {
    filterBtn.classList.add("filters-active");
    filterBtn.dataset.count = active;
    clearBtn.style.display = "";
  } else {
    filterBtn.classList.remove("filters-active");
    delete filterBtn.dataset.count;
    clearBtn.style.display = "none";
  }
}

async function loadStatus() {
  await fetchJson("/api/status");
  $("#serverStatus").textContent = "Online";
  $("#dbInfo").textContent = "Banco conectado";
  $("#reportDbPath").textContent = "Base local protegida e sincronizada com o gestor.";
}

async function loadOpcoes() {
  const data = await fetchJson("/api/opcoes");
  state.opcoes = data.data || {};
  fillSelect("#cnhStatusTecnico", state.opcoes.statusTecnico, "Todos");
  fillSelect("#cnhStatusAcomp", state.opcoes.statusAcompanhamento, "Todos");
  fillSelect("#cnhBulkStatus", state.opcoes.statusAcompanhamento, "Status");
  fillSelect("#cnhFrente", state.opcoes.frentes, "Todas");
  fillSelect("#cnhGestor", state.opcoes.gestores, "Todos");
  fillSelect("#consultaSituacao", state.opcoes.situacoes, "Todas");
  fillSelect("#consultaFuncao", state.opcoes.funcoes, "Todas");
  fillSelect("#consultaCidade", state.opcoes.cidades, "Todas");
  fillSelect("#consultaTurno", state.opcoes.turnos, "Todos");
  // Selects do cadastro (sem opção "Todos" -- blank)
  fillSelect("#cadastroSituacao", state.opcoes.situacoes, "");
  fillSelect("#cadastroFrente", state.opcoes.frentes, "");
  fillSelect("#cadastroTurno", state.opcoes.turnos, "");
  fillSelect("#cadastroFuncaoSafra", state.opcoes.funcoes, "");
}

async function loadDashboard() {
  const data = await fetchJson("/api/dashboard");
  const dashboard = data.data || {};
  state.dashboard = dashboard;
  const colab = dashboard.colaboradores || {};
  const cnh = dashboard.cnh || {};
  const docs = dashboard.documentosAVencer || [];
  const criticos = cnh.criticos || [];
  const totalColaboradores = colab.total ?? cnh.total ?? 0;
  const ativos = colab.ATIVO ?? colab.Ativo ?? 0;
  const pendenciasCnh = cnh.pendentes ?? 0;
  const inconsistencias = cnh.inconsistencias ?? 0;
  const cards = [
    {
      label: "Colaboradores",
      value: totalColaboradores,
      hint: `${ativos} ativos na base`,
      tone: "neutral",
    },
    {
      label: "Ativos",
      value: ativos,
      hint: totalColaboradores ? `${Math.round((ativos / totalColaboradores) * 100)}% do total` : "Sem base carregada",
      tone: "success",
    },
    {
      label: "Pendências CNH",
      value: pendenciasCnh,
      hint: criticos.length ? `${criticos.length} críticas` : "Sem alerta crítico",
      tone: pendenciasCnh ? "warning" : "success",
    },
    {
      label: "Inconsistências",
      value: inconsistencias,
      hint: inconsistencias ? "Revisar cadastros" : "Dados consistentes",
      tone: inconsistencias ? "danger" : "success",
    },
  ];

  const summaryTitle = criticos.length || docs.length
    ? "Atenção para pendências operacionais"
    : "Rotina de RH sem alertas críticos";
  const summaryText = criticos.length || docs.length
    ? `${criticos.length} CNH(s) crítica(s) e ${docs.length} documento(s) com vencimento próximo. Priorize os itens de maior risco.`
    : "Não há CNHs críticas ou documentos vencendo nos próximos 30 dias.";

  const summaryTitleEl = $("#dashboardSummaryTitle");
  const summaryTextEl = $("#dashboardSummaryText");
  if (summaryTitleEl) summaryTitleEl.textContent = summaryTitle;
  if (summaryTextEl) summaryTextEl.textContent = summaryText;
  if ($("#dashboardActiveCount")) $("#dashboardActiveCount").textContent = ativos;
  if ($("#dashboardCnhCount")) $("#dashboardCnhCount").textContent = pendenciasCnh;
  if ($("#dashboardDocsCount")) $("#dashboardDocsCount").textContent = docs.length;
  if ($("#priorityCnhCount")) $("#priorityCnhCount").textContent = pendenciasCnh;
  if ($("#priorityDocsCount")) $("#priorityDocsCount").textContent = docs.length;
  if ($("#priorityCadastroCount")) $("#priorityCadastroCount").textContent = inconsistencias;
  if ($("#priorityCnhText")) $("#priorityCnhText").textContent = pendenciasCnh ? "pendências para acompanhar" : "sem cobrança crítica";
  if ($("#priorityDocsText")) $("#priorityDocsText").textContent = docs.length ? "vencimentos próximos" : "sem vencimentos próximos";
  if ($("#priorityCadastroText")) $("#priorityCadastroText").textContent = inconsistencias ? "itens para revisar" : "cadastros consistentes";

  $("#dashboardCards").innerHTML = cards.map(({ label, value, hint, tone }) => `
    <article class="kpi-card tone-${escapeHtml(tone)}">
      <span>${escapeHtml(label)}</span>
      <strong>${escapeHtml(value)}</strong>
      <small>${escapeHtml(hint)}</small>
    </article>
  `).join("");

  $("#criticalCount").textContent = `${criticos.length} itens`;
  $("#criticalCnhBody").innerHTML = criticos.length
    ? criticos.map((row) => `
        <tr class="table-row-alert" data-codigo="${escapeHtml(row.codigo_colaborador)}">
          <td><span class="code-cell">${escapeHtml(row.codigo_colaborador)}</span></td>
          <td>
            <strong class="table-name">${escapeHtml(row.nome)}</strong>
            <span class="table-subtext">${escapeHtml(row.frente_exibicao || row.frente_safra || "Sem frente")}</span>
          </td>
          <td>
            <span class="date-pill ${escapeHtml(dateTone(row.validade_cnh))}">${escapeHtml(row.validade_cnh_formatada || formatDate(row.validade_cnh))}</span>
            <span class="table-subtext">${escapeHtml(dueText(row.validade_cnh))}</span>
          </td>
          <td>${badge(row.status_tecnico_label || row.status_tecnico, row.status_tecnico)}</td>
        </tr>
      `).join("")
    : `<tr class="empty-row"><td colspan="4">Nenhuma pendência crítica no momento.</td></tr>`;

  $("#documentsDueList").innerHTML = docs.length
    ? docs.slice(0, 8).map((doc) => `
        <div class="list-item list-item-accent">
          <div>
            <strong>${escapeHtml(doc.nome_colaborador)}</strong>
            <span>${escapeHtml(doc.nome_documento)} - ${formatDate(doc.data_validade)} (${escapeHtml(dueText(doc.data_validade))})</span>
          </div>
          ${badge(doc.codigo_colaborador, "neutral")}
        </div>
      `).join("")
    : `<div class="empty-state">Nenhum documento vencendo nos próximos 30 dias.</div>`;
  renderCnhDocumentsDue(docs);
  renderCnhOperationalSummary(state.cnhRows || []);
}

function isBlank(value) {
  return !String(value ?? "").trim();
}

function cadastroIssues(row) {
  const issues = [];
  if (isBlank(row.cpf)) issues.push("CPF");
  if (isBlank(row.funcao_safra || row.funcao)) issues.push("função");
  if (isBlank(row.frente_safra)) issues.push("frente");
  if (isBlank(row.validade_cnh)) issues.push("CNH");
  if (isBlank(row.situacao)) issues.push("situação");
  return issues;
}

function pendingItem(row, detail, tone = "neutral") {
  return `
    <button class="list-item pending-item" data-codigo="${escapeHtml(row.codigo_colaborador)}" type="button">
      <div>
        <strong>${escapeHtml(row.nome || row.nome_colaborador || row.codigo_colaborador)}</strong>
        <span>${escapeHtml(detail)}</span>
      </div>
      ${badge(row.codigo_colaborador || "ver", tone)}
    </button>
  `;
}

function renderPendenciasFromState() {
  const dashboard = state.dashboard || {};
  const docs = dashboard.documentosAVencer || [];
  const cnhRows = state.cnhRows.filter((row) => {
    const tecnico = String(row.status_tecnico || "").toUpperCase();
    const acomp = String(row.status_acompanhamento || "").toUpperCase();
    return tecnico !== "OK" || acomp !== "RESOLVIDO";
  });
  const cadastros = state.colaboradores
    .map((row) => ({ row, issues: cadastroIssues(row) }))
    .filter((item) => item.issues.length);

  $("#pendingCards").innerHTML = [
    ["CNH para acompanhar", cnhRows.length],
    ["Documentos vencendo", docs.length],
    ["Cadastros a revisar", cadastros.length],
    ["Colaboradores ativos", (dashboard.colaboradores || {}).ATIVO ?? (dashboard.colaboradores || {}).Ativo ?? 0],
  ].map(([label, value]) => `
    <article class="kpi-card">
      <span>${escapeHtml(label)}</span>
      <strong>${escapeHtml(value)}</strong>
    </article>
  `).join("");

  $("#pendingCnhCount").textContent = `${cnhRows.length} itens`;
  $("#pendingCnhList").innerHTML = cnhRows.length
    ? cnhRows.slice(0, 12).map((row) => pendingItem(row, `${text(row.status_tecnico_label || row.status_tecnico)} - ${formatDate(row.validade_cnh)}`, row.status_tecnico || "warning")).join("")
    : `<div class="empty-state">Nenhuma pendência de CNH no filtro atual.</div>`;

  $("#pendingDocsCount").textContent = `${docs.length} itens`;
  $("#pendingDocsList").innerHTML = docs.length
    ? docs.slice(0, 12).map((doc) => pendingItem(doc, `${text(doc.nome_documento)} - ${formatDate(doc.data_validade)}`, "warning")).join("")
    : `<div class="empty-state">Nenhum documento vencendo nos próximos 30 dias.</div>`;

  $("#pendingCadastroCount").textContent = `${cadastros.length} itens`;
  $("#pendingCadastroList").innerHTML = cadastros.length
    ? cadastros.slice(0, 12).map(({ row, issues }) => pendingItem(row, `Revisar: ${issues.slice(0, 3).join(", ")}`, "neutral")).join("")
    : `<div class="empty-state">Cadastros principais sem pendências visíveis.</div>`;
}

async function loadPendencias() {
  if (!state.dashboard) await loadDashboard();
  const [cnhData, colabData] = await Promise.all([
    fetchJson("/api/cnh?pendentes=1&limit=1000"),
    fetchJson("/api/colaboradores?limit=1000"),
  ]);
  state.cnhRows = cnhData.data || [];
  state.cnhTotal = cnhData.total || state.cnhRows.length;
  state.colaboradores = colabData.data || [];
  state.consultaTotal = colabData.total || state.colaboradores.length;
  renderPendenciasFromState();
}

async function loadCnh(append = false) {
  state.controllers.cnh?.abort();
  const controller = new AbortController();
  state.controllers.cnh = controller;

  if (!append) {
    state.cnhPage = 1;
    state.cnhRows = [];
  }

  const limit = 120;
  const offset = (state.cnhPage - 1) * limit;

  const params = new URLSearchParams({
    q: $("#cnhSearch").value,
    status_tecnico: $("#cnhStatusTecnico").value,
    status_acompanhamento: $("#cnhStatusAcomp").value,
    frente: $("#cnhFrente").value,
    gestor: $("#cnhGestor").value,
    pendentes: $("#cnhPendentes").checked ? "1" : "",
    com_inconsistencias: state.cnhExtraFilter === "inconsistencias" ? "1" : "",
    limit: limit.toString(),
    offset: offset.toString()
  });
  let data;
  try {
    data = await fetchJson(`/api/cnh?${params}`, { signal: controller.signal, timeoutMs: 20000 });
  } catch (error) {
    if (isAbortError(error)) return;
    throw error;
  } finally {
    if (state.controllers.cnh === controller) state.controllers.cnh = null;
  }

  if (append) {
    state.cnhRows = state.cnhRows.concat(data.data || []);
  } else {
    state.cnhRows = data.data || [];
    state.selectedCnhCodes.clear();
  }

  state.cnhTotal = data.total || state.cnhRows.length;
  renderCnhRows();
}

function renderCnhRows() {
  const visibleRows = state.cnhRows;
  renderCnhOperationalSummary(state.cnhRows);
  $("#cnhTotal").textContent = `${visibleRows.length} de ${state.cnhTotal} registros`;
  $("#cnhTableBody").innerHTML = visibleRows.length
    ? visibleRows.map((row) => `
        <tr data-codigo="${escapeHtml(row.codigo_colaborador)}" class="${state.selectedCnhCodes.has(String(row.codigo_colaborador)) ? "bulk-selected" : ""}">
          <td class="select-col">
            <input class="cnh-row-check" type="checkbox" data-codigo="${escapeHtml(row.codigo_colaborador)}" ${state.selectedCnhCodes.has(String(row.codigo_colaborador)) ? "checked" : ""} />
          </td>
          <td>${badge(row.prioridade_label || "-", priorityTone(row.prioridade_label))}</td>
          <td><span class="code-cell">${escapeHtml(row.codigo_colaborador)}</span></td>
          <td>
            <strong class="table-name">${escapeHtml(row.nome)}</strong>
            <span class="table-subtext">${escapeHtml(row.funcao_exibicao || row.funcao_safra || row.funcao || "sem função")}</span>
          </td>
          <td>
            <strong class="table-name muted">${escapeHtml(row.frente_exibicao || row.frente_safra || "-")}</strong>
            <span class="table-subtext">${escapeHtml(turnoHorarioText(row))}</span>
            <span class="table-subtext">${escapeHtml(row.gestor_responsavel || "sem gestor")}</span>
          </td>
          <td>
            <span class="date-pill ${escapeHtml(dateTone(row.validade_cnh))}">${escapeHtml(row.validade_cnh_formatada || formatDate(row.validade_cnh))}</span>
            <span class="table-subtext">${escapeHtml(dueText(row.validade_cnh))}</span>
          </td>
          <td>${escapeHtml(row.categoria_cnh || "-")}</td>
          <td>${badge(row.status_tecnico_label || row.status_tecnico, row.status_tecnico)}</td>
          <td>${badge(row.status_acompanhamento_label || row.status_acompanhamento, row.status_acompanhamento)}</td>
          <td>${lastCnhAction(row)}</td>
          <td class="issues-cell">${cnhIssueSummary(row)}</td>
        </tr>
      `).join("")
    : `<tr class="empty-row"><td colspan="11">Nenhum registro encontrado.</td></tr>`;
  const moreButton = $("[data-action='load-more-cnh']");
  if (moreButton) moreButton.hidden = state.cnhRows.length >= state.cnhTotal;
  updateCnhBulkBar();
}

async function loadColaboradores() {
  state.controllers.colaboradores?.abort();
  const controller = new AbortController();
  state.controllers.colaboradores = controller;
  const params = new URLSearchParams({
    q: $("#consultaSearch").value,
    situacao: $("#consultaSituacao").value,
    funcao: $("#consultaFuncao").value,
    cidade: $("#consultaCidade").value,
    turno: $("#consultaTurno").value,
    cnh_vencida: $("#consultaCnhVencida").checked ? "1" : "",
    limit: "1000",
  });
  let data;
  try {
    data = await fetchJson(`/api/colaboradores?${params}`, { signal: controller.signal, timeoutMs: 20000 });
  } catch (error) {
    if (isAbortError(error)) return;
    throw error;
  } finally {
    if (state.controllers.colaboradores === controller) state.controllers.colaboradores = null;
  }
  state.colaboradores = data.data || [];
  state.consultaTotal = data.total || state.colaboradores.length;
  state.consultaVisible = 120;
  renderColaboradorRows();
}

// ── Realce de texto buscado ──────────────────────────────────
function highlightText(text, query) {
  if (!query || query.length < 2) return escapeHtml(text);
  const safe = escapeHtml(text);
  const safeQuery = escapeHtml(query).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  return safe.replace(new RegExp(`(${safeQuery})`, "gi"), '<mark class="hl">$1</mark>');
}

function renderColaboradorRows() {
  let rows = [...state.colaboradores];
  const query = $("#consultaSearch")?.value.trim() || "";

  // ── Ordenação local ───────────────────────────────────────
  const { key, dir } = state.consultaSort;
  if (key) {
    rows.sort((a, b) => {
      let va = a[key] ?? "";
      let vb = b[key] ?? "";
      if (typeof va === "string") va = va.toLowerCase();
      if (typeof vb === "string") vb = vb.toLowerCase();
      if (va < vb) return dir === "asc" ? -1 : 1;
      if (va > vb) return dir === "asc" ? 1 : -1;
      return 0;
    });
  }

  const visibleRows = rows.slice(0, state.consultaVisible);
  $("#consultaTotal").textContent = `${visibleRows.length} de ${state.consultaTotal || state.colaboradores.length} registros`;
  $("#consultaTableBody").innerHTML = visibleRows.length
    ? visibleRows.map((row) => `
        <tr data-codigo="${escapeHtml(row.codigo_colaborador)}">
          <td><span class="code-cell">${highlightText(row.codigo_colaborador, query)}</span></td>
          <td>
            <strong class="table-name">${highlightText(row.nome, query)}</strong>
            <span class="table-subtext">${escapeHtml(row.telefone || row.apelido || "sem telefone")}</span>
          </td>
          <td>${badge(row.situacao || "-", row.situacao || "neutral")}</td>
          <td>
            <strong class="table-name muted">${highlightText(row.funcao_safra || row.funcao || "-", query)}</strong>
            <span class="table-subtext">${escapeHtml(turnoHorarioText(row))}</span>
          </td>
          <td>${highlightText(row.frente_safra || "-", query)}</td>
          <td>${escapeHtml(row.cidade || row.municipio || "-")}</td>
          <td><span class="date-pill ${escapeHtml(dateTone(row.validade_cnh))}">${escapeHtml(formatDate(row.validade_cnh))}</span></td>
        </tr>
      `).join("")
    : `<tr class="empty-row"><td colspan="7">Nenhum colaborador encontrado.</td></tr>`;

  const moreButton = $("[data-action='load-more-colaboradores']");
  if (moreButton) moreButton.hidden = state.consultaVisible >= state.colaboradores.length;

  // Restaura seleção visual
  if (state.selectedCodigo) markSelectedRows(state.selectedCodigo);

  // Atualiza visual dos cabeçalhos ordenáveis
  $$("th.sortable").forEach((th) => {
    th.classList.remove("sort-asc", "sort-desc");
    if (th.dataset.sort === key) th.classList.add(dir === "asc" ? "sort-asc" : "sort-desc");
  });
}

// ── Exportar CSV da lista filtrada ────────────────────────────
function exportConsultaCsv() {
  let rows = [...state.colaboradores];
  const { key, dir } = state.consultaSort;
  if (key) {
    rows.sort((a, b) => {
      let va = (a[key] ?? "").toString().toLowerCase();
      let vb = (b[key] ?? "").toString().toLowerCase();
      if (va < vb) return dir === "asc" ? -1 : 1;
      if (va > vb) return dir === "asc" ? 1 : -1;
      return 0;
    });
  }
  const cols = [
    { label: "Código",   key: "codigo_colaborador" },
    { label: "Nome",     key: "nome" },
    { label: "Situação", key: "situacao" },
    { label: "Função",   key: "funcao_safra" },
    { label: "Frente",   key: "frente_safra" },
    { label: "Turno",    key: "turno_safra" },
    { label: "Cidade",   key: "cidade" },
    { label: "Telefone", key: "telefone" },
    { label: "CNH Validade", key: "validade_cnh" },
  ];
  const escape = (v) => {
    const raw = String(v ?? "");
    const safe = /^[=+\-@]/.test(raw) ? `'${raw}` : raw;
    return `"${safe.replace(/"/g, '""')}"`;
  };
  const header = cols.map((c) => escape(c.label)).join(",");
  const body = rows.map((r) => cols.map((c) => escape(r[c.key] ?? "")).join(",")).join("\n");
  const blob = new Blob(["\uFEFF" + header + "\n" + body], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  const now = new Date().toISOString().slice(0, 10);
  a.href = url;
  a.download = `colaboradores_${now}.csv`;
  document.body.appendChild(a);
  a.click();
  setTimeout(() => { URL.revokeObjectURL(url); a.remove(); }, 1000);
  showToast(`${rows.length} registros exportados.`);
}

// ── Navegação Próximo / Anterior ──────────────────────────────
function consultaNavigate(direction) {
  if (!state.colaboradores.length) return;
  const currentIdx = state.colaboradores.findIndex(
    (c) => String(c.codigo_colaborador) === String(state.selectedCodigo)
  );
  let nextIdx;
  if (currentIdx === -1) {
    nextIdx = direction === "next" ? 0 : state.colaboradores.length - 1;
  } else {
    nextIdx = direction === "next" ? currentIdx + 1 : currentIdx - 1;
  }
  if (nextIdx < 0 || nextIdx >= state.colaboradores.length) return;
  // Expande a lista se necessário
  if (nextIdx >= state.consultaVisible) {
    state.consultaVisible = nextIdx + 1;
    renderColaboradorRows();
  }
  const nextCodigo = state.colaboradores[nextIdx].codigo_colaborador;
  loadColaboradorDetail(nextCodigo, "consulta").catch((e) => showToast(e.message));
  // Scroll da linha para dentro da viewport da tabela
  setTimeout(() => {
    const tr = $(`tr[data-codigo="${nextCodigo}"]`);
    if (tr) tr.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, 80);
}

function updateCadastroIdentity(colaborador = {}) {
  const nome = colaborador.nome || "";
  const codigo = colaborador.codigo_colaborador || "";
  const situacao = colaborador.situacao || "";
  const hue = codigo ? avatarHue(codigo) : 152;
  const avatarEl = $("#cadastroAvatar");
  const nomeEl = $("#cadastroNomeDisplay");
  const subEl = $("#cadastroSubDisplay");
  const deleteBtn = $("#cadastroDeleteBtn");
  if (avatarEl) {
    avatarEl.textContent = nome ? nome.slice(0, 1).toUpperCase() : "?";
    avatarEl.style.setProperty("--av-h", hue);
    avatarEl.dataset.hue = "1";
  }
  if (nomeEl) nomeEl.textContent = nome || "Novo colaborador";
  if (subEl) {
    subEl.textContent = codigo
      ? `Código ${codigo}${situacao ? " • " + situacao : ""}`
      : "Preencha o formulário para cadastrar um novo colaborador";
  }
  // Excluir fica desabilitado quando não há colaborador carregado
  if (deleteBtn) deleteBtn.disabled = !codigo;
}

function setCadastroUnsaved(dirty) {
  const badge = $("#cadastroUnsavedBadge");
  if (badge) badge.style.display = dirty ? "" : "none";
  state.cadastroDirty = dirty;
}

function fillColaboradorForm(colaborador = {}) {
  const form = $("#colaboradorForm");
  form.reset();
  for (const [key, value] of Object.entries(colaborador)) {
    const field = form.elements[key];
    if (!field) continue;
    field.value = value ?? "";
  }
  form.elements.original_codigo.value = colaborador.codigo_colaborador || "";
  state.selectedCodigo = colaborador.codigo_colaborador || "";
  syncAttachmentCodes();
  updateCadastroIdentity(colaborador);
  setCadastroUnsaved(false);
}

function syncAttachmentCodes() {
  for (const selector of ["#documentForm", "#atestadoForm", "#advertenciaForm"]) {
    const form = $(selector);
    if (form?.elements.codigo_colaborador) {
      form.elements.codigo_colaborador.value = state.selectedCodigo || "";
    }
  }
}

function renderAttachments(bundle) {
  const docs = bundle.documentos || [];
  const atestados = bundle.atestados || [];
  const advertencias = bundle.advertencias || [];
  $("#documentList").innerHTML = docs.length ? docs.map((item) => attachmentItem(item, "documento")).join("") : emptySmall("Sem documentos.");
  $("#atestadoList").innerHTML = atestados.length ? atestados.map((item) => attachmentItem(item, "atestado")).join("") : emptySmall("Sem atestados.");
  $("#advertenciaList").innerHTML = advertencias.length ? advertencias.map((item) => attachmentItem(item, "advertencia")).join("") : emptySmall("Sem advertências.");
}

function emptySmall(message) {
  return `<div class="list-item"><span>${escapeHtml(message)}</span></div>`;
}

function attachmentItem(item, type) {
  const id = item.id;
  const hasFile = item.caminho_arquivo_db || item.caminho_arquivo || item.caminho_atestado_pdf || item.caminho_advertencia_pdf;
  const name = item.nome_documento || item.tipo_infracao || item.motivo || "Arquivo";
  const date = item.data_validade || item.data_inicio || item.data_infracao || "";
  const openLink = hasFile
    ? `<a class="secondary-button" href="/api/arquivo?type=${encodeURIComponent(type)}&id=${encodeURIComponent(id)}">Abrir</a>`
    : "";
  return `
    <div class="list-item">
      <div>
        <strong>${escapeHtml(name)}</strong>
        <span>${escapeHtml(formatDate(date))}</span>
      </div>
      <div class="actions-row">
        ${openLink}
        <button class="danger-button" data-action="delete-${type}" data-id="${escapeHtml(id)}" type="button">Excluir</button>
      </div>
    </div>
  `;
}

async function loadColaboradorDetail(codigo, target = "cadastro") {
  if (!codigo) return;
  const data = await fetchJson(`/api/colaboradores/${encodeURIComponent(codigo)}`);
  const bundle = data.data || {};
  fillColaboradorForm(bundle.colaborador || {});
  renderAttachments(bundle);
  renderCnhDetail(bundle);
  renderConsultaDetail(bundle);
  markSelectedRows(codigo);
  if (target === "cadastro") setActiveTab("cadastro");
  if (target === "cnh") setActiveTab("cnh");
}

function markSelectedRows(codigo) {
  $$("tr[data-codigo], .pending-item[data-codigo], .queue-mini-card[data-codigo]").forEach((item) => {
    item.classList.toggle("selected", item.dataset.codigo === String(codigo));
  });
}

function cnhDetailAlert(colab) {
  const tone = dateTone(colab.validade_cnh);
  if (tone === "danger") {
    return `<div class="cnh-alert-banner danger"><strong>CNH vencida</strong><span>${escapeHtml(dueText(colab.validade_cnh))}</span></div>`;
  }
  if (tone === "warning") {
    return `<div class="cnh-alert-banner warning"><strong>CNH em atenção</strong><span>${escapeHtml(dueText(colab.validade_cnh))}</span></div>`;
  }
  if (!colab.validade_cnh) {
    return `<div class="cnh-alert-banner neutral"><strong>CNH sem validade</strong><span>Data não informada no cadastro.</span></div>`;
  }
  return `<div class="cnh-alert-banner success"><strong>CNH regular</strong><span>${escapeHtml(dueText(colab.validade_cnh))}</span></div>`;
}

function renderCnhIssueList(colab) {
  const issues = Array.isArray(colab.inconsistencias)
    ? colab.inconsistencias
    : String(colab.inconsistencias_texto || "").split("|").map((item) => item.trim()).filter(Boolean);
  if (!issues.length) return `<div class="empty-state compact">Sem inconsistências registradas para este colaborador.</div>`;
  return issues.map((issue) => `<div class="issue-line">${escapeHtml(issue)}</div>`).join("");
}

function renderCnhDetail(bundle) {
  const baseColab = bundle.colaborador || {};
  const cnhRow = state.cnhRows.find((row) => String(row.codigo_colaborador) === String(baseColab.codigo_colaborador)) || {};
  const colab = { ...cnhRow, ...baseColab };
  const historico = bundle.historicoCnh || [];
  const acompanhamentos = bundle.acompanhamentosCnh || [];
  if (!colab.codigo_colaborador) {
    $("#cnhDetail").innerHTML = `<div class="empty-state">Selecione um colaborador para acompanhar a CNH.</div>`;
    return;
  }
  const acompanhamentoStatus = colab.status_cnh_acompanhamento || colab.status_acompanhamento || "";
  const cnhStatus = colab.status_cnh_acompanhamento_label || colab.status_acompanhamento_label || acompanhamentoStatus || "Sem acompanhamento";
  $("#cnhDetail").innerHTML = `
    <div class="detail-card-head cnh-detail-head">
      <span class="detail-avatar">${escapeHtml(String(colab.nome || colab.codigo_colaborador).slice(0, 1).toUpperCase())}</span>
      <div class="detail-title">
        <strong>${escapeHtml(colab.nome)}</strong>
        <span class="mini-text">Código ${escapeHtml(colab.codigo_colaborador)} - ${escapeHtml(colab.frente_safra || "Sem frente")}</span>
      </div>
    </div>
    ${cnhDetailAlert(colab)}
    <div class="detail-metrics cnh-context-grid">
      <div class="metric-pill">
        <span>Validade</span>
        <strong>${formatDate(colab.validade_cnh)}</strong>
        <small class="${escapeHtml(dateTone(colab.validade_cnh))}">${escapeHtml(dueText(colab.validade_cnh))}</small>
      </div>
      <div class="metric-pill">
        <span>Categoria</span>
        <strong>${text(colab.categoria_cnh)}</strong>
        <small>${escapeHtml(cnhStatus)}</small>
      </div>
      <div class="metric-pill">
        <span>Gestor</span>
        <strong>${text(colab.gestor_responsavel)}</strong>
        <small>${escapeHtml(colab.local_trabalho || colab.frente_safra || "sem local")}</small>
      </div>
      <div class="metric-pill">
        <span>Turno</span>
        <strong>${escapeHtml(turnoHorarioText(colab))}</strong>
        <small>${escapeHtml(colab.funcao_safra || colab.funcao || "sem função")}</small>
      </div>
    </div>
    <section class="detail-section">
      <h3>Inconsistências</h3>
      <div class="issue-list">${renderCnhIssueList(colab)}</div>
    </section>
    <section class="detail-section">
      <h3>Ações rápidas</h3>
      <div class="quick-action-grid">
        <button class="secondary-button" data-action="cnh-quick-status" data-status="SEM_RETORNO" type="button">Sem retorno</button>
        <button class="secondary-button" data-action="cnh-quick-status" data-status="AGENDADO" type="button">Agendado</button>
        <button class="secondary-button" data-action="cnh-quick-status" data-status="EM_ANDAMENTO" type="button">Em andamento</button>
        <button class="secondary-button" data-action="cnh-quick-status" data-status="AGUARDANDO_DOCUMENTO" type="button">Aguardando documento</button>
        <button class="primary-button" data-action="cnh-quick-status" data-status="REGULARIZADO" type="button">Regularizado</button>
      </div>
    </section>
    <section class="detail-section">
      <h3>Registrar acompanhamento</h3>
      <form id="cnhFollowForm" class="stack-form">
        <input type="hidden" name="codigo_colaborador" value="${escapeHtml(colab.codigo_colaborador)}" />
        <label>Status<select name="status">${(state.opcoes.statusAcompanhamento || []).map((item) => `<option value="${escapeHtml(item.value)}" ${item.value === acompanhamentoStatus ? "selected" : ""}>${escapeHtml(item.label)}</option>`).join("")}</select></label>
        <label>Responsável<input name="responsavel" /></label>
        <label>Data prevista<input name="data_prevista" type="date" /></label>
        <label class="check-line"><input name="houve_contato" type="checkbox" value="1" /> Houve contato</label>
        <label>Observação<textarea name="observacao"></textarea></label>
        <label>Comprovante<input name="arquivo" type="file" /></label>
        <button class="primary-button full" type="submit">Salvar acompanhamento</button>
      </form>
    </section>
    <section class="detail-section">
      <h3>Registrar renovação</h3>
      <form id="cnhRenewForm" class="stack-form">
        <input type="hidden" name="codigo_colaborador" value="${escapeHtml(colab.codigo_colaborador)}" />
        <label>Nova validade<input name="nova_validade" type="date" required /></label>
        <label>Categoria<input name="categoria_nova" value="${escapeHtml(colab.categoria_cnh || "")}" /></label>
        <label>Responsável<input name="responsavel" /></label>
        <label>Observação<textarea name="observacao"></textarea></label>
        <label>Comprovante<input name="arquivo" type="file" /></label>
        <button class="secondary-button full" type="submit">Registrar renovação</button>
      </form>
    </section>
    <section class="detail-section">
      <h3>Histórico recente</h3>
      <div class="timeline-list">
        ${(acompanhamentos.length ? acompanhamentos.slice(0, 4) : historico.slice(0, 4)).map((item) => `
          <div class="timeline-item">
            <div>
              <strong>${escapeHtml(item.status_label || item.observacao || "Registro")}</strong>
              <span>${escapeHtml(item.data_hora || item.validade_nova_formatada || "")}</span>
            </div>
          </div>
        `).join("") || emptySmall("Sem histórico de CNH.")}
      </div>
    </section>
  `;
  bindCnhForms();
}

function applyCnhQuickStatus(status) {
  const form = $("#cnhFollowForm");
  if (!form) {
    showToast("Selecione um colaborador na fila de CNH.");
    return;
  }
  const statusField = form.elements.status;
  if (statusField) statusField.value = status;
  if (form.elements.houve_contato) {
    form.elements.houve_contato.checked = ["SEM_RETORNO", "AGENDADO", "EM_ANDAMENTO"].includes(status);
  }
  const labels = {
    SEM_RETORNO: "Sem retorno",
    AGENDADO: "Agendado",
    EM_ANDAMENTO: "Em andamento",
    AGUARDANDO_DOCUMENTO: "Aguardando documento",
    REGULARIZADO: "Regularizado",
  };
  if (form.elements.observacao && !form.elements.observacao.value.trim()) {
    form.elements.observacao.value = labels[status] || "";
  }
  showToast("Ação preparada. Revise e salve o acompanhamento.");
}

async function applyCnhBulkFollowup() {
  const codigos = Array.from(state.selectedCnhCodes);
  const status = $("#cnhBulkStatus")?.value || "";
  if (!codigos.length) {
    showToast("Selecione colaboradores na fila.");
    return;
  }
  if (!status) {
    showToast("Escolha um status para aplicar.");
    return;
  }
  const payload = {
    codigos,
    status,
    responsavel: $("#cnhBulkResponsavel")?.value || "",
    data_prevista: $("#cnhBulkDataPrevista")?.value || "",
    observacao: $("#cnhBulkObs")?.value || "",
    houve_contato: $("#cnhBulkContato")?.checked ? "1" : "",
  };
  const data = await fetchJson("/api/cnh/acompanhamento-lote", {
    method: "POST",
    body: JSON.stringify(payload),
  });
  showToast(data.message || "Acompanhamento em lote aplicado.");
  state.selectedCnhCodes.clear();
  await Promise.all([loadCnh(), loadDashboard(), state.loadedTabs.has("pendencias") ? loadPendencias() : Promise.resolve()]);
}

function renderConsultaDetail(bundle) {
  const colab = bundle.colaborador || {};
  const docs = bundle.documentos || [];
  const atestados = bundle.atestados || [];
  const advertencias = bundle.advertencias || [];
  if (!("#consultaDetail")) return;
  if (!$("#consultaDetail")) return;
  if (!colab.codigo_colaborador) {
    $("#consultaDetail").innerHTML = `<div class="empty-state">Selecione um colaborador para ver o resumo sem sair da consulta.</div>`;
    return;
  }

  const cnhStatus = colab.status_cnh_acompanhamento_label || colab.status_cnh_acompanhamento || "Sem acompanhamento";
  const tone = dateTone(colab.validade_cnh);
  const hue = avatarHue(colab.codigo_colaborador);

  // Banner de alerta CNH
  let cnhBanner = "";
  if (tone === "danger") {
    cnhBanner = `<div class="cnh-alert-banner danger"><span class="cnh-alert-icon">⚠️</span><span>CNH vencida &mdash; ${escapeHtml(dueText(colab.validade_cnh))}</span></div>`;
  } else if (tone === "warning") {
    cnhBanner = `<div class="cnh-alert-banner warning"><span class="cnh-alert-icon">⏰</span><span>CNH vence em breve &mdash; ${escapeHtml(dueText(colab.validade_cnh))}</span></div>`;
  }

  $("#consultaDetail").innerHTML = `
    ${cnhBanner}
    <div class="detail-nav-bar">
      <button class="detail-nav-btn" data-action="consulta-prev" title="Colaborador anterior (seta ↑)">← Anterior</button>
      <span class="detail-nav-pos" id="consultaNavPos"></span>
      <button class="detail-nav-btn" data-action="consulta-next" title="Próximo colaborador (seta ↓)">Próximo →</button>
    </div>
    <div class="detail-card-head" style="border-bottom: 1px solid #e5ece7; padding-bottom: 12px; margin-bottom: 12px;">
      <span class="detail-avatar" data-hue style="--av-h:${hue}">${escapeHtml(String(colab.nome || colab.codigo_colaborador).slice(0, 1).toUpperCase())}</span>
      <div class="detail-title">
        <strong>${escapeHtml(colab.nome)}</strong>
        <span class="mini-text">
          <button class="copy-code-btn" data-action="copy-codigo" data-codigo="${escapeHtml(colab.codigo_colaborador)}" title="Copiar código">${escapeHtml(colab.codigo_colaborador)} 📋</button>
          &bull; ${escapeHtml(colab.situacao || "Sem situação")}
        </span>
      </div>
    </div>
    <div class="detail-section" style="border: none; margin-top: 0; padding-top: 0;">
      <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin-bottom: 12px;">
        <div>
          <span style="display: block; font-size: 0.72rem; color: var(--muted); font-weight: 800; text-transform: uppercase;">Status CNH</span>
          <strong style="display: block; font-size: 0.9rem; margin-top: 2px;">${formatDate(colab.validade_cnh)}</strong>
          <small class="${escapeHtml(tone)}" style="font-size: 0.7rem;">${escapeHtml(dueText(colab.validade_cnh))}</small>
        </div>
        <div>
          <span style="display: block; font-size: 0.72rem; color: var(--muted); font-weight: 800; text-transform: uppercase;">Anexos</span>
          <strong style="display: block; font-size: 0.9rem; margin-top: 2px;">${escapeHtml(String(docs.length + atestados.length + advertencias.length))}</strong>
          <small style="font-size: 0.7rem; color: var(--muted);">registros</small>
        </div>
      </div>
      <div class="list-stack compact-list" style="gap: 4px;">
        <div class="list-item" style="border: none; border-bottom: 1px solid #edf2ee; border-radius: 0; padding: 6px 0;"><strong>Função</strong><span>${escapeHtml(colab.funcao_safra || colab.funcao || "-")}</span></div>
        <div class="list-item" style="border: none; border-bottom: 1px solid #edf2ee; border-radius: 0; padding: 6px 0;"><strong>Frente</strong><span>${escapeHtml(colab.frente_safra || "-")}</span></div>
        <div class="list-item" style="border: none; border-bottom: 1px solid #edf2ee; border-radius: 0; padding: 6px 0;"><strong>Turno</strong><span>${escapeHtml(turnoHorarioText(colab))}</span></div>
        <div class="list-item" style="border: none; border-bottom: 1px solid #edf2ee; border-radius: 0; padding: 6px 0;"><strong>Cidade</strong><span>${escapeHtml(colab.cidade || "-")}</span></div>
        <div class="list-item" style="border: none; border-bottom: 1px solid #edf2ee; border-radius: 0; padding: 6px 0;"><strong>CNH Status</strong><span>${escapeHtml(cnhStatus)}</span></div>
      </div>
    </div>
    <div class="actions-row detail-actions" style="margin-top: 16px;">
      <button class="primary-button" data-action="open-cadastro" type="button">Editar cadastro</button>
      <button class="secondary-button" data-action="open-cnh" type="button">Ver CNH</button>
    </div>
  `;

  // Atualiza posição no painel
  const idx = state.colaboradores.findIndex((c) => String(c.codigo_colaborador) === String(colab.codigo_colaborador));
  const posEl = $("#consultaNavPos");
  if (posEl && idx !== -1) posEl.textContent = `${idx + 1} / ${state.colaboradores.length}`;
}

async function saveColaborador(event) {
  event.preventDefault();
  const payload = getFormObject(event.currentTarget);
  const data = await fetchJson("/api/colaboradores", {
    method: "POST",
    body: JSON.stringify(payload),
  });
  showToast(data.message || "Colaborador salvo.");
  setCadastroUnsaved(false);
  await loadColaboradorDetail(payload.codigo_colaborador, "cadastro");
  await loadDashboard();
  const reloads = [];
  if (state.loadedTabs.has("consulta")) reloads.push(loadColaboradores());
  if (state.loadedTabs.has("cnh")) reloads.push(loadCnh());
  if (state.loadedTabs.has("escala")) reloads.push(loadEscala());
  if (state.loadedTabs.has("pendencias")) reloads.push(loadPendencias());
  await Promise.all(reloads);
}

function newColaborador(switchToCadastro = true) {
  state.selectedCodigo = "";
  fillColaboradorForm({});
  renderAttachments({ documentos: [], atestados: [], advertencias: [] });
  $("#cnhDetail").innerHTML = `<div class="empty-state">Selecione um colaborador para acompanhar a CNH.</div>`;
  if ($("#consultaDetail")) {
    $("#consultaDetail").innerHTML = `<div class="empty-state">Selecione um colaborador para ver o resumo sem sair da consulta.</div>`;
  }
  markSelectedRows("");
  if (switchToCadastro) setActiveTab("cadastro");
}

async function deleteColaborador() {
  const codigo = state.selectedCodigo || $("#colaboradorForm").elements.codigo_colaborador.value;
  if (!codigo) {
    showToast("Selecione um colaborador antes de excluir.");
    return;
  }
  if (!confirm(`Excluir colaborador ${codigo}?`)) return;
  const data = await fetchJson(`/api/colaboradores/${encodeURIComponent(codigo)}`, { method: "DELETE" });
  showToast(data.message || "Colaborador excluído.");
  newColaborador();
  await loadDashboard();
  const reloads = [];
  if (state.loadedTabs.has("consulta")) reloads.push(loadColaboradores());
  if (state.loadedTabs.has("cnh")) reloads.push(loadCnh());
  if (state.loadedTabs.has("escala")) reloads.push(loadEscala());
  if (state.loadedTabs.has("pendencias")) reloads.push(loadPendencias());
  await Promise.all(reloads);
}

async function submitMultipart(form, endpoint) {
  if (!state.selectedCodigo && form.elements.codigo_colaborador) {
    showToast("Selecione ou salve um colaborador primeiro.");
    return;
  }
  const data = await fetchJson(endpoint, {
    method: "POST",
    body: new FormData(form),
  });
  showToast(data.message || "Registro salvo.");
  form.reset();
  syncAttachmentCodes();
  await loadColaboradorDetail(state.selectedCodigo, "cadastro");
}

function bindCnhForms() {
  $("#cnhFollowForm")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const data = await fetchJson("/api/cnh/acompanhamento", {
      method: "POST",
      body: new FormData(event.currentTarget),
    });
    showToast(data.message || "Acompanhamento salvo.");
    await loadColaboradorDetail(state.selectedCodigo, "cnh");
    await Promise.all([loadCnh(), loadDashboard(), state.loadedTabs.has("pendencias") ? loadPendencias() : Promise.resolve()]);
  });

  $("#cnhRenewForm")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const data = await fetchJson("/api/cnh/renovacao", {
      method: "POST",
      body: new FormData(event.currentTarget),
    });
    showToast(data.message || "Renovação registrada.");
    await loadColaboradorDetail(state.selectedCodigo, "cnh");
    await Promise.all([loadCnh(), loadDashboard(), state.loadedTabs.has("pendencias") ? loadPendencias() : Promise.resolve()]);
  });
}

async function loadEscala() {
  const data = await fetchJson("/api/escala");
  const payload = data.data || {};
  const resumo = payload.resumo || {};
  $("#escalaTotal").textContent = `${payload.total || 0} pessoas`;
  $("#escalaSummary").innerHTML = `
    <h3>Resumo</h3>
    <div class="list-stack compact-list">
      <div class="list-item"><strong>Escalados</strong><span>${escapeHtml(payload.total || 0)}</span></div>
      <div class="list-item"><strong>Frentes</strong><span>${escapeHtml(resumo.frentes || 0)}</span></div>
      <div class="list-item"><strong>1º turno</strong><span>${escapeHtml((resumo.turnos || {})["1º"] || 0)}</span></div>
      <div class="list-item"><strong>2º turno</strong><span>${escapeHtml((resumo.turnos || {})["2º"] || 0)}</span></div>
      <div class="list-item"><strong>Fora da escala</strong><span>${escapeHtml(resumo.foraEscala || 0)}</span></div>
    </div>
  `;
  $("#escalaGroups").innerHTML = (payload.grupos || []).map((group) => `
    <section class="escala-group">
      <header>
        <span>${escapeHtml(group.frente)}</span>
        <span>${escapeHtml(group.total)} pessoas | ${escapeHtml(escalaTurnoResumo(group) || "sem turno")}</span>
      </header>
      ${(group.frotas || []).map((frota) => `
        <div class="escala-frota">
          <div class="escala-frota-title">
            <strong>${escapeHtml(frota.frota)}</strong>
            <span>${escapeHtml(frota.total)} pessoas</span>
          </div>
          <div class="escala-person-grid">
            ${(frota.colaboradores || []).map((person) => `
              <div class="escala-person">
                <span class="escala-code">${escapeHtml(person.codigo_colaborador)}</span>
                <strong>${escapeHtml(person.nome)}</strong>
                <span>${escapeHtml(turnoHorarioText(person))}</span>
              </div>
            `).join("")}
          </div>
        </div>
      `).join("")}
    </section>
  `).join("");
}

async function saveScale(event) {
  event.preventDefault();
  const payload = getFormObject(event.currentTarget);
  const data = await fetchJson("/api/escala", {
    method: "POST",
    body: JSON.stringify(payload),
  });
  showToast(data.message || "Escala salva.");
  const reloads = [loadEscala()];
  if (state.loadedTabs.has("consulta")) reloads.push(loadColaboradores());
  if (state.loadedTabs.has("cnh")) reloads.push(loadCnh());
  if (state.loadedTabs.has("pendencias")) reloads.push(loadPendencias());
  await Promise.all(reloads);
}

async function loadAuditoria() {
  const params = new URLSearchParams({
    tipo_acao: $("#auditTipo").value,
    entidade: $("#auditEntidade").value,
    id: $("#auditId").value,
    limit: $("#auditLimit").value || "200",
  });
  const data = await fetchJson(`/api/auditoria?${params}`);
  const rows = data.data || [];
  $("#auditTableBody").innerHTML = rows.length
    ? rows.map((row) => `
      <tr>
        <td>${escapeHtml(row.data_hora)}</td>
        <td>${escapeHtml(row.tipo_acao)}</td>
        <td>${escapeHtml(row.entidade_afetada)}</td>
        <td>${escapeHtml(row.id_entidade)}</td>
        <td>${escapeHtml(row.detalhes)}</td>
      </tr>
    `).join("")
    : `<tr><td colspan="5">Nenhum log encontrado.</td></tr>`;
}

async function deleteAttachment(type, id) {
  const endpoints = {
    documento: "documentos",
    atestado: "atestados",
    advertencia: "advertencias",
  };
  if (!confirm("Excluir este registro?")) return;
  const data = await fetchJson(`/api/${endpoints[type]}/${id}`, { method: "DELETE" });
  showToast(data.message || "Registro excluído.");
  await loadColaboradorDetail(state.selectedCodigo, "cadastro");
}

function bindEvents() {
  $$(".tab").forEach((button) => {
    button.addEventListener("click", () => setActiveTab(button.dataset.tab));
  });

  document.addEventListener("click", async (event) => {
    const quickTab = event.target.closest(".dashboard-action[data-tab], .priority-card[data-tab]");
    if (quickTab) {
      await setActiveTab(quickTab.dataset.tab);
      return;
    }

    const cnhStatusButton = event.target.closest("[data-cnh-status]");
    if (cnhStatusButton) {
      state.cnhExtraFilter = "";
      $("#cnhStatusTecnico").value = cnhStatusButton.dataset.cnhStatus;
      $("#cnhPendentes").checked = true;
      await loadCnh();
      return;
    }

    const cnhFilterButton = event.target.closest("[data-cnh-filter]");
    if (cnhFilterButton) {
      state.cnhExtraFilter = cnhFilterButton.dataset.cnhFilter || "";
      $("#cnhStatusTecnico").value = "";
      $("#cnhPendentes").checked = true;
      await loadCnh();
      return;
    }

    if (event.target.closest(".cnh-row-check")) {
      const check = event.target.closest(".cnh-row-check");
      const codigo = String(check.dataset.codigo || "");
      if (check.checked) state.selectedCnhCodes.add(codigo);
      else state.selectedCnhCodes.delete(codigo);
      check.closest("tr")?.classList.toggle("bulk-selected", check.checked);
      markSelectedRows(state.selectedCodigo);
      updateCnhBulkBar();
      return;
    }

    if (event.target.closest("#cnhSelectAll")) {
      const check = event.target.closest("#cnhSelectAll");
      state.cnhRows.slice(0, state.cnhVisible).forEach((row) => {
        const codigo = String(row.codigo_colaborador);
        if (check.checked) state.selectedCnhCodes.add(codigo);
        else state.selectedCnhCodes.delete(codigo);
      });
      renderCnhRows();
      return;
    }

    const queueItem = event.target.closest(".queue-mini-card[data-codigo]");
    if (queueItem) {
      await loadColaboradorDetail(queueItem.dataset.codigo, "cnh");
      return;
    }

    const row = event.target.closest("tr[data-codigo]");
    if (row && row.closest("#cnhTableBody, #criticalCnhBody")) {
      await loadColaboradorDetail(row.dataset.codigo, "cnh");
      return;
    }
    if (row && row.closest("#consultaTableBody")) {
      await loadColaboradorDetail(row.dataset.codigo, "consulta");
      return;
    }

    const pending = event.target.closest(".pending-item[data-codigo]");
    if (pending) {
      await loadColaboradorDetail(pending.dataset.codigo, "consulta");
      setActiveTab("consulta");
      return;
    }

    const action = event.target.closest("[data-action]")?.dataset.action;
    if (!action) return;

    if (action === "refresh") await loadAll();
    if (action === "load-pendencias") await ensureTabData("pendencias", true);
    if (action === "load-cnh") {
      state.cnhExtraFilter = "";
      await loadCnh();
    }
    if (action === "load-colaboradores") await loadColaboradores();
    if (action === "load-more-cnh") { state.cnhPage++; loadCnh(true); }
    if (action === "load-more-colaboradores") {
      state.consultaVisible += 120;
      renderColaboradorRows();
    }
    if (action === "open-cadastro") setActiveTab("cadastro");
    if (action === "open-cnh") setActiveTab("cnh");
    if (action === "open-auditoria") setActiveTab("auditoria");
    if (action === "cnh-quick-status") applyCnhQuickStatus(event.target.closest("[data-status]")?.dataset.status || "");
    if (action === "apply-cnh-bulk") await applyCnhBulkFollowup();
    if (action === "load-escala") await loadEscala();
    if (action === "load-auditoria") await loadAuditoria();
    if (action === "new-colaborador") newColaborador();
    if (action === "export-consulta-csv") exportConsultaCsv();
    if (action === "consulta-prev") consultaNavigate("prev");
    if (action === "consulta-next") consultaNavigate("next");
    if (action === "copy-codigo") {
      const btn = event.target.closest("[data-codigo]");
      if (btn) {
        navigator.clipboard.writeText(btn.dataset.codigo)
          .then(() => showToast(`Código ${btn.dataset.codigo} copiado!`))
          .catch(() => showToast("Não foi possível copiar."));
      }
    }
    if (action === "clear-consulta-filters") {
      $("#consultaSearch").value = "";
      $("#consultaSituacao").value = "";
      $("#consultaFuncao").value = "";
      $("#consultaCidade").value = "";
      $("#consultaTurno").value = "";
      $("#consultaCnhVencida").checked = false;
      updateConsultaFilterBadge();
      await loadColaboradores();
    }
    if (action === "delete-colaborador") await deleteColaborador();
    if (action === "delete-documento") await deleteAttachment("documento", event.target.closest("[data-id]").dataset.id);
    if (action === "delete-atestado") await deleteAttachment("atestado", event.target.closest("[data-id]").dataset.id);
    if (action === "delete-advertencia") await deleteAttachment("advertencia", event.target.closest("[data-id]").dataset.id);
    if (action === "edit-scale") {
      const button = event.target.closest("[data-action]");
      const form = $("#scaleForm");
      if (!form) return;
      form.elements.codigo_colaborador.value = button.dataset.codigo || "";
      form.elements.nome.value = button.dataset.nome || "";
      form.elements.frente_safra.value = button.dataset.frente || "";
      form.elements.turno_safra.value = button.dataset.turno || "";
      form.elements.funcao_safra.value = button.dataset.funcao || "";
      form.elements.horario.value = button.dataset.horario || "";
    }
  });

  // ── Rastreia alterações não salvas no formulário de cadastro ──
  $("#colaboradorForm")?.addEventListener("input", () => setCadastroUnsaved(true));
  $("#colaboradorForm")?.addEventListener("change", () => setCadastroUnsaved(true));
  $("#cnhBulkStatus")?.addEventListener("change", updateCnhBulkBar);
  $("#cnhBulkResponsavel")?.addEventListener("input", updateCnhBulkBar);
  $("#cnhBulkObs")?.addEventListener("input", updateCnhBulkBar);
  $("#colaboradorForm").addEventListener("submit", saveColaborador);
  $("#scaleForm")?.addEventListener("submit", saveScale);
  $("#documentForm").addEventListener("submit", (event) => {
    event.preventDefault();
    submitMultipart(event.currentTarget, "/api/documentos");
  });
  $("#atestadoForm").addEventListener("submit", (event) => {
    event.preventDefault();
    submitMultipart(event.currentTarget, "/api/atestados");
  });
  $("#advertenciaForm").addEventListener("submit", (event) => {
    event.preventDefault();
    submitMultipart(event.currentTarget, "/api/advertencias");
  });

  for (const selector of ["#cnhSearch", "#consultaSearch"]) {
    const runSearch = debounce(() => {
      if (!shouldRunSearch($(selector).value)) return;
      const request = selector === "#cnhSearch" ? loadCnh() : loadColaboradores();
      request.catch((error) => showToast(error.message));
    }, 380);

    $(selector).addEventListener("input", () => {
      if (selector === "#consultaSearch") updateConsultaFilterBadge();
      runSearch();
    });

    $(selector).addEventListener("keydown", async (event) => {
      if (event.key === "Enter") {
        event.preventDefault();
        if (selector === "#cnhSearch") await loadCnh();
        if (selector === "#consultaSearch") await loadColaboradores();
      }
    });
  }

  for (const id of ["#cnhStatusTecnico", "#cnhStatusAcomp", "#cnhFrente", "#cnhGestor", "#cnhPendentes"]) {
    $(id)?.addEventListener("change", () => {
      state.cnhExtraFilter = "";
      loadCnh().catch((error) => showToast(error.message));
    });
  }

  // ── Atualiza badge ao mudar qualquer filtro da Consulta ──
  for (const id of ["#consultaSituacao", "#consultaFuncao", "#consultaCidade", "#consultaTurno", "#consultaCnhVencida"]) {
    $(id)?.addEventListener("change", updateConsultaFilterBadge);
  }

  // ── Ordenação por coluna ─────────────────────────────────
  document.addEventListener("click", (event) => {
    const th = event.target.closest("th.sortable");
    if (!th) return;
    const key = th.dataset.sort;
    if (!key) return;
    if (state.consultaSort.key === key) {
      state.consultaSort.dir = state.consultaSort.dir === "asc" ? "desc" : "asc";
    } else {
      state.consultaSort.key = key;
      state.consultaSort.dir = "asc";
    }
    renderColaboradorRows();
  });

  // ── Atalhos de teclado globais ────────────────────────────
  document.addEventListener("keydown", (event) => {
    const tag = document.activeElement?.tagName;
    const isTyping = ["INPUT", "TEXTAREA", "SELECT"].includes(tag);

    // / ou f  →  foca na busca da Consulta (apenas quando na aba consulta e não digitando)
    if (!isTyping && state.activeTab === "consulta" && (event.key === "/" || event.key === "f" || event.key === "F")) {
      event.preventDefault();
      $("#consultaSearch")?.focus();
      return;
    }

    // Esc  →  fecha painel lateral / limpa seleção
    if (event.key === "Escape" && state.activeTab === "consulta" && state.selectedCodigo) {
      event.preventDefault();
      state.selectedCodigo = "";
      markSelectedRows("");
      if ($("#consultaDetail")) {
        $("#consultaDetail").innerHTML = `<div class="empty-state">Selecione um colaborador para ver o resumo sem sair da consulta.</div>`;
      }
      return;
    }

    // ↑ ↓  →  navega entre colaboradores (apenas na aba consulta, fora de inputs)
    if (!isTyping && state.activeTab === "consulta" && state.selectedCodigo) {
      if (event.key === "ArrowDown") {
        event.preventDefault();
        consultaNavigate("next");
        return;
      }
      if (event.key === "ArrowUp") {
        event.preventDefault();
        consultaNavigate("prev");
      }
    }
  });
}

async function loadAll() {
  try {
    await loadStatus();
    await loadOpcoes();
    await setActiveTab(state.activeTab || "cnh", { force: true });
    if (state.activeTab !== "dashboard") await loadDashboard();
  } catch (error) {
    showToast(error.message);
  }
}

configureLauncherLinks();
bindEvents();
newColaborador(false);
loadAll();
