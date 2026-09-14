const browserHost =
  window.location.protocol.startsWith("http") && window.location.hostname ? window.location.hostname : "localhost";
const browserProtocol = window.location.protocol === "https:" ? "https:" : "http:";
const portalApiUrl = window.location.port === "8890" || window.location.pathname.startsWith("/balanca")
  ? "/balanca-api"
  : null;

export const API_URL = import.meta.env.VITE_API_URL ?? portalApiUrl ?? `${browserProtocol}//${browserHost}:8833`;
export const authExpiredEvent = "balanca:auth-expired";

export class ApiError extends Error {
  constructor(
    message: string,
    public readonly status: number
  ) {
    super(message);
  }
}

export type TransferProgress = {
  loaded: number;
  total?: number;
  percent?: number;
};

type FormProgressHandlers = {
  onUploadProgress?: (progress: TransferProgress) => void;
  onDownloadProgress?: (progress: TransferProgress) => void;
};

export async function apiRequest<T>(path: string, token: string | null, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers);

  if (!(options.body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
  }

  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }

  const response = await fetchWithTimeout(`${API_URL}${path}`, {
    ...options,
    headers,
    credentials: "include"
  }, 30_000);

  if (!response.ok) {
    const payload = await response.json().catch(() => undefined);
    throw responseError(response.status, payload?.message ?? "Falha na requisicao.");
  }

  if (response.status === 204) {
    return undefined as T;
  }

  const text = await response.text();

  if (!text) {
    return undefined as T;
  }

  return JSON.parse(text) as T;
}

export function queryString(filters: Record<string, string | undefined>) {
  const query = new URLSearchParams();

  for (const [key, value] of Object.entries(filters)) {
    if (value) {
      query.set(key, value);
    }
  }

  const text = query.toString();
  return text ? `?${text}` : "";
}

export async function downloadCsv(path: string, token: string, fileName: string) {
  return downloadFile(path, token, fileName);
}

export async function fetchFileBlob(path: string, token: string) {
  const response = await fetchWithTimeout(`${API_URL}${path}`, {
    credentials: "include",
    headers: {
      Authorization: `Bearer ${token}`
    }
  }, 120_000);

  if (!response.ok) {
    const payload = await response.json().catch(() => undefined);
    throw responseError(response.status, payload?.message ?? "Falha ao carregar arquivo.");
  }

  return {
    blob: await response.blob(),
    fileName: extractDownloadFileName(response.headers.get("content-disposition")) ?? undefined
  };
}

export async function downloadFile(path: string, token: string, fileName: string) {
  const response = await fetchWithTimeout(`${API_URL}${path}`, {
    credentials: "include",
    headers: {
      Authorization: `Bearer ${token}`
    }
  }, 120_000);

  if (!response.ok) {
    const payload = await response.json().catch(() => undefined);
    throw responseError(response.status, payload?.message ?? "Falha ao exportar arquivo.");
  }

  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = extractDownloadFileName(response.headers.get("content-disposition")) ?? fileName;
  link.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 1_000);
}

export async function downloadFormFile(path: string, token: string, body: FormData, fallbackFileName: string) {
  return downloadFormFileWithProgress(path, token, body, fallbackFileName);
}

export async function postFormJson<T>(
  path: string,
  token: string,
  body: FormData,
  handlers: Pick<FormProgressHandlers, "onUploadProgress"> = {}
): Promise<T> {
  const response = await sendFormRequest<string>(path, token, body, "text", handlers);
  return JSON.parse(response.body) as T;
}

export async function importExcelFile<T>(path: string, token: string, file: File): Promise<T> {
  const body = new FormData();
  body.append("file", file);
  return postFormJson<T>(path, token, body);
}

export async function downloadFormFileWithProgress(
  path: string,
  token: string,
  body: FormData,
  fallbackFileName: string,
  handlers: FormProgressHandlers = {}
) {
  const response = await sendFormRequest<Blob>(path, token, body, "blob", handlers);
  const blob = response.body;
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = extractDownloadFileName(response.headers["content-disposition"] ?? null) ?? fallbackFileName;
  link.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 1_000);
}

function sendFormRequest<T extends Blob | string>(
  path: string,
  token: string,
  body: FormData,
  responseType: "blob" | "text",
  handlers: FormProgressHandlers
): Promise<{ body: T; headers: Record<string, string> }> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${API_URL}${path}`);
    xhr.responseType = responseType;
    xhr.withCredentials = true;
    xhr.timeout = 15 * 60_000;
    xhr.setRequestHeader("Authorization", `Bearer ${token}`);

    xhr.upload.onprogress = (event) => {
      handlers.onUploadProgress?.(toTransferProgress(event));
    };
    xhr.onprogress = (event) => {
      handlers.onDownloadProgress?.(toTransferProgress(event));
    };
    xhr.onerror = () => reject(new ApiError("Falha de conexao com o servidor.", 0));
    xhr.ontimeout = () => reject(new ApiError("A operacao excedeu 15 minutos e foi cancelada.", 0));
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve({
          body: xhr.response as T,
          headers: parseRawHeaders(xhr.getAllResponseHeaders())
        });
        return;
      }

      void parseXhrError(xhr).then(reject);
    };

    xhr.send(body);
  });
}

function toTransferProgress(event: ProgressEvent<EventTarget>): TransferProgress {
  return {
    loaded: event.loaded,
    total: event.lengthComputable ? event.total : undefined,
    percent: event.lengthComputable && event.total > 0 ? Math.round((event.loaded / event.total) * 100) : undefined
  };
}

function parseRawHeaders(rawHeaders: string) {
  const headers: Record<string, string> = {};

  for (const line of rawHeaders.trim().split(/[\r\n]+/)) {
    const separator = line.indexOf(":");

    if (separator <= 0) {
      continue;
    }

    headers[line.slice(0, separator).trim().toLowerCase()] = line.slice(separator + 1).trim();
  }

  return headers;
}

async function parseXhrError(xhr: XMLHttpRequest) {
  const fallback = xhr.responseType === "blob" ? "Falha ao exportar arquivo." : "Falha na requisicao.";
  let text = "";

  if (xhr.response instanceof Blob) {
    text = await xhr.response.text().catch(() => "");
  } else if (typeof xhr.responseText === "string") {
    text = xhr.responseText;
  }

  const payload = text ? tryParseJson<{ message?: string }>(text) : undefined;
  return responseError(xhr.status, payload?.message ?? fallback);
}

function tryParseJson<T>(text: string): T | undefined {
  try {
    return JSON.parse(text) as T;
  } catch {
    return undefined;
  }
}

export async function openFile(path: string, token: string) {
  const previewWindow = window.open("about:blank", "_blank");
  const response = await fetchWithTimeout(`${API_URL}${path}`, {
    credentials: "include",
    headers: {
      Authorization: `Bearer ${token}`
    }
  }, 120_000);

  if (!response.ok) {
    previewWindow?.close();
    const payload = await response.json().catch(() => undefined);
    throw responseError(response.status, payload?.message ?? "Falha ao abrir arquivo.");
  }

  const blob = await response.blob();
  const url = URL.createObjectURL(blob);

  if (previewWindow) {
    previewWindow.location.href = url;
  } else {
    const link = document.createElement("a");
    link.href = url;
    link.target = "_blank";
    link.rel = "noopener";
    link.click();
  }

  window.setTimeout(() => URL.revokeObjectURL(url), 60_000);
}

export async function createObjectUrl(path: string, token: string) {
  const response = await fetchWithTimeout(`${API_URL}${path}`, {
    credentials: "include",
    headers: {
      Authorization: `Bearer ${token}`
    }
  }, 60_000);

  if (!response.ok) {
    const payload = await response.json().catch(() => undefined);
    throw responseError(response.status, payload?.message ?? "Falha ao carregar arquivo.");
  }

  return URL.createObjectURL(await response.blob());
}

function responseError(status: number, message: string) {
  if (status === 401) {
    localStorage.removeItem("balanca.token");
    localStorage.removeItem("balanca.user");
    window.dispatchEvent(new CustomEvent(authExpiredEvent, { detail: { message } }));
  }

  return new ApiError(message, status);
}

async function fetchWithTimeout(input: RequestInfo | URL, init: RequestInit = {}, timeoutMs: number) {
  const controller = new AbortController();
  const externalSignal = init.signal;
  const abortFromCaller = () => controller.abort(externalSignal?.reason);

  if (externalSignal?.aborted) {
    abortFromCaller();
  } else {
    externalSignal?.addEventListener("abort", abortFromCaller, { once: true });
  }

  const timer = window.setTimeout(() => controller.abort(new DOMException("Timeout", "TimeoutError")), timeoutMs);

  try {
    return await fetch(input, { ...init, signal: controller.signal });
  } catch (error) {
    if (controller.signal.aborted && !externalSignal?.aborted) {
      throw new ApiError(`O servidor nao respondeu em ${Math.round(timeoutMs / 1000)} segundos.`, 0);
    }
    throw error;
  } finally {
    window.clearTimeout(timer);
    externalSignal?.removeEventListener("abort", abortFromCaller);
  }
}

function extractDownloadFileName(disposition: string | null) {
  if (!disposition) {
    return null;
  }

  const encodedMatch = /filename\*=UTF-8''(?<fileName>[^;]+)/i.exec(disposition);

  if (encodedMatch?.groups?.fileName) {
    return decodeURIComponent(encodedMatch.groups.fileName);
  }

  const match = /filename="?(?<fileName>[^";]+)"?/i.exec(disposition);
  return match?.groups?.fileName ?? null;
}
