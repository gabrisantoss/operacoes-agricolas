import assert from "node:assert/strict";
import test, { after } from "node:test";
import { randomUUID } from "node:crypto";
import { createPostgresTestDatabase } from "./testSupport/postgresTestDatabase.js";

process.env.NODE_ENV = "test";
const testDatabaseUrl = process.env.BALANCA_TEST_DATABASE_URL?.trim();

if (!testDatabaseUrl) {
  test.skip("PostgreSQL integration tests require BALANCA_TEST_DATABASE_URL", () => {});
} else {
  const testDatabase = await createPostgresTestDatabase();
  const { db } = await import("./db.js");

after(async () => {
  await Promise.resolve(db.close?.());
  await testDatabase.cleanup();
});

test("runMany participates in the surrounding transaction", () => {
  const farmId = randomUUID();
  const save = db.transaction(() => {
    db.prepare("INSERT INTO farms (id, code, name) VALUES (?, ?, ?)").run(farmId, "999-9001", "Fazenda rollback");
    db.prepare("INSERT INTO fields (id, code, farm_id) VALUES (?, ?, ?)").runMany([
      [randomUUID(), "01", farmId],
      [randomUUID(), "02", farmId]
    ]);
    throw new Error("falha simulada depois do lote");
  });

  assert.throws(save, /falha simulada/);
  assert.equal(readCount("SELECT COUNT(*) AS count FROM farms WHERE id = ?", farmId), 0);
  assert.equal(readCount("SELECT COUNT(*) AS count FROM fields WHERE farm_id = ?", farmId), 0);
});

test("runMany commits normally outside an explicit transaction", () => {
  const farmId = randomUUID();
  db.prepare("INSERT INTO farms (id, code, name) VALUES (?, ?, ?)").run(farmId, "999-9002", "Fazenda lote");
  const result = db.prepare("INSERT INTO fields (id, code, farm_id) VALUES (?, ?, ?)").runMany([
    [randomUUID(), "01", farmId],
    [randomUUID(), "02", farmId]
  ]);

  assert.equal(result.changes, 2);
  assert.equal(readCount("SELECT COUNT(*) AS count FROM fields WHERE farm_id = ?", farmId), 2);
});

test("nested transactions fail before changing the pinned worker", () => {
  const outer = db.transaction(() => {
    const inner = db.transaction(() => undefined);
    inner();
  });

  assert.throws(outer, /aninhadas nao sao suportadas/);
});

function readCount(sql: string, parameter: string) {
  const row = db.prepare(sql).get(parameter) as { count: number } | undefined;
  return Number(row?.count ?? 0);
}
}
