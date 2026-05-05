-- Backfill station + ma_nv for existing QC SP data
-- Encoding: UTF-8

BEGIN;

-- Assign station to QC employee
UPDATE public.quality_employees
SET station = '["Trạm cuối chuyền"]'::jsonb
WHERE ma_nv = 'H3724';

-- Backfill station for existing logs
UPDATE public.qc_output_sp_log
SET station = 'Trạm cuối chuyền'
WHERE station IS NULL OR station = '';

UPDATE public.qc_error_log_sp
SET station = 'Trạm cuối chuyền'
WHERE station IS NULL OR station = '';

UPDATE public.qc_defect_multi
SET station = 'Trạm cuối chuyền'
WHERE station IS NULL OR station = '';

-- Backfill ma_nv for existing logs
UPDATE public.qc_output_sp_log
SET ma_nv = 'H3724'
WHERE ma_nv IS NULL OR ma_nv = '';

UPDATE public.qc_error_log_sp
SET ma_nv = 'H3724'
WHERE ma_nv IS NULL OR ma_nv = '';

UPDATE public.qc_defect_multi
SET ma_nv = 'H3724'
WHERE ma_nv IS NULL OR ma_nv = '';

COMMIT;
