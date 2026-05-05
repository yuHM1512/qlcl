-- Drop legacy time-based QC input tables (approved)
-- Encoding: UTF-8

BEGIN;

-- Drop dependent table first
DROP TABLE IF EXISTS public.qc_defect_bp CASCADE;

-- Then drop master log table
DROP TABLE IF EXISTS public.qc_error_log CASCADE;

COMMIT;
