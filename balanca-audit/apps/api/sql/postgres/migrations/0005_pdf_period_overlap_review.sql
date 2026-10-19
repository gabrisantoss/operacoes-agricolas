-- A period alone does not prove a repeated report: PDFs of the same period with different farms/fields are
-- legitimate. Repetition is now checked by file hash (unique index kept) and by the content overlap review.
DROP INDEX IF EXISTS idx_import_batches_pdf_period_unique;
