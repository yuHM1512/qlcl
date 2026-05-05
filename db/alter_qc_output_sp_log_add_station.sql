-- Migration: add station to qc_output_sp_log and qc_error_log_sp
-- Encoding: UTF-8

BEGIN;

ALTER TABLE public.qc_output_sp_log
    ADD COLUMN IF NOT EXISTS station TEXT;

ALTER TABLE public.qc_error_log_sp
    ADD COLUMN IF NOT EXISTS station TEXT;

CREATE INDEX IF NOT EXISTS idx_qc_output_sp_log_plan_date_station
    ON public.qc_output_sp_log(plan_id, date, station);

CREATE INDEX IF NOT EXISTS idx_qc_error_log_sp_plan_date_station
    ON public.qc_error_log_sp(plan_id, date, station);

COMMIT;
