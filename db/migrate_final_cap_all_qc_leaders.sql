-- Grant Final nội bộ CAP access to every QC leader in a supported Final factory.
-- This is intentionally separate from KPI/QAQT permissions.

BEGIN;

ALTER TABLE public.quality_employees
    DROP CONSTRAINT IF EXISTS quality_employees_qc_role_check;

ALTER TABLE public.quality_employees
    ADD CONSTRAINT quality_employees_qc_role_check CHECK (
        qc_role IN ('QA_ADMIN', 'FACTORY_ADMIN', 'QC', 'FINAL_CAP')
    );

UPDATE public.quality_employees
SET qc_role = 'FINAL_CAP'
WHERE lower(trim(chuc_vu)) = lower('QC trưởng')
  AND don_vi IN ('XN1-V1', 'XN2', 'XN3', 'XNDT');

COMMENT ON COLUMN public.quality_employees.qc_role IS
    'Application role. FINAL_CAP can only access Final internal data for the assigned factory.';

COMMIT;
