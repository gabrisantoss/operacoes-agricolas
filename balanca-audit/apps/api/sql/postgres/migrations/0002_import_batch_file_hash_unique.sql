-- Canonicaliza hashes legados sem excluir lotes ou entradas.
UPDATE import_batches
SET file_hash = NULL
WHERE file_hash IS NOT NULL
  AND btrim(file_hash) = '';

-- Mantem o hash no lote mais antigo; duplicatas historicas continuam auditaveis,
-- mas perdem somente a chave usada para deduplicacao.
WITH ranked_hashes AS (
  SELECT
    id,
    row_number() OVER (
      PARTITION BY lower(btrim(file_hash))
      ORDER BY imported_at ASC, id ASC
    ) AS duplicate_rank
  FROM import_batches
  WHERE file_hash IS NOT NULL
    AND btrim(file_hash) <> ''
)
UPDATE import_batches AS batches
SET file_hash = NULL
FROM ranked_hashes
WHERE batches.id = ranked_hashes.id
  AND ranked_hashes.duplicate_rank > 1;

UPDATE import_batches
SET file_hash = lower(btrim(file_hash))
WHERE file_hash IS NOT NULL
  AND file_hash <> lower(btrim(file_hash));

CREATE UNIQUE INDEX IF NOT EXISTS idx_import_batches_file_hash_unique
  ON import_batches(file_hash)
  WHERE file_hash IS NOT NULL AND btrim(file_hash) <> '';
