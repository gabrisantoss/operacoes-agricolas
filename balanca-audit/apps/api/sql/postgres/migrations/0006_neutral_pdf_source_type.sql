-- Identificador neutro para lotes do relatorio padronizado de pesagem em PDF.
UPDATE import_batches SET source_type = 'CANE_SUMMARY_PDF' WHERE source_type = 'RELPESAG_PDF';
