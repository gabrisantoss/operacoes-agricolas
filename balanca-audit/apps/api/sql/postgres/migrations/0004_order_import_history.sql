CREATE TABLE IF NOT EXISTS order_import_batches (
  id text PRIMARY KEY,
  file_name text NOT NULL,
  file_hash text NOT NULL,
  source_label text NOT NULL DEFAULT 'EXCEL',
  imported_by_id text REFERENCES users(id),
  imported_at timestamptz NOT NULL DEFAULT now(),
  row_count integer NOT NULL DEFAULT 0,
  create_count integer NOT NULL DEFAULT 0,
  update_count integer NOT NULL DEFAULT 0,
  skipped_count integer NOT NULL DEFAULT 0,
  divergence_count integer NOT NULL DEFAULT 0,
  items_json jsonb NOT NULL DEFAULT '[]'::jsonb,
  divergences_json jsonb NOT NULL DEFAULT '[]'::jsonb
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_order_import_batches_file_hash
  ON order_import_batches(file_hash);

CREATE INDEX IF NOT EXISTS idx_order_import_batches_imported_at
  ON order_import_batches(imported_at DESC);
