import assert from "node:assert/strict";
import test from "node:test";
import { portalIdentityToBalancaRole } from "./accessPolicy.js";

const analystEmails = ["analista@example.invalid"];

test("keeps portal administrators as Balanca administrators", () => {
  assert.equal(
    portalIdentityToBalancaRole({ email: "admin@example.invalid", role: "admin" }, analystEmails),
    "ADMIN"
  );
});

test("maps the configured fictional analyst to operational access", () => {
  assert.equal(
    portalIdentityToBalancaRole({ email: "  analista@example.invalid ", role: "user" }, analystEmails),
    "ANALYST"
  );
});

test("maps the remaining approved portal users to read-only access", () => {
  assert.equal(
    portalIdentityToBalancaRole({ email: "joao@example.invalid", role: "user" }, analystEmails),
    "VIEWER"
  );
});

test("keeps the fictional visitor as a read-only user", () => {
  assert.equal(
    portalIdentityToBalancaRole({ email: "visitante@example.invalid", role: "user" }, analystEmails),
    "VIEWER"
  );
});
