-- Migration: add station to qc_defect_multi
-- Encoding: UTF-8

BEGIN;

ALTER TABLE public.qc_defect_multi
    ADD COLUMN IF NOT EXISTS station TEXT;

CREATE INDEX IF NOT EXISTS idx_qc_defect_multi_plan_date_station
    ON public.qc_defect_multi(plan_id, date, station);

COMMIT;
