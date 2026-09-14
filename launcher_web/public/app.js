const grid = document.querySelector("#appsGrid");
const template = document.querySelector("#appCardTemplate");
const userName = document.querySelector("#userName");
const logoutButton = document.querySelector("#logoutButton");
const adminToggle = document.querySelector("#adminToggle");
const adminPanel = document.querySelector("#adminPanel");
const launcherViews = document.querySelectorAll("[data-launcher-view]");
const backToLauncher = document.querySelector("#backToLauncher");
const refreshUsers = document.querySelector("#refreshUsers");
const usersList = document.querySelector("#usersList");
const refreshSystemHealth = document.querySelector("#refreshSystemHealth");
const systemHealthStatus = document.querySelector("#systemHealthStatus");
const refreshActivity = document.querySelector("#refreshActivity");
const activityList = document.querySelector("#activityList");
const activityFilters = document.querySelector("#activityFilters");
const activityUser = document.querySelector("#activityUser");
const activityModule = document.querySelector("#activityModule");
const activityEventType = document.querySelector("#activityEventType");
const activityStart = document.querySelector("#activityStart");
const activityEnd = document.querySelector("#activityEnd");
const activitySearch = document.querySelector("#activitySearch");
const activitySummary = document.querySelector("#activitySummary");
const exportActivity = document.querySelector("#exportActivity");
const backupNow = document.querySelector("#backupNow");
const backupStatus = document.querySelector("#backupStatus");
const welcomeScreen = document.querySelector("#welcomeScreen");
const welcomeName = document.querySelector("#welcomeName");
const welcomeContinue = document.querySelector("#welcomeContinue");
const profileToggle = document.querySelector("#profileToggle");
const profileDialog = document.querySelector("#profileDialog");
const profileForm = document.querySelector("#profileForm");
const profileClose = document.querySelector("#profileClose");
const profileCancel = document.querySelector("#profileCancel");
const profileSubmit = document.querySelector("#profileSubmit");
const profileAvatar = document.querySelector("#profileAvatar");
const profileAccountType = document.querySelector("#profileAccountType");
const profileName = document.querySelector("#profileName");
const profileEmail = document.querySelector("#profileEmail");
const profileSecurity = document.querySelector(".profile-security");
const profileIntegratedPasswordNote = document.querySelector("#profileIntegratedPasswordNote");
const profileCurrentPassword = document.querySelector("#profileCurrentPassword");
const profileNewPassword = document.querySelector("#profileNewPassword");
const profileConfirmPassword = document.querySelector("#profileConfirmPassword");
const profileMessage = document.querySelector("#profileMessage");

// Identidade funcional atual. O id tecnico "balanca" fica como legado para
// preservar rotas, permissoes, auditoria, storage e integracoes existentes.
const portalIdentity = Object.freeze({
  currentName: "Portal de Opera\u00e7\u00f5es Agr\u00edcolas",
  currentNameAscii: "Portal de Operacoes Agricolas",
  legacyModuleId: "balanca",
  legacyNames: ["Balanca Audit", "Auditoria da Balanca"],
});



const fallbackApps = [
  {
    id: "notas",
    name: "Sistema de Notas",
    description: "Notas e transporte da safra.",
    kind: "web",
    button: "Verificando",
    exists: true,
    running: false,
    status: "unknown",
  },
  {
    id: "colaboradores",
    name: "Gestor de Colaboradores",
    description: "Cadastros, CNH e documentos.",
    kind: "web",
    button: "Verificando",
    exists: true,
    running: false,
    status: "unknown",
  },
  {
    id: "balanca",
    name: portalIdentity.currentName,
    description: "Colheita, pesagem, PDFs e divergencias operacionais.",
    kind: "web",
    button: "Verificando",
    exists: true,
    running: false,
    status: "unknown",
  },

  {
    id: "analises",
    name: "Analises Operacionais",
    description: "Indicadores da operacao.",
    kind: "web",
    button: "Verificando",
    exists: true,
    running: false,
    status: "unknown",
  },
];

let currentApps = [...fallbackApps];
let loadingStatus = false;
let statusRequest = null;
let lastStatusLoadAt = 0;
let currentUser = null;
let adminSystems = [];
let adminDataLoaded = false;
let adminDataRequest = null;

const appIcons = {
  notas: `
    <svg viewBox="0 0 48 48" focusable="false">
      <path class="icon-fill" d="M8 28h25l5 5v7H8z" />
      <path d="M13 28V13h17l5 5v10" />
      <path d="M30 13v6h6" />
      <path d="M17 20h8M17 25h12" />
      <path d="M9 34h30" />
      <circle class="icon-dot" cx="16" cy="40" r="3" />
      <circle class="icon-dot" cx="34" cy="40" r="3" />
      <path class="icon-accent" d="M39 11c-4 5-5 11-5 17" />
      <path class="icon-accent" d="M39 11c3 4 3 8 0 12" />
    </svg>`,
  colaboradores: `
    <svg viewBox="0 0 48 48" focusable="false">
      <rect class="icon-fill" x="12" y="10" width="24" height="31" rx="5" />
      <path d="M19 10V7h10v3" />
      <circle class="icon-dot" cx="24" cy="22" r="5" />
      <path d="M16 35c2-6 14-6 16 0" />
      <path d="M18 16h12" />
      <path class="icon-accent" d="M38 17c-4 5-5 10-5 18" />
      <path class="icon-accent" d="M38 17c3 4 3 8 0 12" />
    </svg>`,
  balanca: `
    <svg viewBox="0 0 48 48" focusable="false">
      <path class="icon-fill" d="M9 30h26l4 4v5H9z" />
      <path d="M11 39h28" />
      <circle class="icon-dot" cx="17" cy="39" r="3" />
      <circle class="icon-dot" cx="33" cy="39" r="3" />
      <path d="M13 30l4-11 4 11M27 30l4-11 4 11" />
      <path d="M14 30h22" />
      <path class="icon-accent" d="M31 11l3 3 6-7" />
      <path d="M24 10v9M15 19h18" />
    </svg>`,
  analises: `
    <svg viewBox="0 0 48 48" focusable="false">
      <path class="icon-fill" d="M8 29h18l5 5v6H8z" />
      <path d="M13 29v-9h10l5 5v4" />
      <path d="M23 20v6h6" />
      <circle class="icon-dot" cx="16" cy="40" r="3" />
      <circle class="icon-dot" cx="31" cy="40" r="3" />
      <path class="icon-accent" d="M35 34V22M40 34V16M45 34V26" />
      <path class="icon-accent" d="M34 18l5-5 5 4" />
      <path d="M11 24c2-6 5-9 10-13" />
    </svg>`,
};

const appDescriptions = {
  notas: "Notas e transporte da safra.",
  colaboradores: "Cadastros, CNH e documentos.",
  balanca: "Colheita, pesagem, PDFs e divergencias operacionais.",
  analises: "Indicadores da operacao.",
};

const appQuickNotes = {
  notas: {
    label: "Operacao de safra",
    text: "Lancamento de notas, viagens, cargas, historico e relatorios do transporte.",
  },
  colaboradores: {
    label: "Gestao de pessoas",
    text: "Cadastros, escala, documentos, CNH e acompanhamento de pendencias por frente.",
  },
  balanca: {
    label: "Operacoes agricolas",
    text: "Acompanhamento da colheita, validacao de PDFs da balanca, OS, fazendas, talhoes e divergencias.",
  },

  analises: {
    label: "Indicadores operacionais",
    text: "Apontamentos, paradas, frotas, eficiencia, dashboards e relatorios da operacao.",
  },
};

const moduleLabels = {
  launcher: "Launcher",
  notas: "Sistema de Notas",
  colaboradores: "Gestor de Colaboradores",
  balanca: portalIdentity.currentName,
  analises: "Analises Operacionais",
};

const eventLabels = {
  LOGIN_SUCCESS: "Login",
  LOGIN_FAILED: "Falha de login",
  LOGOUT: "Logout",
  ACCESS_DENIED: "Acesso negado",
  OPEN_SYSTEM: "Abriu sistema",
  PROXY_ERROR: "Erro de proxy",
  SYSTEM_STARTED: "Sistema iniciado",
  SYSTEM_STOPPED: "Sistema parado",
  BACKUP_CREATED: "Backup criado",
  BACKUP_FAILED: "Falha no backup",
  RESTORE_STARTED: "Restauracao iniciada",
  RESTORE_COMPLETED: "Restauracao concluida",
  RESTORE_FAILED: "Falha na restauracao",
  PERMISSION_CHANGED: "Permissao alterada",
  USER_CREATED: "Usuario criado",
  USER_DISABLED: "Usuario bloqueado",
  USER_DELETED: "Usuario excluido",
  PROFILE_UPDATED: "Perfil atualizado",
  PROFILE_UPDATE_DENIED: "Atualizacao de perfil negada",
  "auth.login": "Login",
  "auth.logout": "Logout",
  "access.request": "Solicitacao de acesso",
  "access.approve": "Liberacao de acesso",
  "access.block": "Bloqueio de acesso",
  "access.password_update": "Senha alterada",
  "app.start": "Iniciou sistema",
  "app.start_failed": "Falha ao iniciar",
  "backup.create": "Backup criado",
  "backup.failed": "Falha no backup",
  "backup.verify": "Backup verificado",
  "backup.prepare_restore": "Restauracao preparada",
  "nota.create": "Nota criada",
  "nota.update": "Nota atualizada",
  "nota.delete": "Nota excluida",
  "nota.duplicate": "Nota duplicada",
  "nota.bulk_correction": "Correcao em lote",
  "cadastro.create": "Cadastro criado",
  "cadastro.delete": "Cadastro excluido",
  "colaborador.create": "Colaborador criado",
  "colaborador.update": "Colaborador atualizado",
  "colaborador.delete": "Colaborador excluido",
  "escala.update": "Escala atualizada",
  "cnh.followup": "Acompanhamento CNH",
  "cnh.renewal": "Renovacao CNH",
  "documento.create": "Documento criado",
  "documento.delete": "Documento excluido",
  "operation.create": "Apontamento operacional",
};

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function iconMarkup(app) {
  return appIcons[app.id] || `
    <svg viewBox="0 0 48 48" focusable="false">
      <rect x="10" y="10" width="28" height="28" rx="6" />
      <path d="M17 20h14M17 28h14" />
    </svg>`;
}

function kindText(app) {
  if (app.kind === "web") return "";
  if (app.kind === "internal") return "Portal interno";
  return "Aplicativo local";
}

function statusText(status) {
  const labels = {
    online: "Online",
    degraded: "Atencao",
    offline: "Offline",
    unknown: "Verificando",
    iniciado: "Iniciado",
    iniciando: "Iniciando",
    manutencao: "Manutencao",
    inativo: "Indisponivel",
    pronto: "Pronto",
    erro: "Erro",
  };
  return labels[status] || status;
}

function renderApps(apps) {
  grid.innerHTML = "";
  for (const app of apps) {
    const tile = document.createElement("div");
    tile.className = "app-tile";

    const node = template.content.firstElementChild.cloneNode(true);
    node.classList.add(app.kind);
    node.dataset.status = app.status;

    const title = node.querySelector("h3");
    const icon = node.querySelector(".app-icon");
    const category = node.querySelector(".app-category");
    const description = node.querySelector(".app-description");
    const kind = node.querySelector(".app-kind");
    const pill = node.querySelector(".status-pill");
    const startButton = node.querySelector(".start-button");
    const buttonText = node.querySelector(".button-text");
    const restricted = Boolean(app.restricted);
    const developmentRestricted = restricted
      && app.id !== portalIdentity.legacyModuleId
      && String(currentUser?.email || "").trim().toLowerCase() === "visitante@example.invalid";
    const restrictedMessage = developmentRestricted
      ? "Este portal est\u00e1 em desenvolvimento. Acesso ainda indispon\u00edvel."
      : app.maintenanceMessage || "Acesso restrito ao administrador.";
    const quickNote = appQuickNotes[app.id];

    title.textContent = app.name;
    if (category) category.textContent = quickNote?.label || "Sistema interno";
    if (description) description.textContent = developmentRestricted
      ? "Dispon\u00edvel em breve."
      : quickNote?.text || app.description || "";
    kind.textContent = kindText(app);
    kind.hidden = !kind.textContent;
    icon.innerHTML = iconMarkup(app);
    icon.className = `app-icon ${app.kind}`;
    pill.textContent = developmentRestricted ? "Em desenvolvimento" : statusText(app.status);
    pill.className = `status-pill ${app.status}`;
    node.classList.toggle("is-restricted", restricted);
    node.toggleAttribute("aria-disabled", restricted);

    const warnings = [];
    if (app.apiOffline) warnings.push("API offline");
    if (app.id === "balanca" && !app.staticBuild && !app.devProxy) warnings.push("build ausente");
    if (warnings.length) {
      const warning = document.createElement("div");
      warning.className = "app-warning";
      warning.textContent = warnings.join(" - ");
      node.querySelector(".app-actions")?.before(warning);
    }
    if (restricted) {
      const stamp = document.createElement("div");
      stamp.className = "maintenance-stamp";
      stamp.textContent = developmentRestricted ? "EM DESENVOLVIMENTO" : "EM MANUTENCAO";
      stamp.setAttribute("aria-hidden", "true");
      node.querySelector(".app-actions")?.before(stamp);
    }
    buttonText.textContent = restricted
      ? "Indisponivel"
      : app.apiOffline
        ? "Iniciar API"
      : app.kind === "internal" && app.url ? "Acessar"
      : app.kind === "web" && app.running ? "Acessar web" : app.button;
    startButton.className = ((app.kind === "web" && app.running) || (app.kind === "internal" && app.url)) && !restricted && !app.apiOffline
      ? "start-button access-button"
      : "start-button";
    startButton.classList.toggle("is-off", restricted);
    startButton.disabled = !app.exists || restricted || app.status === "unknown";
    startButton.title = restricted
      ? restrictedMessage
      : app.status === "unknown" ? "Aguardando checagem do sistema." : "";

    startButton.addEventListener("click", () => startApp(app.id, startButton));

    tile.appendChild(node);

    grid.appendChild(tile);
  }
}

function mergeApps(apps) {
  if (!Array.isArray(apps) || apps.length === 0) {
    return [...fallbackApps];
  }
  return apps.map((app) => ({
    ...(fallbackApps.find((fallbackApp) => fallbackApp.id === app.id) || {}),
    ...app,
  }));
}

function canManagePortal() {
  return Boolean(currentUser?.canManagePortal);
}

async function fetchWithTimeout(url, options = {}, timeoutMs = 8000) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);

  try {
    return await fetch(url, {
      ...options,
      signal: controller.signal,
    });
  } finally {
    clearTimeout(timer);
  }
}

async function requestJson(url, options = {}, timeoutMs = 8000) {
  const response = await fetchWithTimeout(url, {
    ...options,
    headers: options.body ? { "Content-Type": "application/json", ...(options.headers || {}) } : options.headers,
  }, timeoutMs);
  const data = await response.json().catch(() => ({}));
  if (!response.ok || data.ok === false) {
    throw new Error(data.message || "Falha na opera\u00e7\u00e3o.");
  }
  return data;
}

function applyAdminVisibility() {
  const isAdmin = canManagePortal();
  if (adminToggle) adminToggle.hidden = !isAdmin;
  if (!isAdmin && adminPanel) {
    adminPanel.hidden = true;
    adminPanel.replaceChildren();
  }
}

function isAdminRoute() {
  return window.location.hash === "#/liberacoes" || window.location.hash === "#liberacoes";
}

function showLauncherView(show) {
  launcherViews.forEach((element) => {
    element.hidden = !show;
  });
}

async function loadAdminViewData(options = {}) {
  if (!canManagePortal()) return;
  if (adminDataLoaded && !options.force) return;
  if (adminDataRequest && !options.force) return adminDataRequest;
  adminDataRequest = (async () => {
    await loadUsers();
    await loadSystemHealth();
    await loadActivity();
    await loadBackups();
    adminDataLoaded = true;
  })();
  try {
    await adminDataRequest;
  } finally {
    adminDataRequest = null;
  }
}

async function syncRouteView() {
  const wantsAdmin = isAdminRoute();
  const isAdmin = canManagePortal();

  if (wantsAdmin && isAdmin) {
    document.body.classList.add("admin-route");
    showLauncherView(false);
    if (adminPanel) adminPanel.hidden = false;
    if (adminToggle) adminToggle.textContent = "Launcher";
    await loadAdminViewData();
    return;
  }

  if (wantsAdmin && currentUser && !isAdmin) {
    window.history.replaceState({}, "", window.location.pathname + window.location.search);
  }

  document.body.classList.remove("admin-route");
  showLauncherView(true);
  if (adminPanel) adminPanel.hidden = true;
  if (adminToggle) adminToggle.textContent = "Libera\u00e7\u00f5es";
}

async function loadSession() {
  const data = await requestJson("/api/session");
  if (!data.authenticated) {
    window.location.href = "/login.html";
    return;
  }
  currentUser = data.user;
  renderCurrentUser();
  applyAdminVisibility();
  showWelcomeIfNeeded();
  await syncRouteView();
}

function normalizeDisplayName(value) {
  return String(value || "").trim().replace(/\s+/g, " ");
}

function profileInitials(name) {
  const parts = normalizeDisplayName(name).split(" ").filter(Boolean);
  if (!parts.length) return "U";
  const selected = parts.length > 1 ? [parts[0], parts.at(-1)] : [parts[0]];
  return selected.map((part) => Array.from(part)[0] || "").join("").toLocaleUpperCase("pt-BR");
}

function profileProviderText(provider) {
  return provider === "local" ? "Conta local" : "Conta integrada";
}

function renderCurrentUser() {
  if (!currentUser) return;
  if (userName) userName.textContent = `${currentUser.name} (${currentUser.email})`;
  if (profileAvatar) profileAvatar.textContent = profileInitials(currentUser.name);
  if (profileName) profileName.value = currentUser.name || "";
  if (profileEmail) profileEmail.value = currentUser.email || "";
  if (profileAccountType) {
    profileAccountType.textContent = `${userRoleText(currentUser.role)} · ${profileProviderText(currentUser.provider)} · ${userStatusText(currentUser.status)}`;
  }
  const hasLocalPassword = currentUser.provider === "local";
  if (profileSecurity) profileSecurity.hidden = !hasLocalPassword;
  if (profileIntegratedPasswordNote) profileIntegratedPasswordNote.hidden = hasLocalPassword;
}

function setProfileMessage(message = "", kind = "success") {
  if (!profileMessage) return;
  profileMessage.textContent = message;
  profileMessage.dataset.kind = kind;
  profileMessage.hidden = !message;
}

function resetProfilePasswords() {
  for (const input of [profileCurrentPassword, profileNewPassword, profileConfirmPassword]) {
    if (!input) continue;
    input.value = "";
    input.type = "password";
  }
  profileDialog?.querySelectorAll("[data-profile-password-toggle]").forEach((button) => {
    button.textContent = "Mostrar";
    button.classList.remove("is-visible");
    const fieldLabels = {
      profileCurrentPassword: "senha atual",
      profileNewPassword: "nova senha",
      profileConfirmPassword: "confirmacao da senha",
    };
    button.setAttribute("aria-label", `Mostrar ${fieldLabels[button.dataset.profilePasswordToggle] || "senha"}`);
  });
}

function openProfileDialog() {
  if (!currentUser || !profileDialog) return;
  renderCurrentUser();
  resetProfilePasswords();
  setProfileMessage();
  document.body.classList.add("profile-open");
  if (!profileDialog.open) profileDialog.showModal();
  window.setTimeout(() => profileName?.focus(), 0);
}

function closeProfileDialog() {
  if (!profileDialog?.open) return;
  profileDialog.close();
}

function profileValidationError(message, input) {
  setProfileMessage(message, "error");
  input?.focus();
}

async function saveProfile(event) {
  event.preventDefault();
  if (!currentUser || !profileSubmit) return;

  const name = normalizeDisplayName(profileName?.value);
  const currentPassword = profileCurrentPassword?.value || "";
  const newPassword = profileNewPassword?.value || "";
  const confirmPassword = profileConfirmPassword?.value || "";
  const wantsPasswordChange = Boolean(currentPassword || newPassword || confirmPassword);

  if (name.length < 3 || name.length > 100) {
    profileValidationError("Informe um nome de apresentação entre 3 e 100 caracteres.", profileName);
    return;
  }
  if (wantsPasswordChange && !currentPassword) {
    profileValidationError("Informe sua senha atual para criar uma nova senha.", profileCurrentPassword);
    return;
  }
  if (wantsPasswordChange && (newPassword.length < 6 || newPassword.length > 128)) {
    profileValidationError("A nova senha precisa ter entre 6 e 128 caracteres.", profileNewPassword);
    return;
  }
  if (wantsPasswordChange && newPassword !== confirmPassword) {
    profileValidationError("A confirmação da nova senha não confere.", profileConfirmPassword);
    return;
  }

  const originalText = profileSubmit.textContent;
  profileSubmit.disabled = true;
  profileSubmit.textContent = "Salvando...";
  setProfileMessage();

  try {
    const payload = {};
    if (name !== normalizeDisplayName(currentUser.name)) payload.name = name;
    if (wantsPasswordChange) {
      payload.currentPassword = currentPassword;
      payload.newPassword = newPassword;
    }
    const data = await requestJson("/api/profile", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    currentUser = data.user;
    renderCurrentUser();
    resetProfilePasswords();
    adminDataLoaded = false;
    setProfileMessage(data.message || "Perfil atualizado com sucesso.");
  } catch (error) {
    setProfileMessage(error.message, "error");
  } finally {
    profileSubmit.disabled = false;
    profileSubmit.textContent = originalText;
  }
}

function firstName(name) {
  return String(name || "usuario").trim().split(/\s+/)[0] || "usuario";
}

function showWelcomeIfNeeded() {
  const params = new URLSearchParams(window.location.search);
  if (params.get("welcome") !== "1" || !welcomeScreen || !currentUser) return;
  if (welcomeName) welcomeName.textContent = firstName(currentUser.name);
  welcomeScreen.hidden = false;
  document.body.classList.add("welcome-open");
  welcomeContinue?.focus();
}

function closeWelcome() {
  if (welcomeScreen) welcomeScreen.hidden = true;
  document.body.classList.remove("welcome-open");
  const url = new URL(window.location.href);
  url.searchParams.delete("welcome");
  window.history.replaceState({}, "", `${url.pathname}${url.search}${url.hash}`);
}

async function loadStatus(options = {}) {
  const force = Boolean(options.force);
  if (statusRequest) return statusRequest;
  if (!force && Date.now() - lastStatusLoadAt < 1200) return;
  loadingStatus = true;

  statusRequest = (async () => {
    try {
      const response = await fetchWithTimeout("/api/status", { cache: "no-store" }, 12000);
      const data = await response.json();
      if (!data.ok) throw new Error(data.message || "Falha ao carregar status.");

      currentApps = mergeApps(data.apps);
      renderApps(currentApps);
      lastStatusLoadAt = Date.now();
    } catch (error) {
      renderApps(currentApps);
    } finally {
      loadingStatus = false;
      statusRequest = null;
    }
  })();

  return statusRequest;
}

function userStatusText(status) {
  return {
    approved: "Liberado",
    pending: "Pendente",
    blocked: "Bloqueado",
  }[status] || status;
}

function userRoleText(role) {
  return role === "admin" ? "Administrador" : "Usuario";
}

function userStatusClass(status) {
  return {
    approved: "approved",
    pending: "pending",
    blocked: "blocked",
  }[status] || "neutral";
}

function renderUsersSummary(users) {
  const counts = users.reduce((acc, user) => {
    acc.total += 1;
    acc[user.status] = (acc[user.status] || 0) + 1;
    if (user.role === "admin") acc.admins += 1;
    return acc;
  }, { total: 0, approved: 0, pending: 0, blocked: 0, admins: 0 });

  return `
    <div class="admin-user-summary" aria-label="Resumo de usuarios">
      <div class="admin-summary-card">
        <span>Total</span>
        <strong>${counts.total}</strong>
      </div>
      <div class="admin-summary-card">
        <span>Liberados</span>
        <strong>${counts.approved || 0}</strong>
      </div>
      <div class="admin-summary-card">
        <span>Pendentes</span>
        <strong>${counts.pending || 0}</strong>
      </div>
      <div class="admin-summary-card">
        <span>Bloqueados</span>
        <strong>${counts.blocked || 0}</strong>
      </div>
      <div class="admin-summary-card">
        <span>Admins</span>
        <strong>${counts.admins}</strong>
      </div>
    </div>
  `;
}

function permissionSummary(user, permissions) {
  if (user.canManagePortal) {
    return { label: "Acesso total", detail: "Por perfil admin", allowed: permissions.map((item) => item.name) };
  }
  const allowed = permissions.filter((permission) => permission.canAccess);
  return {
    label: `${allowed.length} de ${permissions.length || 0} sistemas`,
    detail: allowed.length ? allowed.map((item) => item.name).join(", ") : "Sem sistemas liberados",
    allowed: allowed.map((item) => item.name),
  };
}

function renderPermissionSummary(user, permissions) {
  const summary = permissionSummary(user, permissions);
  return `
    <div class="permission-summary">
      <span class="cell-label">Acessos</span>
      <strong>${escapeHtml(summary.label)}</strong>
      <small>${escapeHtml(summary.detail)}</small>
    </div>
  `;
}

function renderUserGroup(title, description, users) {
  const cards = users.length
    ? users.map(renderUserCard).join("")
    : `<div class="empty-users compact">Nenhum usuario nesta categoria.</div>`;

  return `
    <section class="admin-user-group">
      <div class="admin-user-group-head">
        <div>
          <span>Categoria</span>
          <h3>${escapeHtml(title)}</h3>
          <p>${escapeHtml(description)}</p>
        </div>
        <strong>${users.length} ${users.length === 1 ? "usuario" : "usuarios"}</strong>
      </div>
      <div class="admin-user-table-head" aria-hidden="true">
        <span>Nome</span>
        <span>Perfil</span>
        <span>Status</span>
        <span>Acessos</span>
        <span>Acao</span>
      </div>
      <div class="admin-user-list">${cards}</div>
    </section>
  `;
}

function formatDateTime(seconds) {
  if (!seconds) return "";
  return new Date(seconds * 1000).toLocaleString("pt-BR", {
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function renderUsers(users) {
  if (!usersList) return;
  if (!users.length) {
    usersList.innerHTML = `<div class="empty-users">Nenhum usuario cadastrado.</div>`;
    return;
  }

  const admins = users.filter((user) => user.role === "admin");
  const approved = users.filter((user) => user.role !== "admin" && user.status === "approved");
  const pending = users.filter((user) => user.role !== "admin" && user.status === "pending");
  const blocked = users.filter((user) => user.role !== "admin" && user.status === "blocked");

  usersList.innerHTML = `
    ${renderUsersSummary(users)}
    <div class="admin-user-groups">
      ${renderUserGroup("Administradores", "Contas com acesso total e controles protegidos.", admins)}
      ${renderUserGroup("Usuarios liberados", "Contas comuns aprovadas para uso conforme permissoes.", approved)}
      ${renderUserGroup("Pendentes", "Cadastros aguardando liberacao administrativa.", pending)}
      ${renderUserGroup("Bloqueados", "Contas sem acesso ativo ao portal.", blocked)}
    </div>
  `;
}

function renderUserCard(user) {
        const permissions = user.permissions || [];
        const permissionItems = permissions.length
          ? permissions.map((permission) => {
              const disabled = user.role === "admin" || permission.locked;
              const checked = permission.canAccess ? "checked" : "";
              const lockText = user.role === "admin"
                ? user.canManagePortal ? "Acesso total por perfil admin" : "Restrito pelo modo manutencao do portal"
                : permission.adminOnly
                  ? "Restrito ate permissao explicita"
                  : permission.hasExplicitPermission
                    ? "Permissao explicita"
                    : "Sem permissao explicita";
              return `
                <label class="permission-toggle-row" title="${escapeHtml(lockText)}">
                  <input
                    class="permission-toggle"
                    type="checkbox"
                    data-system-id="${escapeHtml(permission.id)}"
                    ${checked}
                    ${disabled ? "disabled" : ""}
                  >
                  <span>${escapeHtml(permission.name)}</span>
                </label>
              `;
            }).join("")
          : `<div class="empty-permissions">Nenhum sistema configurado.</div>`;
        const isCurrentUser = String(currentUser?.id || "") === String(user.id);
        const canDelete = user.role !== "admin" && !isCurrentUser;
        return `
        <details class="user-card" data-user-id="${user.id}">
          <summary class="user-row-summary">
            <div class="user-identity">
              <strong>${escapeHtml(user.name)}</strong>
              <span>${escapeHtml(user.email)}</span>
            </div>
            <div class="user-meta-cell">
              <span class="cell-label">Perfil</span>
              <strong>${userRoleText(user.role)}</strong>
            </div>
            <div class="user-meta-cell">
              <span class="cell-label">Status</span>
              <strong class="status-text status-${userStatusClass(user.status)}">${userStatusText(user.status)}</strong>
            </div>
            ${renderPermissionSummary(user, permissions)}
            <span class="user-expand-label">Gerenciar</span>
          </summary>
          <div class="user-card-details">
            <div class="user-permissions">
              <strong>Permissoes</strong>
              <div class="permission-toggle-list">${permissionItems}</div>
              ${user.role === "admin" ? `<small>${user.canManagePortal ? "Administradores com acesso completo veem todos os sistemas." : "Administrador restrito pelo modo manutencao do portal."}</small>` : `<button class="small-button save-user-permissions" type="button">Salvar permissoes</button>`}
            </div>
            <div class="user-password-editor">
              <label>
                Nova senha
                <span class="admin-password-field">
                  <input class="user-password-input" type="text" autocomplete="new-password" minlength="6" placeholder="Digite a nova senha">
                  <button class="small-button ghost toggle-user-password" type="button">Ocultar</button>
                </span>
              </label>
              <button class="small-button save-user-password" type="button">Salvar senha</button>
            </div>
            <div class="user-actions">
              ${user.status !== "approved" ? `<button class="small-button approve-user" type="button">Liberar</button>` : ""}
              ${user.role !== "admin" && user.status !== "blocked" ? `<button class="small-button ghost block-user" type="button">Bloquear</button>` : ""}
              ${canDelete ? `<button class="small-button danger delete-user" type="button">Excluir</button>` : ""}
            </div>
          </div>
        </details>
      `;
}

async function loadUsers() {
  const data = await requestJson("/api/admin/users", {}, 6000);
  adminSystems = data.systems || [];
  renderUsers(data.users || []);
}

function healthStateClass(ok) {
  return ok ? "ok" : "error";
}

function renderSystemHealth(health) {
  if (!systemHealthStatus) return;
  const apps = health?.apps || [];
  const databases = health?.databases || [];
  const backup = health?.backup || {};
  const summary = health?.summary || {};
  systemHealthStatus.innerHTML = `
    <div class="system-health-grid">
      <article class="system-health-card">
        <span>Sistemas online</span>
        <strong>${escapeHtml(summary.appsOnline ?? 0)} de ${escapeHtml(summary.appsTotal ?? apps.length)}</strong>
        <small>Checado em ${formatDateTime(health?.checkedAt)}</small>
      </article>
      <article class="system-health-card">
        <span>Bancos verificados</span>
        <strong>${escapeHtml(summary.databasesOk ?? 0)} de ${escapeHtml(summary.databasesTotal ?? databases.length)}</strong>
        <small>Integridade SQLite</small>
      </article>
      <article class="system-health-card">
        <span>Backup</span>
        <strong>${backup.running ? "Executando" : summary.backupOk ? "Ativo" : "Atencao"}</strong>
        <small>${escapeHtml(backup.latest?.name || backup.lastMessage || "Nenhum backup criado.")}</small>
      </article>
    </div>
    <div class="system-health-columns">
      <article class="system-health-card">
        <span>Portais</span>
        <div class="health-list">
          ${apps.map((app) => `
            <div class="health-row">
              <div>
                <strong>${escapeHtml(app.name)}</strong>
                <small>Web ${escapeHtml(app.webPort || "-")}${app.apiPort ? ` - API ${escapeHtml(app.apiPort)}` : ""}</small>
              </div>
              <em class="health-state ${healthStateClass(app.status === "online")}">${escapeHtml(app.status)}</em>
            </div>
            ${app.health?.message ? `<p class="health-note">${escapeHtml(app.health.message)}</p>` : ""}
          `).join("")}
        </div>
      </article>
      <article class="system-health-card">
        <span>Bancos de dados</span>
        <div class="health-list">
          ${databases.map((db) => `
            <div class="health-row">
              <div>
                <strong>${escapeHtml(db.label)}</strong>
                <small>${escapeHtml(formatFileSize(db.size))} - ${db.modifiedAt ? escapeHtml(formatDateTime(db.modifiedAt)) : "nao encontrado"}</small>
              </div>
              <em class="health-state ${healthStateClass(db.ok)}">${escapeHtml(db.integrity)}</em>
            </div>
          `).join("")}
        </div>
      </article>
      <article class="system-health-card system-health-card-wide">
        <span>Logs recentes</span>
        ${apps.map((app) => `
          <details class="health-log">
            <summary>${escapeHtml(app.name)}</summary>
            <pre>${escapeHtml((app.log || []).join("\n") || "Sem linhas recentes.")}</pre>
          </details>
        `).join("")}
      </article>
    </div>
  `;
}

async function loadSystemHealth() {
  if (currentUser?.role !== "admin") return;
  if (systemHealthStatus) systemHealthStatus.innerHTML = `<div class="empty-users">Verificando sistemas...</div>`;
  try {
    const data = await requestJson("/api/admin/health", {}, 20000);
    renderSystemHealth(data.health || {});
  } catch (error) {
    if (systemHealthStatus) systemHealthStatus.innerHTML = `<div class="empty-users">${escapeHtml(error.message)}</div>`;
  }
}

function activityQueryString() {
  const params = new URLSearchParams();
  if (activityUser?.value) params.set("user", activityUser.value);
  if (activityModule?.value) params.set("module", activityModule.value);
  if (activityEventType?.value) params.set("eventType", activityEventType.value);
  if (activityStart?.value) params.set("start", activityStart.value);
  if (activityEnd?.value) params.set("end", activityEnd.value);
  if (activitySearch?.value.trim()) params.set("q", activitySearch.value.trim());
  params.set("limit", "400");
  return params;
}

function setSelectOptions(select, options, currentValue, formatter) {
  if (!select) return;
  const base = select.querySelector("option[value='']")?.textContent || "Todos";
  select.innerHTML = `<option value="">${escapeHtml(base)}</option>`;
  for (const option of options || []) {
    const item = document.createElement("option");
    const formatted = formatter(option);
    item.value = formatted.value;
    item.textContent = formatted.label;
    select.appendChild(item);
  }
  select.value = currentValue || "";
}

function renderActivityFilters(filters) {
  if (!filters) return;
  setSelectOptions(activityUser, filters.users, activityUser?.value, (user) => ({
    value: user.value,
    label: `${user.name}${user.email ? ` - ${user.email}` : ""}`,
  }));
  setSelectOptions(activityModule, filters.modules, activityModule?.value, (item) => ({
    value: item.module,
    label: moduleLabels[item.module] || item.module,
  }));
  setSelectOptions(activityEventType, filters.eventTypes, activityEventType?.value, (item) => ({
    value: item.eventType,
    label: eventLabels[item.eventType] || item.eventType,
  }));
}

function renderActivitySummary(data) {
  if (!activitySummary) return;
  const total = data.total || 0;
  const returned = data.returned || 0;
  const summary = data.summary || {};
  activitySummary.innerHTML = `
    <div>
      <span>Registros</span>
      <strong>${returned} de ${total}</strong>
    </div>
    <div>
      <span>Usuarios</span>
      <strong>${summary.users || 0}</strong>
    </div>
    <div>
      <span>Sistemas</span>
      <strong>${summary.modules || 0}</strong>
    </div>
  `;
}

function renderActivity(groups) {
  if (!activityList) return;
  activityList.innerHTML = groups.length
    ? groups.map((group) => `
        <article class="activity-card">
          <div class="activity-user">
            <div>
              <strong>${escapeHtml(group.userName)}</strong>
              <span>${escapeHtml(group.userEmail || "Sem e-mail")}</span>
            </div>
            <small>${group.total} registros - ultimo ${formatDateTime(group.lastAt)}</small>
          </div>
          <div class="activity-events">
            ${group.events.map((event) => `
              <div class="activity-event">
                <span>${escapeHtml(moduleLabels[event.module] || event.module)} - ${escapeHtml(eventLabels[event.eventType] || event.eventType)}</span>
                <strong>${escapeHtml(event.summary)}</strong>
                <small>${formatDateTime(event.createdAt)}${event.entityType ? ` - ${escapeHtml(event.entityType)} ${escapeHtml(event.entityId || "")}` : ""}</small>
              </div>
            `).join("")}
          </div>
        </article>
      `).join("")
    : `<div class="empty-users">Nenhuma atividade registrada.</div>`;
}

async function loadActivity() {
  const params = activityQueryString();
  const data = await requestJson(`/api/admin/activity?${params.toString()}`, {}, 9000);
  renderActivityFilters(data.filters);
  renderActivitySummary(data);
  renderActivity(data.groups || []);
}

function formatFileSize(bytes) {
  const value = Number(bytes || 0);
  if (value >= 1024 * 1024 * 1024) return `${(value / 1024 / 1024 / 1024).toFixed(2)} GB`;
  if (value >= 1024 * 1024) return `${(value / 1024 / 1024).toFixed(2)} MB`;
  if (value >= 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${value} B`;
}

function formatInterval(seconds) {
  const value = Number(seconds || 0);
  const hours = Math.round(value / 3600);
  if (hours >= 1) return `${hours}h`;
  const minutes = Math.max(1, Math.round(value / 60));
  return `${minutes}min`;
}

function renderBackupStatus(backup) {
  if (!backupStatus) return;
  const files = backup?.files || [];
  const latest = files[0];
  const stateText = backup?.running ? "Executando" : backup?.lastError ? "Falha" : "Ativo";
  const stateClass = backup?.running ? "running" : backup?.lastError ? "error" : "ok";
  backupStatus.innerHTML = `
    <article class="backup-card">
      <div class="backup-main">
        <div>
          <span class="backup-label">Status</span>
          <strong class="backup-state ${stateClass}">${stateText}</strong>
          <small>${escapeHtml(backup?.lastMessage || "Backup ainda nao executado.")}</small>
        </div>
        <div>
          <span class="backup-label">Intervalo</span>
          <strong>${formatInterval(backup?.intervalSeconds)}</strong>
          <small>Mantem ${escapeHtml(backup?.keepFiles || 1)} arquivo${Number(backup?.keepFiles || 1) > 1 ? "s" : ""}</small>
        </div>
        <div>
          <span class="backup-label">Ultimo arquivo</span>
          <strong>${latest ? escapeHtml(latest.name) : "Nenhum"}</strong>
          <small>${latest ? `${formatFileSize(latest.size)} - ${formatDateTime(latest.createdAt)}` : "Sera criado automaticamente."}</small>
        </div>
      </div>
      <div class="backup-path">
        <span>Pasta sincronizada</span>
        <code>${escapeHtml(backup?.dir || "")}</code>
      </div>
      <div class="backup-files">
        <span class="backup-label">Versoes disponiveis</span>
        ${files.length ? files.map((file) => `
          <div class="backup-file" data-backup-name="${escapeHtml(file.name)}">
            <div>
              <strong>${escapeHtml(file.name)}</strong>
              <small>${formatFileSize(file.size)} - ${formatDateTime(file.createdAt)}</small>
            </div>
            <div class="backup-file-actions">
              <button class="small-button ghost verify-backup" type="button">Verificar</button>
              <button class="small-button ghost prepare-restore" type="button">Preparar restauracao</button>
            </div>
          </div>
        `).join("") : `<div class="empty-users">Nenhum backup criado.</div>`}
      </div>
      ${backup?.lastError ? `<p class="backup-error">${escapeHtml(backup.lastError)}</p>` : ""}
    </article>
  `;
}

async function loadBackups() {
  const data = await requestJson("/api/admin/backups", {}, 8000);
  renderBackupStatus(data.backup || {});
}

function delay(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function openWebWhenReady(appId, attempts = 35) {
  for (let attempt = 0; attempt < attempts; attempt += 1) {
    await delay(attempt === 0 ? 800 : 1500);
    await loadStatus({ force: true });
    const app = currentApps.find((item) => item.id === appId);
    if (app?.kind === "web" && app.running && app.url && !app.apiOffline) {
      window.location.href = app.url;
      return true;
    }
  }
  return false;
}

async function startApp(appId, button) {
  const app = currentApps.find((item) => item.id === appId);
  if (app?.kind === "internal" && app.url) {
    window.location.href = app.url;
    return;
  }
  if (app?.kind === "web" && app.running && app.url && !app.apiOffline) {
    window.location.href = app.url;
    return;
  }

  const buttonText = button.querySelector(".button-text");
  const originalText = buttonText?.textContent || button.textContent;
  button.disabled = true;
  if (buttonText) buttonText.textContent = "Iniciando...";

  try {
    const response = await fetchWithTimeout(`/api/start/${appId}`, { method: "POST" }, 25000);
    const data = await response.json();
    if (!data.ok) throw new Error(data.message || "Nao foi possivel iniciar.");

    if (buttonText) buttonText.textContent = "Comando enviado";
    if (app?.kind === "web") {
      if (buttonText) buttonText.textContent = "Abrindo...";
      const opened = await openWebWhenReady(appId);
      if (!opened) {
        alert("Servidor iniciado, mas ainda nao respondeu. Clique novamente em alguns segundos.");
      }
    } else {
      setTimeout(loadStatus, 1500);
    }
  } catch (error) {
    alert(error.message);
    if (buttonText) buttonText.textContent = originalText;
  } finally {
    setTimeout(() => {
      button.disabled = false;
      if (buttonText) buttonText.textContent = originalText;
    }, 1800);
  }
}

renderApps(currentApps);
loadSession().then(() => loadStatus({ force: true })).catch(() => {
  window.location.href = "/login.html";
});
setInterval(loadStatus, 10000);

logoutButton?.addEventListener("click", async () => {
  await requestJson("/api/logout", { method: "POST" }).catch(() => null);
  window.location.href = "/login.html";
});

profileToggle?.addEventListener("click", openProfileDialog);
profileClose?.addEventListener("click", closeProfileDialog);
profileCancel?.addEventListener("click", closeProfileDialog);
profileForm?.addEventListener("submit", saveProfile);

profileDialog?.addEventListener("close", () => {
  document.body.classList.remove("profile-open");
  resetProfilePasswords();
  setProfileMessage();
  profileToggle?.focus();
});

profileDialog?.addEventListener("click", (event) => {
  const toggle = event.target.closest?.("[data-profile-password-toggle]");
  if (toggle) {
    const input = document.querySelector(`#${toggle.dataset.profilePasswordToggle}`);
    if (!input) return;
    const showing = input.type === "password";
    input.type = showing ? "text" : "password";
    toggle.textContent = showing ? "Ocultar" : "Mostrar";
    toggle.classList.toggle("is-visible", showing);
    toggle.setAttribute("aria-label", `${showing ? "Ocultar" : "Mostrar"} senha`);
    return;
  }
  if (event.target === profileDialog) closeProfileDialog();
});

welcomeContinue?.addEventListener("click", closeWelcome);

window.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && welcomeScreen && !welcomeScreen.hidden) {
    closeWelcome();
  }
});

adminToggle?.addEventListener("click", async () => {
  if (!canManagePortal()) return;
  if (isAdminRoute()) {
    window.location.hash = "";
    await syncRouteView();
    return;
  }
  window.location.hash = "/liberacoes";
  await syncRouteView();
});

backToLauncher?.addEventListener("click", async () => {
  window.location.hash = "";
  await syncRouteView();
});

window.addEventListener("hashchange", () => {
  syncRouteView().catch(() => undefined);
});

refreshUsers?.addEventListener("click", loadUsers);
refreshSystemHealth?.addEventListener("click", loadSystemHealth);
refreshActivity?.addEventListener("click", loadActivity);
activityFilters?.addEventListener("submit", async (event) => {
  event.preventDefault();
  await loadActivity();
});
exportActivity?.addEventListener("click", () => {
  const params = activityQueryString();
  params.delete("limit");
  window.location.href = `/api/admin/activity/export?${params.toString()}`;
});
backupNow?.addEventListener("click", async () => {
  const originalText = backupNow.textContent;
  backupNow.disabled = true;
  backupNow.textContent = "Criando...";
  try {
    const data = await requestJson("/api/admin/backups/create", { method: "POST" }, 60000);
    renderBackupStatus({
      ...(data.backup || {}),
      lastMessage: data.message || "Backup criado.",
    });
    await loadBackups();
    await loadActivity();
  } catch (error) {
    alert(error.message);
    await loadBackups().catch(() => null);
  } finally {
    backupNow.disabled = false;
    backupNow.textContent = originalText;
  }
});

backupStatus?.addEventListener("click", async (event) => {
  const button = event.target.closest("button");
  const card = event.target.closest("[data-backup-name]");
  if (!button || !card) return;
  const name = card.dataset.backupName;
  if (!name) return;

  button.disabled = true;
  const originalText = button.textContent;
  try {
    if (button.classList.contains("verify-backup")) {
      button.textContent = "Verificando...";
      const result = await requestJson("/api/admin/backups/verify", {
        method: "POST",
        body: JSON.stringify({ name }),
      }, 30000);
      alert(`${result.message}\nBancos verificados: ${result.databases?.length || 0}`);
    }
    if (button.classList.contains("prepare-restore")) {
      const confirmed = confirm("Preparar restauracao nao altera o sistema agora. Ele apenas extrai o backup e cria instrucoes. Continuar?");
      if (!confirmed) return;
      button.textContent = "Preparando...";
      const result = await requestJson("/api/admin/backups/prepare-restore", {
        method: "POST",
        body: JSON.stringify({ name }),
      }, 60000);
      alert(`${result.message}\nPasta: ${result.restorePath}`);
    }
    await loadBackups();
    await loadActivity();
  } catch (error) {
    alert(error.message);
  } finally {
    button.disabled = false;
    button.textContent = originalText;
  }
});

usersList?.addEventListener("click", async (event) => {
  const card = event.target.closest("[data-user-id]");
  if (!card) return;
  const userId = card.dataset.userId;
  const passwordInput = card.querySelector(".user-password-input");
  const togglePassword = event.target.closest(".toggle-user-password");
  if (togglePassword && passwordInput) {
    const show = passwordInput.type === "password";
    passwordInput.type = show ? "text" : "password";
    togglePassword.textContent = show ? "Ocultar" : "Mostrar";
    return;
  }

  const savePassword = event.target.closest(".save-user-password");
  if (savePassword && passwordInput) {
    const password = passwordInput.value;
    if (password.length < 6) {
      alert("A senha precisa ter pelo menos 6 caracteres.");
      passwordInput.focus();
      return;
    }

    const originalText = savePassword.textContent;
    savePassword.disabled = true;
    savePassword.textContent = "Salvando...";
    try {
      await requestJson(`/api/admin/users/${userId}/password`, {
        method: "POST",
        body: JSON.stringify({ password }),
      });
      passwordInput.value = "";
      await loadActivity();
      alert("Senha atualizada.");
    } catch (error) {
      alert(error.message);
    } finally {
      savePassword.disabled = false;
      savePassword.textContent = originalText;
    }
    return;
  }

  const savePermissions = event.target.closest(".save-user-permissions");
  if (savePermissions) {
    const permissions = {};
    card.querySelectorAll(".permission-toggle").forEach((input) => {
      if (!input.disabled) {
        permissions[input.dataset.systemId] = input.checked;
      }
    });
    const originalText = savePermissions.textContent;
    savePermissions.disabled = true;
    savePermissions.textContent = "Salvando...";
    try {
      await requestJson(`/api/admin/users/${userId}/permissions`, {
        method: "POST",
        body: JSON.stringify({ permissions }),
      });
      await loadUsers();
      await loadActivity();
      alert("Permissoes atualizadas.");
    } catch (error) {
      alert(error.message);
    } finally {
      savePermissions.disabled = false;
      savePermissions.textContent = originalText;
    }
    return;
  }

  const deleteUser = event.target.closest(".delete-user");
  if (deleteUser) {
    const targetName = card.querySelector(".user-identity strong")?.textContent || "este usuario";
    const confirmed = confirm(`Excluir ${targetName}? Esta acao remove o usuario, encerra sessoes e apaga permissoes dele. A auditoria historica permanece registrada.`);
    if (!confirmed) return;
    const originalText = deleteUser.textContent;
    deleteUser.disabled = true;
    deleteUser.textContent = "Excluindo...";
    try {
      await requestJson(`/api/admin/users/${userId}?action=delete`, { method: "POST" });
      await loadUsers();
      await loadActivity();
      alert("Usuario excluido.");
    } catch (error) {
      alert(error.message);
    } finally {
      deleteUser.disabled = false;
      deleteUser.textContent = originalText;
    }
    return;
  }

  const action = event.target.closest(".approve-user") ? "approve" : event.target.closest(".block-user") ? "block" : "";
  if (!action) return;
  await requestJson(`/api/admin/users/${userId}?action=${action}`, { method: "POST" });
  await loadUsers();
  await loadActivity();
});
