import { z } from "zod";


// Identidade funcional atual do sistema.
// "balanca" continua como namespace tecnico legado em rotas, pacotes, banco,
// variaveis de ambiente e chaves de storage para manter compatibilidade.
export const systemIdentity = {
  currentName: "Portal de Opera\u00e7\u00f5es Agr\u00edcolas",
  currentNameAscii: "Portal de Operacoes Agricolas",
  legacyNamespace: "balanca",
  legacyNames: ["Balanca Audit", "Auditoria da Balanca"] as const,
  compatibilityNote:
    "Referencias tecnicas com 'balanca' sao legadas e devem continuar funcionando; a identidade do produto e operacoes agricolas."
} as const;

export const entryStatuses = [
  "OK",
  "OS_NOT_FOUND",
  "FARM_NOT_FOUND",
  "FIELD_NOT_FOUND",
  "FARM_MISMATCH",
  "FIELD_NOT_RELEASED",
  "MISSING_DATA"
] as const;

export const userRoles = ["ADMIN", "ANALYST", "VIEWER"] as const;

export const fleetMovementTypes = ["LEFT_MILL", "RETURNED_MILL", "RESERVE_ACTIVATED", "RESERVE_RELEASED"] as const;
export const fleetEquipmentTypes = [
  "COLHEDORA",
  "TRANSBORDO",
  "CARREGADEIRA",
  "VIVENCIA",
  "CAMINHAO_DAGUA",
  "FURGAO",
  "ONIBUS",
  "OUTRO"
] as const;
export const fleetMovementStatuses = ["OPEN", "CLOSED"] as const;

export const entryStatusSchema = z.enum(entryStatuses);
export const userRoleSchema = z.enum(userRoles);

export const fleetMovementTypeSchema = z.enum(fleetMovementTypes);
export const fleetEquipmentTypeSchema = z.enum(fleetEquipmentTypes);
export const fleetMovementStatusSchema = z.enum(fleetMovementStatuses);

export type EntryStatus = z.infer<typeof entryStatusSchema>;
export type UserRole = z.infer<typeof userRoleSchema>;

export type FleetMovementType = z.infer<typeof fleetMovementTypeSchema>;
export type FleetEquipmentType = z.infer<typeof fleetEquipmentTypeSchema>;
export type FleetMovementStatus = z.infer<typeof fleetMovementStatusSchema>;

export const loginSchema = z.object({
  email: z.string().trim().min(1),
  password: z.string().min(1)
});

const optionalAreaSchema = z.preprocess(
  (value) => {
    if (typeof value === "string") {
      const trimmed = value.trim();
      return trimmed ? Number(trimmed.replace(",", ".")) : undefined;
    }

    return value;
  },
  z.number().min(0).optional()
);



const createFarmFieldSchema = z.object({
  code: z.string().trim().min(1),
  areaAlq: optionalAreaSchema
});

export function formatFarmCode(value: string | null | undefined) {
  const digits = String(value ?? "").replace(/\D/g, "");
  return digits.length > 3 ? `${digits.slice(0, 3)}-${digits.slice(3)}` : digits;
}

export function formatFarmCodeInput(value: string) {
  return formatFarmCode(value);
}

export function normalizeFarmText(value: string | null | undefined) {
  return String(value ?? "").replace(/\s+/g, " ").trim().toLocaleUpperCase("pt-BR");
}





const farmCodeSchema = z
  .string()
  .trim()
  .regex(/^[\d-]*$/)
  .transform(formatFarmCode)
  .refine((value) => value === "" || /^\d{3}-\d+$/.test(value));

const farmTextSchema = z.string().transform(normalizeFarmText);

export const createFarmSchema = z.object({
  code: farmCodeSchema.optional(),
  name: farmTextSchema.pipe(z.string().min(1)),
  sectionName: farmTextSchema.optional(),
  ownerName: farmTextSchema.optional(),
  municipality: farmTextSchema.optional(),




  fields: z.array(z.union([z.string().trim().min(1), createFarmFieldSchema])).default([])
});

export const updateFarmSchema = z.object({
  code: farmCodeSchema.optional(),
  name: farmTextSchema.pipe(z.string().min(1)),
  sectionName: farmTextSchema.optional(),
  ownerName: farmTextSchema.optional(),
  municipality: farmTextSchema.optional(),




});

export const createFieldSchema = z.object({
  code: z.string().trim().min(1),
  name: z.string().trim().optional(),
  areaAlq: optionalAreaSchema
});

export const updateFieldSchema = createFieldSchema.extend({
  code: z.string().trim().min(1),
});

const orderInputSchema = z.object({
  number: z.string().trim().min(1),
  frontNumber: z.coerce.number().int().min(1).max(99).optional(),
  frontNumbers: z.array(z.coerce.number().int().min(1).max(99)).optional(),
  farmId: z.string().trim().optional(),
  fieldIds: z.array(z.string().trim().min(1)).min(1),
  startDate: z.string().optional(),
  endDate: z.string().optional(),
  origin: z.string().trim().optional()
});

export const createOrderSchema = orderInputSchema;
export const updateOrderSchema = orderInputSchema;

export const bulkCloseOrdersSchema = z.object({
  numbers: z.array(z.string().trim().min(1)).min(1).max(300)
});

export const importMappingSchema = z.object({
  ticketNumber: z.string().optional(),
  entryDate: z.string().optional(),
  farm: z.string().optional(),
  field: z.string().optional(),
  order: z.string().optional(),
  vehiclePlate: z.string().optional(),
  grossWeight: z.string().optional(),
  netWeight: z.string().optional()
});

export const importOptionsSchema = z.object({
  mapping: importMappingSchema.optional(),
  referenceOrderId: z.string().trim().optional()
});

export const dashboardFilterSchema = z.object({
  batchId: z.string().trim().optional(),
  status: entryStatusSchema.optional(),
  farmId: z.string().trim().optional(),
  year: z.coerce.number().int().min(2000).max(2100).optional(),
  from: z.string().trim().optional(),
  to: z.string().trim().optional(),
  order: z.string().trim().optional(),
  fileName: z.string().trim().optional()
});

const optionalIdSchema = z.preprocess(
  (value) => (typeof value === "string" && value.trim() === "" ? undefined : value),
  z.string().trim().optional()
);





export const fleetMovementInputSchema = z.object({
  movementType: fleetMovementTypeSchema,
  equipmentCode: z.string().trim().min(1),
  equipmentType: fleetEquipmentTypeSchema.default("OUTRO"),
  frontNumber: z.preprocess(
    (value) => (typeof value === "string" && value.trim() === "" ? undefined : value),
    z.coerce.number().int().min(1).max(99).optional()
  ),
  reserveCode: z.string().trim().optional(),
  replacesCode: z.string().trim().optional(),
  reason: z.string().trim().optional(),
  occurredAt: z.string().trim().optional(),
  status: fleetMovementStatusSchema.default("OPEN")
});

export const fleetMovementStatusInputSchema = z.object({
  status: fleetMovementStatusSchema
});

export type LoginInput = z.infer<typeof loginSchema>;
export type CreateFarmInput = z.infer<typeof createFarmSchema>;
export type UpdateFarmInput = z.infer<typeof updateFarmSchema>;
export type CreateFieldInput = z.infer<typeof createFieldSchema>;
export type UpdateFieldInput = z.infer<typeof updateFieldSchema>;
export type CreateOrderInput = z.infer<typeof createOrderSchema>;
export type UpdateOrderInput = z.infer<typeof updateOrderSchema>;
export type BulkCloseOrdersInput = z.infer<typeof bulkCloseOrdersSchema>;
export type ImportMappingInput = z.infer<typeof importMappingSchema>;
export type ImportOptionsInput = z.infer<typeof importOptionsSchema>;
export type DashboardFilterInput = z.infer<typeof dashboardFilterSchema>;

export type FleetMovementInput = z.infer<typeof fleetMovementInputSchema>;
export type FleetMovementStatusInput = z.infer<typeof fleetMovementStatusInputSchema>;
