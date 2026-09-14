type InternalHealth = {
  ok: boolean;
  service: string;
  timestamp: string;
  [key: string]: unknown;
};

export type HealthCheck = {
  ok: boolean;
  [key: string]: unknown;
};

export function internalHealthResponse(input: {
  service: string;
  timestamp: string;
  uptimeSeconds: number;
  coreChecks: Record<string, HealthCheck>;
  advisoryChecks?: Record<string, HealthCheck>;
}) {
  return {
    ok: Object.values(input.coreChecks).every((check) => check.ok),
    service: input.service,
    timestamp: input.timestamp,
    uptimeSeconds: input.uptimeSeconds,
    checks: {
      ...input.coreChecks,
      ...(input.advisoryChecks ?? {})
    }
  };
}

export function publicHealthResponse(health: InternalHealth) {
  return {
    ok: health.ok,
    service: health.service,
    timestamp: health.timestamp
  };
}
