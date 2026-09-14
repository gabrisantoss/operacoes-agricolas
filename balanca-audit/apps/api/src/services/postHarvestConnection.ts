export function hasRequiredPostHarvestDeliveryConfig(input: { url?: string | null; token?: string | null }) {
  return Boolean(input.url?.trim() && input.token?.trim());
}

export const missingPostHarvestDeliveryConfigMessage =
  "POST_HARVEST_WEBHOOK_URL e POST_HARVEST_WEBHOOK_TOKEN devem estar configurados.";
