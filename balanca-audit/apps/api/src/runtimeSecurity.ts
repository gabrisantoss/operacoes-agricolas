export const defaultApiHost = "127.0.0.1";

export function resolveApiHost(value: string | undefined) {
  return value?.trim() || defaultApiHost;
}

export function isLoopbackAddress(value: string | undefined | null) {
  const normalized = String(value ?? "")
    .trim()
    .toLowerCase()
    .replace(/^\[|\]$/g, "")
    .replace(/^::ffff:/, "");

  return normalized === "localhost" || normalized === "::1" || normalized === "0:0:0:0:0:0:0:1" || normalized.startsWith("127.");
}

export function localAccessIsAllowed(input: {
  configured: boolean;
  apiHost: string;
  remoteAddress?: string | null;
}) {
  return input.configured && isLoopbackAddress(input.apiHost) && isLoopbackAddress(input.remoteAddress);
}

export function localAccessIsConfiguredForDevelopment(input: {
  requested: boolean;
  nodeEnv?: string;
  npmLifecycleEvent?: string;
}) {
  const nodeEnv = input.nodeEnv?.trim().toLowerCase();
  const lifecycle = input.npmLifecycleEvent?.trim().toLowerCase();
  return input.requested && (nodeEnv === "development" || lifecycle === "dev");
}
