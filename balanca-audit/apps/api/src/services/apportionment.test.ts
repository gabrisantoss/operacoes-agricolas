import assert from "node:assert/strict";
import test from "node:test";
import {
  APPORTIONMENT_WEIGHT_UNIT,
  apportionmentFieldMetrics,
  apportionmentResultMetrics,
  calculateApportionments,
  countClosedApportionmentOrders,
  type ApportionmentSourceOrder
} from "./apportionment.js";

test("apportionment summary counts only actually closed orders", () => {
  assert.equal(countClosedApportionmentOrders([
    { status: "CLOSED" },
    { status: "ACTIVE" },
    { status: "CLOSED" },
    { status: null }
  ]), 2);
});

test("apportionment keeps imported cane weights in the canonical metric-ton unit", () => {
  const order = multiFarmOrder();
  const [result] = calculateApportionments(
    [order],
    [
      { order_id: order.id, farm_id: "farm-a", total_weight: 303.84 },
      { order_id: order.id, farm_id: "farm-b", total_weight: 538.38 }
    ],
    []
  );

  assert.equal(result.weightUnit, APPORTIONMENT_WEIGHT_UNIT);
  assert.equal(result.totalWeight, 842.22);
  assert.equal(result.allocatedWeight, 842.22);
  assert.equal(result.unassignedWeight, 0);

  const field = result.fields.find((item) => item.fieldId === "field-a-1")!;
  assert.equal(field.proratedWeight, 75.96);
  const fieldMetrics = apportionmentFieldMetrics(field);
  assert.equal(fieldMetrics.weightTons, 75.96);
  assert.ok(Math.abs(fieldMetrics.tch - 7.596) < 1e-9);

  const metrics = apportionmentResultMetrics(result);
  assert.equal(metrics.weightTons, 842.22);
  assert.equal(metrics.tch, 842.22 / result.totalAreaHa);
});

test("apportionment keeps weights separated when two farms share the same field code", () => {
  const order = multiFarmOrder();
  const [result] = calculateApportionments(
    [order],
    [
      { order_id: order.id, farm_id: "farm-a", total_weight: 100 },
      { order_id: order.id, farm_id: "farm-b", total_weight: 300 }
    ],
    [
      { order_id: order.id, farm_id: "farm-a", field_id: "field-a-1", field_code_raw: "01" },
      { order_id: order.id, farm_id: "farm-b", field_id: "field-b-1", field_code_raw: "01" }
    ]
  );

  assert.equal(result.farms.length, 2);
  assert.equal(result.totalWeight, 400);
  assert.equal(result.unassignedWeight, 0);
  assert.equal(result.farms.find((farm) => farm.farmId === "farm-a")?.fields[0].proratedWeight, 100);
  assert.equal(result.farms.find((farm) => farm.farmId === "farm-b")?.fields[0].proratedWeight, 300);
});

test("apportionment filters harvested fields inside each farm only", () => {
  const order = multiFarmOrder();
  const [result] = calculateApportionments(
    [order],
    [
      { order_id: order.id, farm_id: "farm-a", total_weight: 100 },
      { order_id: order.id, farm_id: "farm-b", total_weight: 300 }
    ],
    [
      { order_id: order.id, farm_id: "farm-a", field_id: "field-a-1", field_code_raw: "01" },
      { order_id: order.id, farm_id: "farm-b", field_id: "field-b-2", field_code_raw: "02" }
    ]
  );

  const farmA = result.farms.find((farm) => farm.farmId === "farm-a")!;
  const farmB = result.farms.find((farm) => farm.farmId === "farm-b")!;
  assert.equal(farmA.fields.find((field) => field.fieldId === "field-a-1")?.proratedWeight, 100);
  assert.equal(farmA.fields.find((field) => field.fieldId === "field-a-2")?.proratedWeight, 0);
  assert.equal(farmB.fields.find((field) => field.fieldId === "field-b-1")?.proratedWeight, 0);
  assert.equal(farmB.fields.find((field) => field.fieldId === "field-b-2")?.proratedWeight, 300);
});

test("weight without farm is only assigned automatically to a single-farm order", () => {
  const order = multiFarmOrder();
  const [multiFarm] = calculateApportionments(
    [order],
    [{ order_id: order.id, farm_id: null, total_weight: 50 }],
    []
  );
  assert.equal(multiFarm.unassignedWeight, 50);

  const singleOrder = { ...order, farms: [order.farms![0]], fields: order.fields.filter((item) => item.field.farmId === "farm-a") };
  const [singleFarm] = calculateApportionments(
    [singleOrder],
    [{ order_id: order.id, farm_id: null, total_weight: 50 }],
    []
  );
  assert.equal(singleFarm.unassignedWeight, 0);
  assert.equal(singleFarm.farms[0].totalWeight, 50);
});

function multiFarmOrder(): ApportionmentSourceOrder {
  const farms = [
    { id: "farm-a", code: "100-0001", name: "Fazenda A" },
    { id: "farm-b", code: "200-0002", name: "Fazenda B" }
  ];
  return {
    id: "order-1",
    number: "25001",
    farm: farms[0],
    farms,
    fields: [
      field("field-a-1", "01", "farm-a", 10),
      field("field-a-2", "02", "farm-a", 30),
      field("field-b-1", "01", "farm-b", 20),
      field("field-b-2", "02", "farm-b", 40)
    ]
  };
}

function field(id: string, code: string, farmId: string, areaHa: number) {
  return { fieldId: id, field: { id, code, farmId, areaHa } };
}
