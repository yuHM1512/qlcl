-- Migration: add bo_phan to qc_error_dps and update unique key
-- Encoding: UTF-8

BEGIN;

ALTER TABLE public.qc_error_dps
    ADD COLUMN IF NOT EXISTS bo_phan TEXT;

DROP INDEX IF EXISTS uq_qc_error_dps_key;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM (
            SELECT plan_id, date, time_bucket, station, bo_phan, loai_loi, COALESCE(ma_loi, ''), COALESCE(vi_tri, '')
            FROM public.qc_error_dps
            GROUP BY 1, 2, 3, 4, 5, 6, 7, 8
            HAVING COUNT(*) > 1
        ) dup
    ) THEN
        CREATE UNIQUE INDEX IF NOT EXISTS uq_qc_error_dps_key
        ON public.qc_error_dps(plan_id, date, time_bucket, station, bo_phan, loai_loi, COALESCE(ma_loi, ''), COALESCE(vi_tri, ''));
    ELSE
        RAISE NOTICE 'Skipping uq_qc_error_dps_key with station/bo_phan because duplicate qc_error_dps keys already exist.';
    END IF;
END $$;

COMMIT;
