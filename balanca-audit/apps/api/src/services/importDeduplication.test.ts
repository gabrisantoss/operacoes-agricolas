import assert from "node:assert/strict";
import test from "node:test";
import {
  IMPORT_BATCH_FILE_HASH_UNIQUE_INDEX,
  isDuplicateImportFileHashError
} from "./importDeduplication.js";

test("recognizes the PostgreSQL file-hash unique violation without masking unrelated conflicts", () => {
  assert.equal(
    isDuplicateImportFileHashError({ code: "23505", constraint: IMPORT_BATCH_FILE_HASH_UNIQUE_INDEX }),
    true
  );
  assert.equal(isDuplicateImportFileHashError({ code: "23505", constraint: "users_email_key" }), false);
  assert.equal(isDuplicateImportFileHashError(new Error("connection failed")), false);
});
