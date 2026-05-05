-- Migration: add ma_nv to QC SP logs
-- Encoding: UTF-8

BEGIN;

ALTER TABLE public.qc_output_sp_log
    ADD COLUMN IF NOT EXISTS ma_nv VARCHAR(16);

ALTER TABLE public.qc_error_log_sp
    ADD COLUMN IF NOT EXISTS ma_nv VARCHAR(16);

ALTER TABLE public.qc_defect_multi
    ADD COLUMN IF NOT EXISTS ma_nv VARCHAR(16);

CREATE INDEX IF NOT EXISTS idx_qc_output_sp_log_ma_nv
    ON public.qc_output_sp_log(ma_nv);

CREATE INDEX IF NOT EXISTS idx_qc_error_log_sp_ma_nv
    ON public.qc_error_log_sp(ma_nv);

CREATE INDEX IF NOT EXISTS idx_qc_defect_multi_ma_nv
    ON public.qc_defect_multi(ma_nv);

COMMIT;
