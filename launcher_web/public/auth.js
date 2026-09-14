const message = document.querySelector("#authMessage");
const loginForm = document.querySelector("#loginForm");
const registerForm = document.querySelector("#registerForm");
const forgotPassword = document.querySelector("#forgotPassword");

function showMessage(text, tone = "info") {
  message.hidden = false;
  message.textContent = text;
  message.classList.toggle("error", tone === "error");
  message.dataset.tone = tone;
}

async function requestJson(url, options = {}) {
  const response = await fetch(url, {
    ...options,
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok || data.ok === false) {
    throw new Error(data.message || "Falha na opera\u00e7\u00e3o.");
  }
  return data;
}

document.querySelectorAll("[data-auth-tab]").forEach((button) => {
  button.addEventListener("click", () => {
    const tab = button.dataset.authTab;
    document.querySelectorAll("[data-auth-tab]").forEach((item) => item.classList.toggle("active", item === button));
    loginForm.classList.toggle("active", tab === "login");
    registerForm.classList.toggle("active", tab === "register");
  });
});

document.querySelectorAll("[data-password-toggle]").forEach((button) => {
  button.addEventListener("click", () => {
    const input = button.closest(".password-field")?.querySelector("input");
    if (!input) return;
    const showing = input.type === "password";
    input.type = showing ? "text" : "password";
    button.classList.toggle("is-visible", showing);
    button.setAttribute("aria-label", showing ? "Ocultar senha" : "Mostrar senha");
    button.setAttribute("title", showing ? "Ocultar senha" : "Mostrar senha");
  });
});

forgotPassword?.addEventListener("click", () => {
  showMessage("Para redefinir sua senha, solicite ao administrador do portal a troca do acesso.", "info");
});

loginForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const payload = Object.fromEntries(new FormData(loginForm).entries());
  try {
    await requestJson("/api/login", { method: "POST", body: JSON.stringify(payload) });
    window.location.href = "/?welcome=1";
  } catch (error) {
    showMessage(error.message, "error");
  }
});

registerForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const payload = Object.fromEntries(new FormData(registerForm).entries());
  try {
    const data = await requestJson("/api/register", { method: "POST", body: JSON.stringify(payload) });
    registerForm.reset();
    showMessage(data.message || "Cadastro enviado. Aguarde libera\u00e7\u00e3o.", "success");
  } catch (error) {
    showMessage(error.message, "error");
  }
});

async function boot() {
  const params = new URLSearchParams(window.location.search);
  if (params.get("pending")) showMessage("Cadastro recebido. Aguarde libera\u00e7\u00e3o do administrador.", "info");

  try {
    const session = await requestJson("/api/session");
    if (session.authenticated) {
      window.location.href = "/";
      return;
    }
  } catch {}
}

boot();
