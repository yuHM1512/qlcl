-- Migration: add station to qc_error_dps and update unique key
-- Encoding: UTF-8

BEGIN;

ALTER TABLE public.qc_error_dps
    ADD COLUMN IF NOT EXISTS station TEXT;

DROP INDEX IF EXISTS uq_qc_error_dps_key;

CREATE UNIQUE INDEX IF NOT EXISTS uq_qc_error_dps_key
ON public.qc_error_dps(plan_id, date, time_bucket, station, loai_loi, COALESCE(ma_loi, ''), COALESCE(vi_tri, ''));

COMMIT;
