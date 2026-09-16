-- Keep HR/KPI positions separate from QC application permissions.
BEGIN;
ALTER TABLE public.quality_employees ADD COLUMN IF NOT EXISTS qc_role TEXT;

-- Run the backfill once, including when this migration is applied manually
-- before the application's schema bootstrap.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'quality_employees_qc_role_check'
                   AND conrelid = 'public.quality_employees'::regclass) THEN
        UPDATE public.quality_employees
        SET qc_role = CASE
            WHEN chuc_vu = 'QAQT' THEN 'QA_ADMIN'
            WHEN chuc_vu IN ('QC', 'FACTORY_MANAGER', 'FACTORY_DIRECTOR') THEN 'QC'
            ELSE NULL
        END
        WHERE qc_role IS NULL;
        ALTER TABLE public.quality_employees
            ADD CONSTRAINT quality_employees_qc_role_check
            CHECK (qc_role IN ('QA_ADMIN', 'FACTORY_ADMIN', 'QC'));

        -- Initial factory administrators explicitly assigned by the business.
        INSERT INTO public.quality_employees
            (ma_nv, ho_ten, chuc_vu, don_vi, bo_phan, station, qc_role)
        VALUES
            ('B0443', 'Lê Viết Bình', 'Điều độ', 'XN3', 'Điều độ', '[]'::jsonb, 'FACTORY_ADMIN'),
            ('H1289', 'Nguyễn Thị Quỳnh Hương', 'Điều độ', 'XN2', 'Điều độ', '[]'::jsonb, 'FACTORY_ADMIN')
        ON CONFLICT (ma_nv) DO UPDATE SET
            ho_ten = EXCLUDED.ho_ten, chuc_vu = EXCLUDED.chuc_vu,
            don_vi = EXCLUDED.don_vi, qc_role = EXCLUDED.qc_role;
    END IF;
END $$;

COMMENT ON COLUMN public.quality_employees.qc_role IS
    'QC application role. NULL means no QC access. FACTORY_ADMIN and QC are scoped by don_vi.';
CREATE INDEX IF NOT EXISTS idx_quality_employees_qc_role ON public.quality_employees(qc_role);
COMMIT;
