-- Migration: Add key fields for qc_error_dps
-- Encoding: UTF-8

BEGIN;

ALTER TABLE public.qc_error_dps
    ADD COLUMN IF NOT EXISTS date DATE,
    ADD COLUMN IF NOT EXISTS time_bucket TEXT,
    ADD COLUMN IF NOT EXISTS ma_loi TEXT,
    ADD COLUMN IF NOT EXISTS vi_tri TEXT;

UPDATE public.qc_error_dps
SET date = COALESCE(date, CURRENT_DATE),
    time_bucket = COALESCE(time_bucket, '')
WHERE date IS NULL OR time_bucket IS NULL;

ALTER TABLE public.qc_error_dps
    ALTER COLUMN date SET NOT NULL,
    ALTER COLUMN time_bucket SET NOT NULL;

CREATE INDEX IF NOT EXISTS idx_qc_error_dps_date_bucket ON public.qc_error_dps(date, time_bucket);
CREATE INDEX IF NOT EXISTS idx_qc_error_dps_ma_loi ON public.qc_error_dps(ma_loi);

CREATE UNIQUE INDEX IF NOT EXISTS uq_qc_error_dps_key
ON public.qc_error_dps(plan_id, date, time_bucket, loai_loi, COALESCE(ma_loi, ''), COALESCE(vi_tri, ''));

COMMIT;
