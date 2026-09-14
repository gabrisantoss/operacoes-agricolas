export type ApportionmentSourceOrder = {
  id: string;
  number: string;
  farm: ApportionmentSourceFarm;
  farms?: ApportionmentSourceFarm[];
  fields: Array<{
    fieldId: string;
    field: {
      id: string;
      code: string;
      areaHa?: number | null;
      farmId: string;
    };
  }>;
};

type ApportionmentSourceFarm = {
  id: string;
  code?: string | null;
  name: string;
};

export type ApportionmentWeightRow = {
  order_id: string;
  farm_id: string | null;
  /** Canonical persisted cane weight unit: metric tons (t). */
  total_weight: number;
};

export const APPORTIONMENT_WEIGHT_UNIT = "t" as const;

export type ApportionmentHarvestedFieldRow = {
  order_id: string;
  farm_id: string | null;
  field_id: string | null;
  field_code_raw: string | null;
};

export type ApportionmentFieldResult = {
  fieldId: string;
  fieldCode: string;
  farmId: string;
  farmCode: string;
  farmName: string;
  areaHa: number;
  percentage: number;
  farmPercentage: number;
  /** Metric tons (t). */
  proratedWeight: number;
  harvested: boolean;
};

export type ApportionmentFarmResult = {
  farmId: string;
  farmCode: string;
  farmName: string;
  totalAreaHa: number;
  /** Metric tons (t). */
  totalWeight: number;
  fields: ApportionmentFieldResult[];
};

export type ApportionmentResult = {
  orderId: string;
  orderNumber: string;
  farmName: string;
  farmCode: string;
  weightUnit: typeof APPORTIONMENT_WEIGHT_UNIT;
  totalAreaHa: number;
  /** Metric tons (t). */
  totalWeight: number;
  /** Metric tons (t). */
  allocatedWeight: number;
  /** Metric tons (t). */
  unassignedWeight: number;
  farms: ApportionmentFarmResult[];
  fields: ApportionmentFieldResult[];
};

export function calculateApportionments(
  orders: ApportionmentSourceOrder[],
  weightRows: ApportionmentWeightRow[],
  harvestedRows: ApportionmentHarvestedFieldRow[]
): ApportionmentResult[] {
  const weightsByOrder = groupBy(weightRows, (row) => row.order_id);
  const harvestedByOrder = groupBy(harvestedRows, (row) => row.order_id);

  return orders.map((order) => calculateOrderApportionment(
    order,
    weightsByOrder.get(order.id) ?? [],
    harvestedByOrder.get(order.id) ?? []
  ));
}

function calculateOrderApportionment(
  order: ApportionmentSourceOrder,
  weightRows: ApportionmentWeightRow[],
  harvestedRows: ApportionmentHarvestedFieldRow[]
): ApportionmentResult {
  const fieldsByFarm = groupBy(order.fields, (item) => item.field.farmId);
  const knownFarms = new Map((order.farms?.length ? order.farms : [order.farm]).map((farm) => [farm.id, farm]));
  knownFarms.set(order.farm.id, order.farm);
  const singleFarmId = fieldsByFarm.size === 1 ? fieldsByFarm.keys().next().value as string | undefined : undefined;
  const normalizedWeights = weightRows.map((row) => ({
    ...row,
    farm_id: row.farm_id ?? singleFarmId ?? null,
    total_weight: asCaneWeightTons(row.total_weight)
  }));
  const totalWeight = normalizedWeights.reduce((sum, row) => sum + row.total_weight, 0);
  const farms: ApportionmentFarmResult[] = [];

  for (const [farmId, orderFields] of fieldsByFarm) {
    const farm = knownFarms.get(farmId) ?? { id: farmId, code: "", name: "Fazenda removida" };
    const fieldIds = new Set(orderFields.map((item) => item.field.id));
    const farmHarvestedRows = harvestedRows.filter((row) => row.farm_id === farmId || Boolean(row.field_id && fieldIds.has(row.field_id)));
    const harvestedFieldIds = new Set(farmHarvestedRows.map((row) => row.field_id).filter((value): value is string => Boolean(value)));
    const harvestedCodes = new Set(farmHarvestedRows.map((row) => normalizeFieldCode(row.field_code_raw)).filter(Boolean));
    const filterToHarvested = harvestedFieldIds.size > 0 || harvestedCodes.size > 0;
    const farmWeight = normalizedWeights
      .filter((row) => row.farm_id === farmId)
      .reduce((sum, row) => sum + row.total_weight, 0);
    const fieldStates = orderFields.map((item) => {
      const harvested = !filterToHarvested || harvestedFieldIds.has(item.field.id) || harvestedCodes.has(normalizeFieldCode(item.field.code));
      return {
        item,
        harvested,
        areaHa: positiveNumber(item.field.areaHa)
      };
    });
    const totalAreaHa = fieldStates.reduce((sum, state) => sum + (state.harvested ? state.areaHa : 0), 0);
    const fields = fieldStates.map<ApportionmentFieldResult>((state) => {
      const farmPercentage = state.harvested && totalAreaHa > 0 ? state.areaHa / totalAreaHa : 0;
      const proratedWeight = farmPercentage * farmWeight;
      return {
        fieldId: state.item.field.id,
        fieldCode: state.item.field.code,
        farmId,
        farmCode: farm.code ?? "",
        farmName: farm.name,
        areaHa: state.areaHa,
        percentage: totalWeight > 0 ? proratedWeight / totalWeight : 0,
        farmPercentage,
        proratedWeight,
        harvested: state.harvested
      };
    });

    farms.push({
      farmId,
      farmCode: farm.code ?? "",
      farmName: farm.name,
      totalAreaHa,
      totalWeight: farmWeight,
      fields
    });
  }

  farms.sort((left, right) => left.farmCode.localeCompare(right.farmCode, "pt-BR", { numeric: true }) || left.farmName.localeCompare(right.farmName, "pt-BR"));
  const fields = farms.flatMap((farm) => farm.fields);
  const allocatedWeight = farms.reduce((sum, farm) => sum + farm.totalWeight, 0);

  return {
    orderId: order.id,
    orderNumber: order.number,
    farmName: farms.length === 1 ? farms[0].farmName : `${farms.length} fazendas`,
    farmCode: farms.length === 1 ? farms[0].farmCode : farms.map((farm) => farm.farmCode).filter(Boolean).join(", "),
    weightUnit: APPORTIONMENT_WEIGHT_UNIT,
    totalAreaHa: farms.reduce((sum, farm) => sum + farm.totalAreaHa, 0),
    totalWeight,
    allocatedWeight,
    unassignedWeight: Math.max(0, totalWeight - allocatedWeight),
    farms,
    fields
  };
}

export function asCaneWeightTons(value: unknown) {
  const parsed = Number(value ?? 0);
  return Number.isFinite(parsed) ? parsed : 0;
}

export function calculateTonsPerHectare(weightTons: number, areaHa: number) {
  return areaHa > 0 ? weightTons / areaHa : 0;
}

export function countClosedApportionmentOrders(orders: Array<{ status?: string | null }>) {
  return orders.filter((order) => order.status === "CLOSED").length;
}

export function apportionmentFieldMetrics(field: Pick<ApportionmentFieldResult, "proratedWeight" | "areaHa">) {
  const weightTons = asCaneWeightTons(field.proratedWeight);
  return {
    weightTons,
    tch: calculateTonsPerHectare(weightTons, field.areaHa)
  };
}

export function apportionmentResultMetrics(
  result: Pick<ApportionmentResult, "allocatedWeight" | "totalAreaHa" | "unassignedWeight">
) {
  const weightTons = asCaneWeightTons(result.allocatedWeight);
  return {
    weightTons,
    unassignedWeightTons: asCaneWeightTons(result.unassignedWeight),
    tch: calculateTonsPerHectare(weightTons, result.totalAreaHa)
  };
}

function normalizeFieldCode(value: unknown) {
  return String(value ?? "").trim().replace(/^0+(?=\d)/, "");
}

function positiveNumber(value: unknown) {
  const parsed = Number(value ?? 0);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : 0;
}

function groupBy<T>(items: T[], keyFor: (item: T) => string) {
  const groups = new Map<string, T[]>();
  for (const item of items) {
    const key = keyFor(item);
    const current = groups.get(key);
    if (current) {
      current.push(item);
    } else {
      groups.set(key, [item]);
    }
  }
  return groups;
}
