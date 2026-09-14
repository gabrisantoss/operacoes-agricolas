ALTER TABLE harvest_orders
  ADD COLUMN IF NOT EXISTS origin text;

UPDATE harvest_orders
SET origin = 'MANUAL'
WHERE origin IS NULL;

ALTER TABLE harvest_orders
  ALTER COLUMN origin SET DEFAULT 'MANUAL';

ALTER TABLE harvest_orders
  ALTER COLUMN origin SET NOT NULL;

ALTER TABLE cane_entries
  ADD COLUMN IF NOT EXISTS farm_code_raw text;
