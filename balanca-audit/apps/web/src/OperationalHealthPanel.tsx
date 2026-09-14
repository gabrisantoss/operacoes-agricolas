import { useCallback, useEffect, useState } from "react";
import { RefreshCw } from "lucide-react";
import { apiRequest } from "./api";

type QueueSourceError = {
  ok: false;
  available: false;
  attentionRequired: boolean;
  draining?: false;
  message: string;
};

type BackgroundJobsHealth = {
  ok: boolean;
  available: true;
  attentionRequired: boolean;
  draining?: boolean;
  counts: {
    QUEUED: number;
    RUNNING: number;
    RETRY: number;
    SUCCEEDED: number;
    DEAD: number;
  };
  oldestPendingOrRetryAt: string | null;
  oldestPendingOrRetryAgeSeconds: number | null;
  claimableNowCount?: number;
  scheduledRetryCount?: number;
  oldestClaimableAt?: string | null;
  oldestClaimableAgeSeconds?: number | null;
  staleAfterSeconds?: number;
  lastSucceededAt?: string | null;
  lastSucceededAgeSeconds?: number | null;
  deadCount: number;
  expiredRunningLeaseCount: number;
  missingRunningLeaseCount: number;
  unknownStatusCount: number;
};

type PostHarvestOutboxHealth = {
  ok: boolean;
  available: true;
  attentionRequired: boolean;
  draining?: boolean;
  counts: {
    PENDING: number;
    PROCESSING: number;
    SENT: number;
    ERROR: number;
    DEAD: number;
  };
  oldestPendingOrErrorAt: string | null;
  oldestPendingOrErrorAgeSeconds: number | null;
  deliveryConfigured?: boolean;
  claimableNowCount?: number;
  scheduledRetryCount?: number;
  oldestClaimableAt?: string | null;
  oldestClaimableAgeSeconds?: number | null;
  staleAfterSeconds?: number;
  lastSentAt?: string | null;
  lastSentAgeSeconds?: number | null;
  deadCount: number;
  expiredProcessingLeaseCount: number;
  missingProcessingLeaseCount: number;
  unknownStatusCount: number;
};

type OperationalHealth = {
  ok: boolean;
  timestamp: string;
  uptimeSeconds: number;
  checks: {
    database?: {
      ok: boolean;
      provider?: string;
      schemaVersion?: string | null;
      message?: string;
    };
    disk?: {
      ok: boolean;
      freeBytes?: number;
      minFreeBytes?: number;
      message?: string;
    };
    persistentQueues?: {
      ok: boolean;
      state?: "OK" | "DRAINING" | "ATTENTION" | "WAITING_CONFIGURATION" | "UNAVAILABLE";
      available: boolean;
      degraded: boolean;
      attentionRequired: boolean;
      draining?: boolean;
      configurationRequired?: boolean;
      collectedAt: string;
      message?: string;
      warning?: string;
      backgroundJobs: BackgroundJobsHealth | QueueSourceError;
      postHarvestOutbox: PostHarvestOutboxHealth | QueueSourceError;
    };
  };
};

export function OperationalHealthPanel({ token }: { token: string }) {
  const [snapshot, setSnapshot] = useState<OperationalHealth | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);

    try {
      const payload = await apiRequest<OperationalHealth>("/health/details", token);
      setSnapshot(payload);
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "Falha ao carregar a saude operacional.");
    } finally {
      setLoading(false);
    }
  }, [token]);

  useEffect(() => {
    void load();
  }, [load]);

  const queues = snapshot?.checks.persistentQueues;
  const background = queues?.backgroundJobs;
  const outbox = queues?.postHarvestOutbox;
  const outboxWaiting = outbox?.available ? outbox.counts.PENDING + outbox.counts.ERROR : 0;
  const deliveryNotConfigured = Boolean(outbox?.available && outbox.deliveryConfigured === false);
  const configurationRequired = queues?.configurationRequired ?? (deliveryNotConfigured && outboxWaiting > 0);
  const deliveryNeedsConfiguration = configurationRequired || deliveryNotConfigured;
  const queueDraining = queues?.state === "DRAINING" || queues?.draining === true;
  const overallTone = !snapshot?.ok || (queues && !queues.available)
    ? "danger"
    : queues?.attentionRequired || deliveryNeedsConfiguration || queueDraining
      ? "warning"
      : "ok";
  const overallStatus = overallTone === "danger"
    ? "Falha"
    : queues?.attentionRequired
      ? "Atencao"
      : deliveryNeedsConfiguration
        ? "Aguardando configuracao"
        : queueDraining
          ? "Processando backlog"
        : "Saudavel";

  return (
    <section className="panel" aria-live="polite">
      <div className="sectionHeader">
        <div>
          <h2>Saude operacional</h2>
          <span className="muted">Banco, disco, filas persistentes e outbox pos-colheita.</span>
        </div>
        <div className="filterActions">
          {snapshot ? (
            <span className={`statusBadge ${overallTone}`}>{overallStatus}</span>
          ) : null}
          <button className="secondaryButton compactButton" type="button" onClick={() => void load()} disabled={loading}>
            <RefreshCw size={16} />
            {loading ? "Atualizando" : "Atualizar saude"}
          </button>
        </div>
      </div>

      {loading && !snapshot ? <div className="emptyState">Carregando saude operacional...</div> : null}
      {error ? (
        <div className="notice">
          {error} {snapshot ? "O ultimo snapshot valido foi preservado." : ""}
        </div>
      ) : null}

      {snapshot ? (
        <>
          <div className="statusGrid">
            <HealthStatus
              label="PostgreSQL"
              tone={healthTone(snapshot.checks.database?.ok)}
              value={snapshot.checks.database?.provider ?? "-"}
            />
            <HealthStatus
              label="Schema"
              tone={healthTone(snapshot.checks.database?.ok)}
              value={snapshot.checks.database?.schemaVersion ?? "-"}
            />
            <HealthStatus
              label="Disco livre"
              tone={healthTone(snapshot.checks.disk?.ok)}
              value={formatBytes(snapshot.checks.disk?.freeBytes)}
            />
            <HealthStatus label="Uptime" tone={healthTone(snapshot.ok)} value={formatDuration(snapshot.uptimeSeconds)} />
          </div>

          {background?.available && outbox?.available ? (
            <div className="metricsGrid compactMetrics operationalHealthMetrics">
              <OperationalMetric
                label="Jobs prontos"
                value={background.claimableNowCount ?? background.counts.QUEUED + background.counts.RETRY}
              />
              <OperationalMetric label="Jobs executando" value={background.counts.RUNNING} />
              <OperationalMetric label="Jobs dead-letter" value={background.deadCount} danger={background.deadCount > 0} />
              <OperationalMetric label={deliveryNotConfigured ? "Eventos preservados" : "Outbox aguardando"} value={outboxWaiting} />
              <OperationalMetric
                label={deliveryNotConfigured ? "Prontos ao configurar" : "Outbox pronta"}
                value={outbox.claimableNowCount ?? outboxWaiting}
              />
              <OperationalMetric label="Outbox dead-letter" value={outbox.deadCount} danger={outbox.deadCount > 0} />
            </div>
          ) : null}

          <div className="statusGrid operationalQueueGrid">
            <QueueSourceStatus
              label="Trabalhos em segundo plano"
              source={background}
              claimableNow={background?.available ? background.claimableNowCount ?? background.counts.QUEUED + background.counts.RETRY : null}
              scheduledRetry={background?.available ? background.scheduledRetryCount ?? 0 : null}
              backlogAge={background?.available ? background.oldestClaimableAgeSeconds ?? background.oldestPendingOrRetryAgeSeconds : null}
              expiredLeases={background?.available ? background.expiredRunningLeaseCount : null}
              missingLeases={background?.available ? background.missingRunningLeaseCount : null}
              unknownStatuses={background?.available ? background.unknownStatusCount : null}
              lastProgressAge={background?.available ? background.lastSucceededAgeSeconds ?? null : null}
            />
            <QueueSourceStatus
              label="Outbox pos-colheita"
              source={outbox}
              claimableNow={outbox?.available ? outbox.claimableNowCount ?? outboxWaiting : null}
              scheduledRetry={outbox?.available ? outbox.scheduledRetryCount ?? 0 : null}
              backlogAge={outbox?.available ? outbox.oldestClaimableAgeSeconds ?? outbox.oldestPendingOrErrorAgeSeconds : null}
              expiredLeases={outbox?.available ? outbox.expiredProcessingLeaseCount : null}
              missingLeases={outbox?.available ? outbox.missingProcessingLeaseCount : null}
              unknownStatuses={outbox?.available ? outbox.unknownStatusCount : null}
              lastProgressAge={outbox?.available ? outbox.lastSentAgeSeconds ?? null : null}
              deliveryNotConfigured={deliveryNotConfigured}
              waitingCount={outboxWaiting}
            />
            <HealthStatus
              label="Snapshot"
              tone={
                !queues || !queues.available
                  ? "danger"
                  : queues.attentionRequired || queues.configurationRequired || queues.draining
                    ? "warning"
                    : "ok"
              }
              value={formatDateTime(queues?.collectedAt ?? snapshot.timestamp)}
              statusLabel={
                queues?.state === "WAITING_CONFIGURATION"
                  ? "Aguardando"
                  : queues?.state === "DRAINING"
                    ? "Processando"
                    : undefined
              }
            />
          </div>

          {queues?.message ? <div className="notice">{queues.message}</div> : null}
          {queues?.warning ? <div className="notice">{queues.warning}</div> : null}
        </>
      ) : null}
    </section>
  );
}

function OperationalMetric({ label, value, danger = false }: { label: string; value: number; danger?: boolean }) {
  return (
    <article className={`metric ${danger ? "danger" : "info"}`}>
      <span>{label}</span>
      <strong>{formatCount(value)}</strong>
    </article>
  );
}

function HealthStatus({
  label,
  tone,
  value,
  statusLabel
}: {
  label: string;
  tone: "ok" | "warning" | "danger";
  value: string;
  statusLabel?: string;
}) {
  const status = statusLabel ?? (tone === "ok" ? "OK" : tone === "warning" ? "Atencao" : "Falha");
  return (
    <article className="statusItem operationalStatusItem">
      <span>{label}</span>
      <strong>{value}</strong>
      <small className={`statusBadge ${tone}`}>{status}</small>
    </article>
  );
}

function QueueSourceStatus({
  label,
  source,
  claimableNow,
  scheduledRetry,
  backlogAge,
  expiredLeases,
  missingLeases,
  unknownStatuses,
  lastProgressAge,
  deliveryNotConfigured = false,
  waitingCount = 0
}: {
  label: string;
  source?: BackgroundJobsHealth | PostHarvestOutboxHealth | QueueSourceError;
  claimableNow: number | null;
  scheduledRetry: number | null;
  backlogAge: number | null;
  expiredLeases: number | null;
  missingLeases: number | null;
  unknownStatuses: number | null;
  lastProgressAge: number | null;
  deliveryNotConfigured?: boolean;
  waitingCount?: number;
}) {
  const sourceDraining = Boolean(source?.available && source.draining);
  const tone = !source || !source.available
    ? "danger"
    : source.attentionRequired || deliveryNotConfigured || sourceDraining
      ? "warning"
      : "ok";
  const value = !source
    ? "Sem telemetria"
    : !source.available
      ? source.message
      : deliveryNotConfigured
        ? [
            `envio automatico nao configurado`,
            `${formatCount(waitingCount)} evento(s) preservado(s)`,
            `${formatCount(source.deadCount)} dead-letter`,
            `${expiredLeases ?? 0} lease(s) vencido(s)`,
            `${missingLeases ?? 0} sem lease`,
            `${unknownStatuses ?? 0} status desconhecido(s)`,
            "nenhum envio sera tentado ate configurar o destino"
          ].join("; ")
      : [
          `${formatCount(claimableNow ?? 0)} pronto(s) agora`,
          `${formatCount(scheduledRetry ?? 0)} agendado(s)`,
          backlogAge === null ? "sem espera" : `mais antigo pronto ha ${formatDuration(backlogAge)}`,
          ...(claimableNow && claimableNow > 0
            ? [lastProgressAge === null ? "sem conclusao recente" : `ultimo sucesso ha ${formatDuration(lastProgressAge)}`]
            : []),
          `${expiredLeases ?? 0} lease(s) vencido(s)`,
          `${missingLeases ?? 0} sem lease`,
          `${unknownStatuses ?? 0} status desconhecido(s)`
        ].join("; ");

  return (
    <HealthStatus
      label={label}
      tone={tone}
      value={value}
      statusLabel={
        source?.attentionRequired
          ? undefined
          : deliveryNotConfigured
            ? "Nao configurado"
            : sourceDraining
              ? "Processando"
              : undefined
      }
    />
  );
}

function healthTone(ok?: boolean): "ok" | "warning" | "danger" {
  return ok === true ? "ok" : ok === false ? "danger" : "warning";
}

function formatBytes(value?: number) {
  if (value === undefined || !Number.isFinite(value)) {
    return "-";
  }
  return `${(value / 1024 ** 3).toLocaleString("pt-BR", { maximumFractionDigits: 1 })} GB`;
}

function formatDuration(value: number) {
  const seconds = Math.max(0, Math.trunc(value));
  if (seconds < 60) return `${seconds}s`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}min`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ${Math.floor((seconds % 3600) / 60)}min`;
  return `${Math.floor(seconds / 86400)}d ${Math.floor((seconds % 86400) / 3600)}h`;
}

function formatDateTime(value: string) {
  const parsed = new Date(value);
  return Number.isFinite(parsed.getTime()) ? parsed.toLocaleString("pt-BR") : "-";
}

function formatCount(value: number) {
  return Math.max(0, Math.trunc(value)).toLocaleString("pt-BR");
}
