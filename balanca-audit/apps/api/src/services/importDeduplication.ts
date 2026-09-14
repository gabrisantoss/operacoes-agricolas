export const IMPORT_BATCH_FILE_HASH_UNIQUE_INDEX = "idx_import_batches_file_hash_unique";

export function isDuplicateImportFileHashError(error: unknown) {
  if (!error || typeof error !== "object") return false;

  const postgresError = error as {
    code?: string;
    constraint?: string;
    message?: string;
    detail?: string;
  };
  if (postgresError.code !== "23505") return false;

  return [postgresError.constraint, postgresError.message, postgresError.detail]
    .filter((value): value is string => typeof value === "string")
    .some((value) => value.includes(IMPORT_BATCH_FILE_HASH_UNIQUE_INDEX));
}
