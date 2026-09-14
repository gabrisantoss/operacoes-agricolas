import { randomUUID } from "node:crypto";
import { systemIdentity } from "@balanca/shared";
import type { FarmRecord, HarvestOrderRecord } from "../db.js";
import {
  claimPostHarvestDispatchableIntegrationEvents,
  claimPostHarvestIntegrationEventById,
  closeOrderWithinExistingTransaction,
  createPostHarvestIntegrationEvents,
  db,
  findOrderById,
  findPostHarvestIntegrationEventById,
  markPostHarvestIntegrationEventError,
  markPostHarvestIntegrationEventSent,
  type PostHarvestIntegrationEventRecord
} from "../db.js";
import type { CreatePostHarvestIntegrationEventInput } from "../repositories/postHarvestIntegrationRepository.js";
import { env } from "../env.js";
import { buildPostHarvestEventId, POST_HARVEST_EVENT_VERSION } from "./postHarvestEvent.js";
import { dispatchClaimedItemsOneAtATime } from "./postHarvestDispatchLoop.js";
import {
  hasRequiredPostHarvestDeliveryConfig,
  missingPostHarvestDeliveryConfigMessage
} from "./postHarvestConnection.js";

const eventType = "TALHAO_LIBERADO_POS_COLHEITA";
const eventVersion = POST_HARVEST_EVENT_VERSION;
const releasedStatus = "TALHAO_LIBERADO_POS_COLHEITA";
const pendingManagementDecision = "AGUARDANDO_DECISAO";
const managementOptions = ["COBERTURA_SOQUEIRA", "REFORMA_PREPARO_SOLO"] as const;
const dispatcherWorkerId = `post-harvest:${process.pid}:${randomUUID()}`;
const dispatcherLeaseMs = 2 * 60_000;
let dispatcherActive = false;
let dispatcherTimer: NodeJS.Timeout | null = null;
let schedulerStarted = false;

export type PostHarvestDispatchResult = {
  event: PostHarvestIntegrationEventRecord | null;
  sent: boolean;
  skipped?: boolean;
  reason?: string;
};

export function closeOrderAndReleasePostHarvest(orderId: string) {
  const closeAndEnqueue = db.transaction(() => {
    const current = findOrderById(orderId);
    if (!current) return null;

    if (current.status !== "CLOSED" && !closeOrderWithinExistingTransaction(orderId)) {
      return null;
    }

    const closedOrder = findOrderById(orderId);
    if (!closedOrder) return null;

    const inputs = buildPostHarvestReleaseEventInputs(closedOrder, new Date().toISOString());
    const events = createPostHarvestIntegrationEvents(inputs);
    return { order: closedOrder, events };
  });

  const result = closeAndEnqueue();
  if (result) wakePostHarvestDispatcher();
  return result;
}

/** Backward-compatible entry point for already closed orders. */
export function releasePostHarvestForClosedOrder(order: HarvestOrderRecord) {
  const events = createPostHarvestReleaseEventsForOrder(order);
  wakePostHarvestDispatcher();
  return events;
}

export function createPostHarvestReleaseEventsForOrder(order: HarvestOrderRecord) {
  if (order.status !== "CLOSED") return [];

  return createPostHarvestIntegrationEvents(
    buildPostHarvestReleaseEventInputs(order, new Date().toISOString())
  );
}

export function buildPostHarvestReleaseEventInputs(
  order: HarvestOrderRecord,
  dataEvento: string
): CreatePostHarvestIntegrationEventInput[] {
  if (order.status !== "CLOSED") return [];

  return order.fields.map((orderField) => {
    const farm = resolveFieldFarm(order, orderField.field.farmId);
    const field = orderField.field;
    const eventId = buildPostHarvestEventId(order.number, farm.code ?? farm.id, field.code);
    const payload = {
      evento_id: eventId,
      versao_evento: eventVersion,
      tipo: eventType,
      origem: systemIdentity.currentNameAscii,
      data_evento: dataEvento,
      safra: field.cropYear ?? farm.cropYear ?? null,
      fazenda_codigo: farm.code ?? null,
      fazenda_nome: farm.sectionName ?? farm.name,
      talhao_codigo: field.code,
      talhao_nome: field.name ?? null,
      os_colheita: order.number,
      frente: order.frontNumbers[0] ?? null,
      frentes: order.frontNumbers,
      data_inicio_colheita: order.startDate ?? null,
      data_fim_colheita: order.endDate ?? dataEvento,
      status: releasedStatus,
      decisao_manejo: pendingManagementDecision,
      opcoes_manejo: managementOptions
    };

    return {
      eventId,
      eventType,
      eventVersion,
      orderId: order.id,
      orderNumber: order.number,
      farmId: farm.id,
      farmCode: farm.code ?? null,
      farmName: farm.sectionName ?? farm.name,
      fieldId: field.id,
      fieldCode: field.code,
      frontNumbers: order.frontNumbers,
      payload
    };
  });
}

export function getPostHarvestConnectionInfo() {
  const configured = postHarvestDeliveryConfigured();
  return {
    mode: "OUTGOING_WEBHOOK",
    configured,
    targetUrlConfigured: Boolean(env.postHarvestWebhookUrl),
    tokenConfigured: Boolean(env.postHarvestWebhookToken),
    timeoutMs: env.postHarvestWebhookTimeoutMs,
    eventVersion,
    delivery: { leaseMs: dispatcherLeaseMs, maxAttempts: 8, idempotency: "event_id" },
    requiredReceiver: {
      method: "POST",
      contentType: "application/json",
      idempotencyHeader: "Idempotency-Key",
      authorizationHeader: "Authorization: Bearer <token>"
    },
    env: {
      url: "POST_HARVEST_WEBHOOK_URL",
      token: "POST_HARVEST_WEBHOOK_TOKEN",
      timeoutMs: "POST_HARVEST_WEBHOOK_TIMEOUT_MS"
    }
  };
}

export async function dispatchPostHarvestEventById(id: string): Promise<PostHarvestDispatchResult> {
  const existing = findPostHarvestIntegrationEventById(id);
  if (!existing) return { event: null, sent: false, skipped: true, reason: "Evento nao encontrado." };
  if (existing.status === "SENT") return { event: existing, sent: true, skipped: true, reason: "Evento ja enviado." };
  if (!postHarvestDeliveryConfigured()) return { event: existing, sent: false, skipped: true, reason: missingPostHarvestDeliveryConfigMessage };

  const event = claimPostHarvestIntegrationEventById(id, dispatcherWorkerId, dispatcherLeaseMs);
  if (!event) {
    return { event: findPostHarvestIntegrationEventById(id), sent: false, skipped: true, reason: "Evento indisponivel ou aguardando retry." };
  }
  return dispatchClaimedPostHarvestEvent(event);
}

export async function dispatchPendingPostHarvestEvents(limit = 50) {
  if (!postHarvestDeliveryConfigured()) return [];
  // Claim immediately before each network call. Claiming the whole batch would
  // consume the fixed lease while later events wait behind earlier timeouts.
  return dispatchClaimedItemsOneAtATime({
    limit,
    claimOne: () => claimPostHarvestDispatchableIntegrationEvents({
      workerId: dispatcherWorkerId,
      limit: 1,
      leaseMs: dispatcherLeaseMs
    })[0] ?? null,
    dispatchOne: dispatchClaimedPostHarvestEvent
  });
}

export async function dispatchPostHarvestEvents(events: PostHarvestIntegrationEventRecord[]) {
  const results: PostHarvestDispatchResult[] = [];
  for (const event of events) results.push(await dispatchClaimedPostHarvestEvent(event));
  return results;
}

export function startPostHarvestScheduler() {
  if (schedulerStarted) return;
  schedulerStarted = true;
  wakePostHarvestDispatcher();
}

function wakePostHarvestDispatcher(delayMs = 0) {
  if (!postHarvestDeliveryConfigured() || dispatcherActive) return;
  if (dispatcherTimer) clearTimeout(dispatcherTimer);
  dispatcherTimer = setTimeout(() => {
    dispatcherTimer = null;
    if (dispatcherActive) return;
    dispatcherActive = true;
    void dispatchPendingPostHarvestEvents(25)
      .catch((error) => console.error("Falha no scheduler do outbox pos-colheita.", error))
      .finally(() => {
        dispatcherActive = false;
        wakePostHarvestDispatcher(30_000);
      });
  }, Math.max(0, delayMs));
  dispatcherTimer.unref();
}

async function dispatchClaimedPostHarvestEvent(event: PostHarvestIntegrationEventRecord): Promise<PostHarvestDispatchResult> {
  if (!postHarvestDeliveryConfigured()) {
    return { event, sent: false, skipped: true, reason: missingPostHarvestDeliveryConfigMessage };
  }

  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), env.postHarvestWebhookTimeoutMs);
  try {
    const response = await fetch(env.postHarvestWebhookUrl, {
      method: "POST",
      headers: buildWebhookHeaders(event.eventId),
      body: JSON.stringify(event.payload),
      signal: controller.signal
    });
    const responseBody = await response.text().catch(() => "");

    if (response.ok) {
      const updated = markPostHarvestIntegrationEventSent(event.id, dispatcherWorkerId, {
        httpStatus: response.status,
        responseBody
      });
      return { event: updated, sent: true };
    }

    const updated = markPostHarvestIntegrationEventError(event, dispatcherWorkerId, {
      httpStatus: response.status,
      responseBody,
      error: `Destino respondeu HTTP ${response.status}.`
    });
    return { event: updated, sent: false, reason: `HTTP ${response.status}` };
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    const updated = markPostHarvestIntegrationEventError(event, dispatcherWorkerId, { error: message });
    return { event: updated, sent: false, reason: message };
  } finally {
    clearTimeout(timeout);
  }
}

function buildWebhookHeaders(eventId: string) {
  return {
    "Content-Type": "application/json",
    "Idempotency-Key": eventId,
    Authorization: `Bearer ${env.postHarvestWebhookToken}`
  };
}

function postHarvestDeliveryConfigured() {
  return hasRequiredPostHarvestDeliveryConfig({
    url: env.postHarvestWebhookUrl,
    token: env.postHarvestWebhookToken
  });
}

function resolveFieldFarm(order: HarvestOrderRecord, farmId: string): FarmRecord {
  return order.farms.find((farm) => farm.id === farmId) ?? order.farm;
}
