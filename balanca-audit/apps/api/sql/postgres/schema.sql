CREATE TABLE IF NOT EXISTS balanca_schema_migrations (
  version text PRIMARY KEY,
  description text NOT NULL,
  checksum text NOT NULL,
  applied_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS users (
  id text PRIMARY KEY,
  name text NOT NULL,
  email text NOT NULL UNIQUE,
  password_hash text NOT NULL,
  role text NOT NULL DEFAULT 'VIEWER',
  active boolean NOT NULL DEFAULT true,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS farms (
  id text PRIMARY KEY,
  code text UNIQUE,
  name text NOT NULL,
  property_number text,
  sequence_number text,
  area_ha numeric(14, 4),
  area_alq numeric(14, 4),
  street text,
  city text,
  postal_code text,
  section_name text,
  owner_name text,
  municipality text,
  crop_year text,
  total_area_alq numeric(14, 4),
  total_area_ha numeric(14, 4),
  metadata_updated_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS fields (
  id text PRIMARY KEY,
  code text NOT NULL,
  name text,
  farm_id text NOT NULL REFERENCES farms(id) ON DELETE CASCADE,
  area_ha numeric(14, 4),
  area_alq numeric(14, 4),
  planted_area_ha numeric(14, 4),
  crop_year text,
  area_type text,
  active boolean NOT NULL DEFAULT true,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(farm_id, code)
);

CREATE TABLE IF NOT EXISTS harvest_orders (
  id text PRIMARY KEY,
  number text NOT NULL,
  front_number integer,
  farm_id text NOT NULL REFERENCES farms(id),
  status text NOT NULL DEFAULT 'ACTIVE',
  start_date date,
  end_date timestamptz,
  origin TEXT NOT NULL DEFAULT 'MANUAL',
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS harvest_order_fronts (
  id text PRIMARY KEY,
  order_id text NOT NULL REFERENCES harvest_orders(id) ON DELETE CASCADE,
  front_number integer NOT NULL,
  UNIQUE(order_id, front_number)
);

CREATE TABLE IF NOT EXISTS harvest_order_fields (
  id text PRIMARY KEY,
  order_id text NOT NULL REFERENCES harvest_orders(id) ON DELETE CASCADE,
  field_id text NOT NULL REFERENCES fields(id) ON DELETE CASCADE,
  UNIQUE(order_id, field_id)
);

CREATE TABLE IF NOT EXISTS harvest_order_history (
  id text PRIMARY KEY,
  order_id text REFERENCES harvest_orders(id) ON DELETE SET NULL,
  order_number text NOT NULL,
  event_type text NOT NULL,
  front_numbers_before jsonb NOT NULL DEFAULT '[]'::jsonb,
  front_numbers_after jsonb NOT NULL DEFAULT '[]'::jsonb,
  occurred_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS post_harvest_integration_events (
  id text PRIMARY KEY,
  event_id text NOT NULL UNIQUE,
  event_type text NOT NULL,
  order_id text REFERENCES harvest_orders(id) ON DELETE SET NULL,
  order_number text NOT NULL,
  farm_id text REFERENCES farms(id) ON DELETE SET NULL,
  farm_code text,
  farm_name text NOT NULL,
  field_id text REFERENCES fields(id) ON DELETE SET NULL,
  field_code text NOT NULL,
  front_numbers text NOT NULL DEFAULT '[]',
  payload_json text NOT NULL,
  event_version integer NOT NULL DEFAULT 1,
  status text NOT NULL DEFAULT 'PENDING',
  attempt_count integer NOT NULL DEFAULT 0,
  max_attempts integer NOT NULL DEFAULT 8,
  available_at timestamptz NOT NULL DEFAULT now(),
  lease_owner text,
  lease_expires_at timestamptz,
  last_http_status integer,
  last_response_body text,
  last_error text,
  sent_at timestamptz,
  dead_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS background_jobs (
  id text PRIMARY KEY,
  kind text NOT NULL,
  dedupe_key text NOT NULL,
  payload_json jsonb NOT NULL DEFAULT '{}'::jsonb,
  status text NOT NULL DEFAULT 'QUEUED',
  attempt_count integer NOT NULL DEFAULT 0,
  max_attempts integer NOT NULL DEFAULT 5,
  available_at timestamptz NOT NULL DEFAULT now(),
  lease_owner text,
  lease_expires_at timestamptz,
  progress_percent integer NOT NULL DEFAULT 0,
  progress_stage text NOT NULL DEFAULT 'queued',
  progress_message text NOT NULL DEFAULT 'Aguardando processamento.',
  last_error text,
  started_at timestamptz,
  finished_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS fleet_movements (
  id text PRIMARY KEY,
  movement_type text NOT NULL,
  equipment_code text NOT NULL,
  equipment_type text NOT NULL DEFAULT 'OUTRO',
  front_number integer,
  reserve_code text,
  replaces_code text,
  reason text,
  status text NOT NULL DEFAULT 'OPEN',
  occurred_at timestamptz NOT NULL DEFAULT now(),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS import_batches (
  id text PRIMARY KEY,
  file_name text NOT NULL,
  stored_file_name text,
  mime_type text,
  file_size bigint,
  file_hash text,
  source_type text,
  report_date date,
  period_start date,
  period_end date,
  total_net_weight numeric(14, 3),
  total_trips integer,
  imported_by_id text REFERENCES users(id),
  imported_at timestamptz NOT NULL DEFAULT now(),
  row_count integer NOT NULL DEFAULT 0,
  ok_count integer NOT NULL DEFAULT 0,
  error_count integer NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS cane_entries (
  id text PRIMARY KEY,
  batch_id text NOT NULL REFERENCES import_batches(id) ON DELETE CASCADE,
  ticket_number text,
  entry_date date,
  farm_id text REFERENCES farms(id),
  farm_name_raw text,
  farm_code_raw text,
  field_id text REFERENCES fields(id),
  field_code_raw text,
  order_id text REFERENCES harvest_orders(id),
  order_number_raw text,
  vehicle_plate text,
  gross_weight numeric(14, 3),
  net_weight numeric(14, 3),
  status text NOT NULL DEFAULT 'MISSING_DATA',
  notes text,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_cane_entries_status ON cane_entries(status);
CREATE INDEX IF NOT EXISTS idx_cane_entries_entry_date ON cane_entries(entry_date);
CREATE INDEX IF NOT EXISTS idx_cane_entries_batch_id ON cane_entries(batch_id);
CREATE INDEX IF NOT EXISTS idx_farms_code ON farms(code);
CREATE INDEX IF NOT EXISTS idx_fields_farm_code ON fields(farm_id, code);
CREATE INDEX IF NOT EXISTS idx_fields_code ON fields(code);
CREATE INDEX IF NOT EXISTS idx_harvest_orders_number ON harvest_orders(number);
CREATE INDEX IF NOT EXISTS idx_harvest_orders_status ON harvest_orders(status);
CREATE INDEX IF NOT EXISTS idx_harvest_orders_farm_id ON harvest_orders(farm_id);
CREATE INDEX IF NOT EXISTS idx_harvest_order_fronts_front_number ON harvest_order_fronts(front_number);
CREATE INDEX IF NOT EXISTS idx_harvest_order_fields_order_id ON harvest_order_fields(order_id);
CREATE INDEX IF NOT EXISTS idx_harvest_order_fields_field_id ON harvest_order_fields(field_id);
CREATE INDEX IF NOT EXISTS idx_import_batches_period ON import_batches(period_start, period_end, report_date);
CREATE INDEX IF NOT EXISTS idx_import_batches_imported_at ON import_batches(imported_at);
CREATE UNIQUE INDEX IF NOT EXISTS idx_import_batches_file_hash_unique
  ON import_batches(file_hash)
  WHERE file_hash IS NOT NULL AND btrim(file_hash) <> '';
CREATE INDEX IF NOT EXISTS idx_cane_entries_farm_field ON cane_entries(farm_id, field_id);
CREATE INDEX IF NOT EXISTS idx_cane_entries_order_id ON cane_entries(order_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_import_batches_pdf_period_unique
  ON import_batches (
    COALESCE(period_start, report_date),
    COALESCE(period_end, period_start, report_date)
  )
  WHERE (source_type = 'SCS0110P_PDF' OR lower(file_name) LIKE '%.pdf')
    AND COALESCE(period_start, report_date) IS NOT NULL
    AND COALESCE(period_end, period_start, report_date) IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_harvest_order_history_order_id ON harvest_order_history(order_id);
CREATE INDEX IF NOT EXISTS idx_harvest_order_history_occurred_at ON harvest_order_history(occurred_at);
CREATE INDEX IF NOT EXISTS idx_post_harvest_integration_events_status ON post_harvest_integration_events(status);
CREATE INDEX IF NOT EXISTS idx_post_harvest_integration_events_order_id ON post_harvest_integration_events(order_id);
CREATE INDEX IF NOT EXISTS idx_post_harvest_integration_events_created_at ON post_harvest_integration_events(created_at);
CREATE INDEX IF NOT EXISTS idx_post_harvest_dispatch_claim
  ON post_harvest_integration_events(status, available_at, lease_expires_at);
CREATE INDEX IF NOT EXISTS idx_background_jobs_claim
  ON background_jobs(kind, status, available_at, lease_expires_at);
CREATE INDEX IF NOT EXISTS idx_background_jobs_dedupe_history
  ON background_jobs(kind, dedupe_key, created_at DESC);
CREATE UNIQUE INDEX IF NOT EXISTS idx_background_jobs_active_dedupe
  ON background_jobs(kind, dedupe_key)
  WHERE status IN ('QUEUED', 'RETRY', 'RUNNING');
CREATE INDEX IF NOT EXISTS idx_fleet_movements_status ON fleet_movements(status);
CREATE INDEX IF NOT EXISTS idx_fleet_movements_occurred_at ON fleet_movements(occurred_at);
