import assert from "node:assert/strict";
import test, { after } from "node:test";
import bcrypt from "bcryptjs";
import type { Server } from "node:http";
import { createPostgresTestDatabase } from "../testSupport/postgresTestDatabase.js";

process.env.NODE_ENV = "test";
const testDatabaseUrl = process.env.BALANCA_TEST_DATABASE_URL?.trim();

if (!testDatabaseUrl) {
  test(
    "auth integration tests require BALANCA_TEST_DATABASE_URL",
    { skip: "BALANCA_TEST_DATABASE_URL is not configured" },
    () => {}
  );
} else {
  const testDatabase = await createPostgresTestDatabase();
  const { createUser, db } = await import("../db.js");
  const { createApp } = await import("../app.js");
  const email = "visitante@example.invalid";
  createUser({
    id: "login-rate-limit-user",
    name: "Teste Login",
    email,
    passwordHash: await bcrypt.hash("senha-correta-123", 4),
    role: "VIEWER",
    active: true
  });

  const server = await listen(createApp());
  const address = server.address();
  if (!address || typeof address === "string") {
    throw new Error("Servidor de teste nao abriu uma porta TCP.");
  }
  const baseUrl = `http://127.0.0.1:${address.port}`;

  after(async () => {
    await new Promise<void>((resolve) => server.close(() => resolve()));
    await Promise.resolve(db.close?.());
    await testDatabase.cleanup();
  });

  test("account login limit cannot be bypassed by rotating X-Forwarded-For", async () => {
    for (let attempt = 1; attempt <= 6; attempt += 1) {
      const response = await login(`203.0.113.${attempt}`);
      assert.equal(response.status, 401);
    }

    const blocked = await login("198.51.100.200");
    assert.equal(blocked.status, 429);
    assert.ok(Number(blocked.headers.get("retry-after")) > 0);
  });

  function login(forwardedFor: string) {
    return fetch(`${baseUrl}/auth/login`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Forwarded-For": forwardedFor
      },
      body: JSON.stringify({ email, password: "senha-errada-123" })
    });
  }

  function listen(app: ReturnType<typeof createApp>) {
    return new Promise<Server>((resolve, reject) => {
      const candidate = app.listen(0, "127.0.0.1", () => resolve(candidate));
      candidate.on("error", reject);
    });
  }
}
