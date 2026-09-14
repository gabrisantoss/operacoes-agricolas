const state = {
  options: { frentes: [], frotas: [], turnos: [], date_range: {} },
  tableOffset: 0,
  tableLimit: 160,
  tableTotal: 0,
  refreshToken: 0,
  refreshController: null,
  activeTab: "dashboard",
  tableDirty: true,
  tableLoaded: false,
  optionsLoadedAt: 0,
  optionsTtlMs: 5 * 60 * 1000,
  downloads: new Set(),
};

const $ = (selector) => document.querySelector(selector);

function debounce(fn, delay = 360) {
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

function configureLauncherLinks() {
  const host = window.location.hostname || "127.0.0.1";
  const url = `${window.location.protocol}//${host}:8890/`;
  document.querySelectorAll("[data-launcher-link]").forEach((link) => {
    link.href = url;
  });
}

function todayIso() {
  return new Date().toISOString().slice(0, 10);
}

function nowText() {
  return new Date().toLocaleTimeString("pt-BR", {
    hour: "2-digit",
    minute: "2-digit",
  });
}

function queryParams(extra = {}) {
  const params = new URLSearchParams();
  const values = {
    start: $("#filterStart").value,
    end: $("#filterEnd").value,
    frente: $("#filterFrente").value,
    turno: $("#filterTurno").value,
    status: $("#filterStatus").value,
    frota: $("#filterFrota").value,
    q: $("#filterSearch").value.trim(),
    ...extra,
  };
  Object.entries(values).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== "") params.set(key, value);
  });
  return params;
}

async function fetchJson(url, options = {}) {
  const timeoutMs = options.timeoutMs || 25000;
  const parentSignal = options.signal;
  const controller = new AbortController();
  const abortFromParent = () => controller.abort();
  const timeout = window.setTimeout(() => controller.abort(), timeoutMs);
  const fetchOptions = { ...options, signal: controller.signal };
  delete fetchOptions.timeoutMs;

  if (parentSignal) {
    if (parentSignal.aborted) controller.abort();
    else parentSignal.addEventListener("abort", abortFromParent, { once: true });
  }

  try {
    const response = await fetch(url, fetchOptions);
    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.message || data.error || "Falha na requisicao.");
    }
    return data;
  } finally {
    window.clearTimeout(timeout);
    if (parentSignal) parentSignal.removeEventListener("abort", abortFromParent);
  }
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function fillSelect(select, values, allLabel) {
  select.innerHTML = "";
  const all = document.createElement("option");
  all.value = "";
  all.textContent = allLabel;
  select.appendChild(all);

  values.forEach((value) => {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = value;
    select.appendChild(option);
  });
}

function fillDatalist(list, values) {
  list.innerHTML = values.map((value) => `<option value="${escapeHtml(value)}"></option>`).join("");
}

async function loadOptions({ force = false } = {}) {
  const now = Date.now();
  if (!force && state.optionsLoadedAt && now - state.optionsLoadedAt < state.optionsTtlMs) {
    return state.options;
  }
  state.options = await fetchJson("/api/options");
  state.optionsLoadedAt = now;
  fillSelect($("#filterFrente"), state.options.frentes, "Todas");
  fillSelect($("#filterTurno"), state.options.turnos, "Todos");
  fillSelect($("#filterFrota"), state.options.frotas, "Todas");
  fillDatalist($("#frentesList"), state.options.frentes);
  fillDatalist($("#frotasList"), state.options.frotas);

  if (state.options.date_range) {
    $("#filterStart").value = state.options.date_range.start || "";
    $("#filterEnd").value = state.options.date_range.end || "";
  }
}

function renderTopReasons(items = []) {
  const maxMinutes = Math.max(...items.map((item) => item.minutes || 0), 1);
  $("#topReasons").innerHTML = items.length ? items.map((item) => {
    const width = Math.max(4, Math.round((item.minutes || 0) / maxMinutes * 100));
    return `
      <div class="reason-row">
        <div>
          <strong>${escapeHtml(item.motivo)}</strong>
          <div class="bar"><span style="width:${width}%"></span></div>
        </div>
        <span>${escapeHtml(item.count)} registros</span>
        <strong>${minutesToHours(item.minutes)}</strong>
      </div>
    `;
  }).join("") : `<p>Sem dados no periodo.</p>`;
}

function renderTurnEfficiency(items = []) {
  $("#turnEfficiency").innerHTML = items.length ? items.map((item) => {
    const width = Math.max(4, Math.min(100, Math.round(item.eficiencia || 0)));
    return `
      <div class="turn-row">
        <strong>Turno ${escapeHtml(item.turno)}</strong>
        <div class="bar"><span style="width:${width}%"></span></div>
        <strong>${Number(item.eficiencia || 0).toFixed(2)}%</strong>
      </div>
    `;
  }).join("") : `<p>Sem eficiencia finalizada.</p>`;
}

function renderPending(items = []) {
  $("#pendingCountLabel").textContent = `${items.length} exibidas`;
  $("#pendingList").innerHTML = items.length ? items.map((row) => `
    <div class="pending-row">
      <strong>${escapeHtml(row.Data)}</strong>
      <span>F${escapeHtml(row.Frente)}</span>
      <span>T${escapeHtml(row.Turno)}</span>
      <span>${escapeHtml(row.Frota)}</span>
      <span>${escapeHtml(row.Motivo)}</span>
      <strong>${escapeHtml(row.Parou_Hora)}</strong>
    </div>
  `).join("") : `<p>Nenhuma parada em andamento no filtro atual.</p>`;
}

function minutesToHours(total) {
  const value = Math.max(0, Number(total || 0));
  const hours = Math.floor(value / 60);
  const minutes = value % 60;
  return `${hours}:${String(minutes).padStart(2, "0")}`;
}

async function loadSummary({ signal } = {}) {
  const data = await fetchJson(`/api/summary?${queryParams()}`, { signal });
  $("#metricTotal").textContent = data.total_registros;
  $("#metricHours").textContent = data.total_horas_paradas;
  $("#metricEfficiency").textContent = `${Number(data.eficiencia_media || 0).toFixed(2)}%`;
  $("#metricPending").textContent = data.em_andamento;
  $("#metricColhedora").textContent = data.colhedora;
  $("#metricTransbordo").textContent = data.transbordo;
  $("#metricCriteria").textContent = data.criterio;
  renderTopReasons(data.top_motivos);
  renderTurnEfficiency(data.eficiencia_por_turno);
  renderPending(data.paradas_em_andamento);
}

function operationRow(row) {
  const statusClass = row.Status_Parada === "Em Andamento" ? "aberta" : "finalizada";
  return `
    <tr>
      <td>${escapeHtml(row.Data)}</td>
      <td>${escapeHtml(row.Frente)}</td>
      <td>${escapeHtml(row.Turno)}</td>
      <td><strong>${escapeHtml(row.Frota)}</strong></td>
      <td>${escapeHtml(row.Motivo)}</td>
      <td>${escapeHtml(row.Parou_Hora)}</td>
      <td>${escapeHtml(row.Voltou_Hora)}</td>
      <td>${escapeHtml(row.Total_Hora_Parado)}</td>
      <td>${row.Eficiencia == null ? "" : Number(row.Eficiencia).toFixed(2)}</td>
      <td><span class="status-badge ${statusClass}">${escapeHtml(row.Status_Parada)}</span></td>
    </tr>
  `;
}

async function loadOperations({ append = false, signal } = {}) {
  const loadMoreButton = $("#loadMore");
  const refreshButton = $("#refreshTable");
  loadMoreButton.disabled = true;
  refreshButton.disabled = true;

  const params = queryParams({
    limit: state.tableLimit,
    offset: append ? state.tableOffset : 0,
  });
  try {
    const data = await fetchJson(`/api/operations?${params}`, { signal });
    state.tableTotal = data.total;
    state.tableOffset = (append ? state.tableOffset : 0) + data.rows.length;

    const html = data.rows.map(operationRow).join("");
    if (append) {
      $("#operationsBody").insertAdjacentHTML("beforeend", html);
    } else {
      $("#operationsBody").innerHTML = html;
      state.tableLoaded = true;
      state.tableDirty = false;
    }
    $("#tableCount").textContent = `${state.tableOffset} de ${state.tableTotal} linhas`;
    loadMoreButton.disabled = !data.has_more;
  } finally {
    refreshButton.disabled = false;
    loadMoreButton.disabled = state.tableOffset >= state.tableTotal;
  }
}

async function loadOperationsSafe(options = {}) {
  try {
    await loadOperations(options);
  } catch (error) {
    if (error.name === "AbortError") return;
    $("#tableCount").textContent = error.message;
  }
}

function markTableDirty() {
  state.tableDirty = true;
  if (state.activeTab !== "dados") {
    $("#tableCount").textContent = state.tableLoaded
      ? "Tabela pendente de atualizar"
      : "Abra a aba Dados para carregar";
  }
}

async function ensureTableLoaded() {
  if (state.activeTab === "dados" && (state.tableDirty || !state.tableLoaded)) {
    await loadOperationsSafe();
  }
}

async function refreshAll() {
  const token = ++state.refreshToken;
  if (state.refreshController) state.refreshController.abort();
  const controller = new AbortController();
  state.refreshController = controller;
  const shouldLoadTable = state.activeTab === "dados";

  $("#lastUpdate").textContent = "Atualizando...";
  try {
    const jobs = [loadSummary({ signal: controller.signal })];
    if (shouldLoadTable) jobs.push(loadOperations({ signal: controller.signal }));
    else markTableDirty();
    await Promise.all(jobs);
    if (token !== state.refreshToken) return;
    $("#lastUpdate").textContent = `Atualizado as ${nowText()}`;
  } catch (error) {
    if (error.name === "AbortError") return;
    $("#lastUpdate").textContent = error.message;
  } finally {
    if (state.refreshController === controller) state.refreshController = null;
  }
}

function switchTab(tabId) {
  state.activeTab = tabId;
  document.querySelectorAll(".tab").forEach((tab) => {
    tab.classList.toggle("active", tab.dataset.tab === tabId);
  });
  document.querySelectorAll(".view").forEach((view) => {
    view.classList.toggle("active", view.id === tabId);
  });
  if (tabId === "dados") ensureTableLoaded();
  if (tabId === "relatorios") loadSystemStatus({ quiet: true });
}

function clearFilters() {
  $("#filterStart").value = state.options.date_range?.start || "";
  $("#filterEnd").value = state.options.date_range?.end || "";
  $("#filterFrente").value = "";
  $("#filterTurno").value = "";
  $("#filterStatus").value = "";
  $("#filterFrota").value = "";
  $("#filterSearch").value = "";
  refreshAll();
}

function updateStatusFields() {
  const andamento = $("#formStatus").value === "Em Andamento";
  $("#voltouField").style.display = andamento ? "none" : "";
  $("#formVoltou").value = andamento ? "" : $("#formVoltou").value;
}

async function submitOperation(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const payload = Object.fromEntries(new FormData(form).entries());
  $("#formMessage").textContent = "Salvando...";

  try {
    const data = await fetchJson("/api/operations", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    $("#formMessage").textContent = data.message;
    form.reset();
    $("#formDate").value = todayIso();
    updateStatusFields();
    markTableDirty();
    await loadOptions({ force: true });
    await refreshAll();
  } catch (error) {
    $("#formMessage").textContent = error.message;
  }
}

function filenameFromDisposition(header, fallback) {
  const match = String(header || "").match(/filename="?([^"]+)"?/i);
  return match ? match[1] : fallback;
}

async function download(path, button) {
  if (state.downloads.has(path)) return;
  const params = queryParams();
  const originalText = button?.textContent || "";
  state.downloads.add(path);
  if (button) {
    button.disabled = true;
    button.textContent = "Gerando...";
  }

  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), 120000);
  try {
    const response = await fetch(`${path}?${params}`, { signal: controller.signal });
    if (!response.ok) {
      let message = "Nao foi possivel gerar o arquivo.";
      try {
        const data = await response.json();
        message = data.message || data.error || message;
      } catch {
        // Mantem a mensagem padrao quando a resposta nao for JSON.
      }
      throw new Error(message);
    }
    const blob = await response.blob();
    const filename = filenameFromDisposition(response.headers.get("Content-Disposition"), "relatorio");
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
  } catch (error) {
    alert(error.name === "AbortError" ? "Tempo esgotado ao gerar o arquivo." : error.message);
  } finally {
    window.clearTimeout(timeout);
    state.downloads.delete(path);
    if (button) {
      button.disabled = false;
      button.textContent = originalText;
    }
  }
}

function renderSystemStatus(data) {
  const errors = data.recent_errors?.length
    ? data.recent_errors.map((line) => `ERRO: ${line}`).join("\n")
    : "Sem erro recente no log.";
  const starts = data.recent_start?.length
    ? data.recent_start.join("\n")
    : "Sem registro recente de inicializacao.";
  $("#systemStatusBody").textContent = [
    `Verificado em: ${data.checked_at || "-"}`,
    `Banco: ${data.database?.quick_check || "-"}`,
    `Modo: ${data.database?.journal_mode || "-"}`,
    `Tamanho: ${data.database?.size_mb ?? 0} MB`,
    `Ultima alteracao: ${data.database?.modified_at || "-"}`,
    "",
    "Inicializacao:",
    starts,
    "",
    "Erros:",
    errors,
  ].join("\n");
}

async function loadSystemStatus({ quiet = false } = {}) {
  const button = $("#checkSystemStatus");
  if (!button || button.disabled) return;
  const originalText = button.textContent;
  if (!quiet) {
    button.disabled = true;
    button.textContent = "Verificando...";
  }
  try {
    const data = await fetchJson("/api/system/status", { timeoutMs: 10000 });
    renderSystemStatus(data);
  } catch (error) {
    $("#systemStatusBody").textContent = error.message;
  } finally {
    if (!quiet) {
      button.disabled = false;
      button.textContent = originalText;
    }
  }
}

async function boot() {
  configureLauncherLinks();
  $("#formDate").value = todayIso();

  document.querySelectorAll(".tab").forEach((tab) => {
    tab.addEventListener("click", () => switchTab(tab.dataset.tab));
  });
  $("#applyFilters").addEventListener("click", refreshAll);
  $("#clearFilters").addEventListener("click", clearFilters);
  $("#refreshAll").addEventListener("click", refreshAll);
  $("#refreshTable").addEventListener("click", () => loadOperationsSafe());
  $("#loadMore").addEventListener("click", () => loadOperationsSafe({ append: true }));
  $("#operationForm").addEventListener("submit", submitOperation);
  $("#formStatus").addEventListener("change", updateStatusFields);
  $("#filterSearch").addEventListener("keydown", (event) => {
    if (event.key === "Enter") refreshAll();
  });
  $("#filterSearch").addEventListener("input", debounce(() => {
    if (shouldRunSearch($("#filterSearch").value)) refreshAll();
  }, 420));
  $("#downloadOperationPdf").addEventListener("click", (event) => download("/api/reports/operations", event.currentTarget));
  $("#downloadEfficiencyPdf").addEventListener("click", (event) => download("/api/reports/efficiency", event.currentTarget));
  $("#downloadDatabaseExcel").addEventListener("click", (event) => download("/api/export/database", event.currentTarget));
  $("#checkSystemStatus").addEventListener("click", () => loadSystemStatus());

  try {
    await fetchJson("/api/health");
    $("#serverStatus").textContent = "Online";
    await loadOptions();
    updateStatusFields();
    await refreshAll();
  } catch (error) {
    $("#serverStatus").textContent = "Erro";
    $("#lastUpdate").textContent = error.message;
    console.error(error);
  }
}

boot();
