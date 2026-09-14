import { execFile } from "node:child_process";
import { randomUUID } from "node:crypto";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { promisify } from "node:util";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const pdfParse = require("pdf-parse");

const execFileAsync = promisify(execFile);
const GOOGLE_VISION_ANNOTATE_URL = "https://vision.googleapis.com/v1/images:annotate";
const GEMINI_GENERATE_CONTENT_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models";
const DEFAULT_GEMINI_MODEL = "gemini-3.5-flash";

type AssistProvider = "off" | "google-vision" | "gemini" | "hybrid";

type GoogleVisionResponse = {
  responses?: Array<{
    fullTextAnnotation?: { text?: string };
    textAnnotations?: Array<{ description?: string }>;
    error?: { message?: string };
  }>;
};

type GeminiResponse = {
  candidates?: Array<{ content?: { parts?: Array<{ text?: string }> } }>;
};

export type GeminiCanePdfRow = {
  originCode: string;
  supplierCode: string;
  farm: string;
  field: string;
  netWeight: number;
  tripCount: number;
};

export type GeminiCanePdfExtraction = {
  reportDate?: string;
  periodStart?: string;
  periodEnd?: string;
  totalNetWeight?: number;
  totalTrips?: number;
  rows: GeminiCanePdfRow[];
};

export type CanePdfAssistCandidates = {
  googleVisionText?: string;
  geminiExtraction?: GeminiCanePdfExtraction;
};

type UsageState = {
  month: string;
  used: number;
  limit: number;
  updatedAt: string;
};

let visionUsageQueue: Promise<unknown> = Promise.resolve();
let geminiUsageQueue: Promise<unknown> = Promise.resolve();

export async function extractCanePdfAssistCandidates(filePath: string): Promise<CanePdfAssistCandidates> {
  const provider = resolveAssistProvider();

  if (provider === "off") {
    return {};
  }

  const isPdf = path.extname(filePath).toLowerCase() === ".pdf";

  let nativeExtraction: GeminiCanePdfExtraction | undefined;

  if (isPdf) {
    nativeExtraction = await extractNativePdfText(filePath);
  }

  const [googleVisionText, geminiExtraction] = await Promise.all([
    provider === "google-vision" || provider === "hybrid" ? extractWithGoogleVision(filePath) : Promise.resolve(undefined),
    nativeExtraction
      ? Promise.resolve(nativeExtraction)
      : (provider === "gemini" || provider === "hybrid" ? extractWithGemini(filePath) : Promise.resolve(undefined))
  ]);

  return { googleVisionText, geminiExtraction };
}

async function extractNativePdfText(filePath: string): Promise<GeminiCanePdfExtraction | undefined> {
  try {
    const pythonScriptPath = path.join(process.cwd(), "src", "services", "extractors", "cane_pdfplumber.py");
    const { stdout } = await execFileAsync("python", [pythonScriptPath, filePath], {
      maxBuffer: 10 * 1024 * 1024
    });

    const parsed = JSON.parse(stdout);

    if (parsed.error) {
      console.error("Python pdfplumber error:", parsed.error);
      return undefined;
    }

    if (parsed.rows && parsed.rows.length > 0) {
      return {
        reportDate: parsed.reportDate,
        periodStart: parsed.periodStart,
        periodEnd: parsed.periodEnd,
        totalNetWeight: parsed.totalNetWeight,
        totalTrips: parsed.totalTrips,
        rows: parsed.rows
      };
    }

    return undefined;
  } catch (error) {
    console.error("Failed to execute python pdfplumber:", error);
    return undefined;
  }
}

function resolveAssistProvider(): AssistProvider {
  const configured = (process.env.CANE_PDF_ASSIST_PROVIDER ?? "auto").trim().toLowerCase();

  if (["0", "off", "false", "none", "local"].includes(configured)) {
    return "off";
  }

  if (["google", "google-vision", "vision"].includes(configured)) {
    return readGoogleVisionApiKey() ? "google-vision" : "off";
  }

  if (["gemini", "ai", "ia"].includes(configured)) {
    return readGeminiApiKey() ? "gemini" : "off";
  }

  const hasVision = Boolean(readGoogleVisionApiKey());
  const hasGemini = Boolean(readGeminiApiKey());
  return hasVision && hasGemini ? "hybrid" : hasVision ? "google-vision" : hasGemini ? "gemini" : "off";
}

async function extractWithGoogleVision(filePath: string) {
  const apiKey = readGoogleVisionApiKey();

  if (!apiKey) {
    return undefined;
  }

  const tempDir = path.join(os.tmpdir(), `agricola-cane-vision-${randomUUID()}`);

  try {
    await fs.mkdir(tempDir, { recursive: true });
    const prefix = path.join(tempDir, "page");
    await execFileAsync("pdftoppm", ["-png", "-r", "180", filePath, prefix], {
      timeout: readPositiveIntegerEnv("CANE_PDF_RENDER_TIMEOUT_MS", 180_000, 10_000, 300_000),
      maxBuffer: 8 * 1024 * 1024
    });
    const pages = (await fs.readdir(tempDir))
      .filter((fileName) => /^page-\d+\.png$/i.test(fileName) || /^page\.png$/i.test(fileName))
      .sort(comparePageNames);

    if (pages.length === 0 || !(await reserveUsage("vision", pages.length))) {
      return undefined;
    }

    const requests = await Promise.all(
      pages.map(async (fileName) => ({
        image: { content: await fs.readFile(path.join(tempDir, fileName), "base64") },
        features: [{ type: "DOCUMENT_TEXT_DETECTION" }],
        imageContext: { languageHints: ["pt", "en"] }
      }))
    );
    const controller = new AbortController();
    const timeout = setTimeout(
      () => controller.abort(),
      readPositiveIntegerEnv("CANE_PDF_GOOGLE_TIMEOUT_MS", 35_000, 5_000, 120_000)
    );

    try {
      const response = await fetch(`${GOOGLE_VISION_ANNOTATE_URL}?key=${encodeURIComponent(apiKey)}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        signal: controller.signal,
        body: JSON.stringify({ requests })
      });

      if (!response.ok) {
        return undefined;
      }

      const payload = (await response.json()) as GoogleVisionResponse;
      const chunks = (payload.responses ?? [])
        .filter((item) => !item.error?.message)
        .map((item) => item.fullTextAnnotation?.text ?? item.textAnnotations?.[0]?.description ?? "")
        .filter((text) => text.trim().length > 0);
      return chunks.length === pages.length ? chunks.join("\n") : undefined;
    } finally {
      clearTimeout(timeout);
    }
  } catch {
    return undefined;
  } finally {
    await fs.rm(tempDir, { recursive: true, force: true }).catch(() => undefined);
  }
}

async function extractWithGemini(filePath: string) {
  const apiKey = readGeminiApiKey();

  if (!apiKey || !(await reserveUsage("gemini", 1))) {
    return undefined;
  }

  try {
    const content = await fs.readFile(filePath, "base64");
    const model = (
      process.env.CANE_PDF_GEMINI_MODEL ?? process.env.MAP_GEMINI_MODEL ?? process.env.GEMINI_MODEL ?? DEFAULT_GEMINI_MODEL
    )
      .trim()
      .replace(/^models\//i, "");
    const controller = new AbortController();
    const timeout = setTimeout(
      () => controller.abort(),
      readPositiveIntegerEnv("CANE_PDF_GEMINI_TIMEOUT_MS", 45_000, 5_000, 180_000)
    );

    try {
      const response = await fetch(`${GEMINI_GENERATE_CONTENT_BASE_URL}/${encodeURIComponent(model)}:generateContent`, {
        method: "POST",
        headers: { "Content-Type": "application/json", "x-goog-api-key": apiKey },
        signal: controller.signal,
        body: JSON.stringify({
          contents: [
            {
              role: "user",
              parts: [
                { inlineData: { mimeType: "application/pdf", data: content } },
                { text: buildGeminiPrompt() }
              ]
            }
          ],
          generationConfig: {
            temperature: 0,
            maxOutputTokens: 16384,
            responseMimeType: "application/json"
          }
        })
      });

      if (!response.ok) {
        return undefined;
      }

      const payload = (await response.json()) as GeminiResponse;
      const text = payload.candidates?.flatMap((candidate) => candidate.content?.parts ?? []).map((part) => part.text ?? "").join("\n");
      return normalizeGeminiExtraction(parseJsonObject(text ?? ""));
    } finally {
      clearTimeout(timeout);
    }
  } catch {
    return undefined;
  }
}

function buildGeminiPrompt() {
  return `Leia o relatorio SCS0110P - Resumo de Cana Entregue - Talhao.
Retorne somente JSON com reportDate, periodStart, periodEnd, totalNetWeight, totalTrips e rows.
Cada item de rows deve conter originCode, supplierCode, farm, field, netWeight e tripCount.
Copie todas as linhas de talhao exatamente uma vez. Nao inclua totais e nao invente valores.
Datas devem usar YYYY-MM-DD e numeros devem ser JSON numerico com ponto decimal.`;
}

function normalizeGeminiExtraction(value: unknown): GeminiCanePdfExtraction | undefined {
  if (!value || typeof value !== "object") {
    return undefined;
  }

  const data = value as Record<string, unknown>;
  const rows = Array.isArray(data.rows)
    ? data.rows.map(normalizeGeminiRow).filter((row): row is GeminiCanePdfRow => Boolean(row))
    : [];

  if (rows.length === 0) {
    return undefined;
  }

  return {
    reportDate: normalizeDate(data.reportDate),
    periodStart: normalizeDate(data.periodStart),
    periodEnd: normalizeDate(data.periodEnd),
    totalNetWeight: normalizeNumber(data.totalNetWeight),
    totalTrips: normalizeInteger(data.totalTrips),
    rows
  };
}

function normalizeGeminiRow(value: unknown): GeminiCanePdfRow | null {
  if (!value || typeof value !== "object") {
    return null;
  }

  const data = value as Record<string, unknown>;
  const originCode = normalizeCode(data.originCode);
  const supplierCode = normalizeCode(data.supplierCode);
  const farm = normalizeText(data.farm);
  const field = normalizeText(data.field);
  const netWeight = normalizeNumber(data.netWeight);
  const tripCount = normalizeInteger(data.tripCount);

  if (!originCode || !supplierCode || !farm || !field || netWeight === undefined || tripCount === undefined) {
    return null;
  }

  return { originCode, supplierCode, farm, field, netWeight, tripCount };
}

function parseJsonObject(text: string) {
  const cleaned = text.trim().replace(/^```(?:json)?\s*/i, "").replace(/\s*```$/i, "");
  const start = cleaned.indexOf("{");
  const end = cleaned.lastIndexOf("}");

  if (start < 0 || end <= start) {
    return undefined;
  }

  try {
    return JSON.parse(cleaned.slice(start, end + 1));
  } catch {
    return undefined;
  }
}

async function reserveUsage(kind: "vision" | "gemini", units: number) {
  const queue = kind === "vision" ? visionUsageQueue : geminiUsageQueue;
  let release: () => void = () => undefined;
  const nextQueue = new Promise((resolve) => {
    release = () => resolve(undefined);
  });

  if (kind === "vision") {
    visionUsageQueue = nextQueue;
  } else {
    geminiUsageQueue = nextQueue;
  }

  await queue.catch(() => undefined);

  try {
    const limit = readPositiveIntegerEnv(
      kind === "vision" ? "CANE_PDF_GOOGLE_MONTHLY_LIMIT" : "CANE_PDF_GEMINI_MONTHLY_LIMIT",
      kind === "vision" ? 1000 : 200,
      0,
      100_000
    );
    const usagePath = path.resolve(
      process.cwd(),
      kind === "vision" ? "./data/cane-pdf-google-vision-usage.json" : "./data/cane-pdf-gemini-usage.json"
    );
    const month = currentMonth();
    const current = await readUsageState(usagePath, month, limit);

    if (limit <= 0 || current.used + units > limit) {
      return false;
    }

    await fs.mkdir(path.dirname(usagePath), { recursive: true });
    await fs.writeFile(
      usagePath,
      `${JSON.stringify({ ...current, used: current.used + units, updatedAt: new Date().toISOString() }, null, 2)}\n`,
      "utf8"
    );
    return true;
  } finally {
    release();
  }
}

async function readUsageState(filePath: string, month: string, limit: number): Promise<UsageState> {
  try {
    const parsed = JSON.parse(await fs.readFile(filePath, "utf8")) as Partial<UsageState>;

    if (parsed.month === month && Number.isFinite(parsed.used)) {
      return { month, used: Math.max(0, Math.floor(Number(parsed.used))), limit, updatedAt: parsed.updatedAt ?? new Date().toISOString() };
    }
  } catch {
    // A missing or invalid counter starts a fresh month.
  }

  return { month, used: 0, limit, updatedAt: new Date().toISOString() };
}

function readGoogleVisionApiKey() {
  return (process.env.GOOGLE_CLOUD_VISION_API_KEY ?? process.env.GOOGLE_VISION_API_KEY ?? process.env.GOOGLE_API_KEY ?? "").trim();
}

function readGeminiApiKey() {
  return (
    process.env.GEMINI_API_KEY ??
    process.env.GOOGLE_GEMINI_API_KEY ??
    process.env.GOOGLE_AI_API_KEY ??
    process.env.GOOGLE_GENERATIVE_AI_API_KEY ??
    ""
  ).trim();
}

function readPositiveIntegerEnv(name: string, fallback: number, min: number, max: number) {
  const value = Number(process.env[name]);
  return Number.isFinite(value) ? Math.max(min, Math.min(max, Math.floor(value))) : fallback;
}

function currentMonth() {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
}

function comparePageNames(left: string, right: string) {
  const leftNumber = Number(/page-(\d+)\.png$/i.exec(left)?.[1] ?? "1");
  const rightNumber = Number(/page-(\d+)\.png$/i.exec(right)?.[1] ?? "1");
  return leftNumber - rightNumber || left.localeCompare(right);
}

function normalizeCode(value: unknown) {
  const text = normalizeText(value);
  return text && /^\d+$/.test(text) ? text : undefined;
}

function normalizeText(value: unknown) {
  if (typeof value !== "string" && typeof value !== "number") {
    return undefined;
  }

  return String(value).trim() || undefined;
}

function normalizeDate(value: unknown) {
  const text = normalizeText(value);
  return text && /^\d{4}-\d{2}-\d{2}$/.test(text) ? text : undefined;
}

function normalizeNumber(value: unknown) {
  const number = typeof value === "number" ? value : Number(String(value ?? "").replace(",", "."));
  return Number.isFinite(number) && number >= 0 ? number : undefined;
}

function normalizeInteger(value: unknown) {
  const number = normalizeNumber(value);
  return number !== undefined && Number.isInteger(number) ? number : undefined;
}
