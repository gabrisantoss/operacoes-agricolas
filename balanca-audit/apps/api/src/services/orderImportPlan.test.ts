import assert from "node:assert/strict";
import test from "node:test";
import type { FarmRecord, HarvestOrderRecord } from "../db.js";
import { buildOrderImportPlan, type OrderImportSourceRow } from "./orderImportPlan.js";

test("order import groups multiple valid sectors into one atomic create action", () => {
  const farm = makeFarm();
  const rows = [row(2, "25001", "0001234", "01"), row(3, "25001", "001-234", "02")];
  const plan = buildOrderImportPlan(rows, { farms: [farm], orders: [] }, "os.xlsx", "a".repeat(64));

  assert.deepEqual(plan.summary, {
    rowCount: 2,
    successCount: 1,
    createCount: 1,
    updateCount: 0,
    skippedCount: 0,
    errorsCount: 0
  });
  assert.equal(plan.actions[0]?.type, "CREATE");
  assert.deepEqual(plan.actions[0]?.input.fieldIds, ["field-1", "field-2"]);
  assert.equal(plan.actions[0]?.input.origin, "EXCEL");
});

test("order import never invents a fallback farm and blocks the whole commit plan on errors", () => {
  const rows = [row(2, "25002", "999999", "01")];
  const plan = buildOrderImportPlan(rows, { farms: [makeFarm()], orders: [] });

  assert.equal(plan.actions.length, 0);
  assert.equal(plan.summary.errorsCount, 1);
  assert.match(plan.errors[0]!, /nenhuma fazenda foi criada automaticamente/i);
});

test("order import preserves existing fields and plans one guarded update", () => {
  const farm = makeFarm();
  const existingOrder = makeOrder(farm, ["field-1"]);
  const rows = [row(2, " 25001 ", "1234", "01"), row(3, "25001", "1234", "02")];
  const plan = buildOrderImportPlan(rows, { farms: [farm], orders: [existingOrder] });

  assert.equal(plan.summary.updateCount, 1);
  assert.equal(plan.summary.skippedCount, 1);
  const action = plan.actions[0];
  assert.equal(action?.type, "UPDATE");
  if (action?.type === "UPDATE") {
    assert.deepEqual(action.expectedFieldIds, ["field-1"]);
    assert.deepEqual(action.input.fieldIds, ["field-1", "field-2"]);
  }
});

test("order import rejects closed orders and inactive sectors", () => {
  const farm = makeFarm();
  farm.fields[1]!.active = false;
  const closedOrder = { ...makeOrder(farm, ["field-1"]), status: "CLOSED" as const };
  const rows = [row(2, "25001", "1234", "01"), row(3, "25002", "1234", "02")];
  const plan = buildOrderImportPlan(rows, { farms: [farm], orders: [closedOrder] });

  assert.equal(plan.actions.length, 0);
  assert.equal(plan.summary.errorsCount, 2);
  assert.ok(plan.errors.some((message) => /esta fechada/i.test(message)));
  assert.ok(plan.errors.some((message) => /esta inativo/i.test(message)));
});

function row(rowNumber: number, orderNumber: string, farmReference: string, fieldReference: string): OrderImportSourceRow {
  return { rowNumber, orderNumber, farmReference, fieldReference };
}

function makeFarm(): FarmRecord {
  return {
    id: "farm-1",
    code: "001-234",
    propertyNumber: "001234",
    name: "Fazenda Teste",
    fields: [
      { id: "field-1", code: "01", farmId: "farm-1", active: true },
      { id: "field-2", code: "02", farmId: "farm-1", active: true }
    ]
  };
}

function makeOrder(farm: FarmRecord, fieldIds: string[]): HarvestOrderRecord {
  return {
    id: "order-1",
    number: "25001",
    frontNumber: 7,
    frontNumbers: [7],
    farmId: farm.id,
    farmIds: [farm.id],
    status: "ACTIVE",
    farm,
    farms: [farm],
    fields: fieldIds.map((fieldId) => ({
      id: `link-${fieldId}`,
      fieldId,
      field: farm.fields.find((field) => field.id === fieldId)!
    }))
  };
}
