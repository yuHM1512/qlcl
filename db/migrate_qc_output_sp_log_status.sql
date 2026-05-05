-- Migration: add status column for qc_output_sp_log
-- Encoding: UTF-8

BEGIN;

ALTER TABLE public.qc_output_sp_log
    ADD COLUMN IF NOT EXISTS status VARCHAR(20) NOT NULL DEFAULT 'Passed';

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'chk_qc_output_sp_log_status'
          AND conrelid = 'public.qc_output_sp_log'::regclass
    ) THEN
        ALTER TABLE public.qc_output_sp_log
            ADD CONSTRAINT chk_qc_output_sp_log_status
                CHECK (status IN ('Passed', 'Failed'));
    END IF;
END $$;

UPDATE public.qc_output_sp_log
SET status = 'Passed'
WHERE status IS NULL OR status = '';

COMMIT;
