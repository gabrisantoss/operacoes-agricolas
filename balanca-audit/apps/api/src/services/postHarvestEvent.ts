export const POST_HARVEST_EVENT_VERSION = 1;

export function buildPostHarvestEventId(orderNumber: string, farmCode: string, fieldCode: string) {
  return `POSCOLHEITA-V${POST_HARVEST_EVENT_VERSION}-${normalizeEventToken(orderNumber)}-${normalizeEventToken(farmCode)}-${normalizeEventToken(fieldCode)}`;
}

function normalizeEventToken(value: string) {
  const token = value
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toUpperCase()
    .replace(/[^A-Z0-9]+/g, "");
  return token || "SEMIDENTIFICACAO";
}
