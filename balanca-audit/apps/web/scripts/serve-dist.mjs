import { createReadStream } from "node:fs";
import { stat } from "node:fs/promises";
import { createServer } from "node:http";
import { extname, join, normalize, relative } from "node:path";
import { fileURLToPath } from "node:url";

const host = process.env.WEB_HOST || "127.0.0.1";
const port = Number(process.env.WEB_PORT || 8873);
const rootDir = normalize(join(fileURLToPath(new URL(".", import.meta.url)), ".."));
const distDir = normalize(join(rootDir, "dist"));
const indexFile = join(distDir, "index.html");

const contentTypes = {
  ".css": "text/css; charset=utf-8",
  ".html": "text/html; charset=utf-8",
  ".ico": "image/x-icon",
  ".js": "text/javascript; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".map": "application/json; charset=utf-8",
  ".png": "image/png",
  ".svg": "image/svg+xml",
  ".webp": "image/webp",
};

function isInsideDist(filePath) {
  const rel = relative(distDir, normalize(filePath));
  return rel && !rel.startsWith("..") && !rel.includes(":");
}

async function resolveFile(requestUrl) {
  const parsedUrl = new URL(requestUrl, `http://${host}:${port}`);
  const cleanPath = decodeURIComponent(parsedUrl.pathname)
    .replace(/^\/balanca\/?/, "")
    .replace(/^\/+/, "");
  const requestedFile = join(distDir, cleanPath);

  if (isInsideDist(requestedFile)) {
    try {
      const info = await stat(requestedFile);
      if (info.isFile()) return requestedFile;
    } catch {
      // Fall through to SPA fallback.
    }
  }

  if (parsedUrl.pathname.startsWith("/assets/") || parsedUrl.pathname.startsWith("/balanca/assets/")) return null;
  return indexFile;
}

const server = createServer(async (request, response) => {
  if (!request.url || !["GET", "HEAD"].includes(request.method || "")) {
    response.writeHead(405, { Allow: "GET, HEAD" });
    response.end();
    return;
  }

  const filePath = await resolveFile(request.url).catch(() => null);
  if (!filePath) {
    response.writeHead(404, { "Content-Type": "text/plain; charset=utf-8" });
    response.end("Arquivo nao encontrado.");
    return;
  }

  response.writeHead(200, {
    "Cache-Control": filePath.includes(`${join("dist", "assets")}`) ? "public, max-age=31536000, immutable" : "no-cache",
    "Content-Type": contentTypes[extname(filePath).toLowerCase()] || "application/octet-stream",
  });

  if (request.method === "HEAD") {
    response.end();
    return;
  }

  createReadStream(filePath).pipe(response);
});

server.on("error", (error) => {
  if (error.code === "EADDRINUSE") {
    console.error(`Porta ${port} ja esta em uso.`);
    process.exit(1);
  }
  console.error(error);
  process.exit(1);
});

server.listen(port, host, () => {
  console.log(`Web da balanca em http://localhost:${port}`);
});
