-- Grant factory-scoped Final CAP access to the designated QC leaders.

BEGIN;

ALTER TABLE public.quality_employees
    DROP CONSTRAINT IF EXISTS quality_employees_qc_role_check;

ALTER TABLE public.quality_employees
    ADD CONSTRAINT quality_employees_qc_role_check CHECK (
        qc_role IN ('QA_ADMIN', 'FACTORY_ADMIN', 'QC', 'FINAL_CAP')
    );

INSERT INTO public.quality_employees
    (ma_nv, ho_ten, chuc_vu, don_vi, bo_phan, station, qc_role)
VALUES
    ('H3853', 'Nguyễn Thị Hồng', 'QC trưởng', 'XN1-V1', 'QC', '[]'::jsonb, 'FINAL_CAP'),
    ('X0066', 'Hồ Thị Xoa', 'QC trưởng', 'XN2', 'QC', '[]'::jsonb, 'FINAL_CAP'),
    ('Đ0051', 'Phạm Thị Đào', 'QC trưởng', 'XN3', 'QC', '[]'::jsonb, 'FINAL_CAP'),
    ('D9022', 'Hứa Thị Diệu', 'QC trưởng', 'XNDT', 'QC', '[]'::jsonb, 'FINAL_CAP'),
    ('L9003', 'Thái Thị Trương Lài', 'QC trưởng', 'XNDT', 'QC', '[]'::jsonb, 'FINAL_CAP')
ON CONFLICT (ma_nv) DO UPDATE SET
    ho_ten = EXCLUDED.ho_ten,
    chuc_vu = EXCLUDED.chuc_vu,
    don_vi = EXCLUDED.don_vi,
    bo_phan = EXCLUDED.bo_phan,
    qc_role = EXCLUDED.qc_role;

COMMENT ON COLUMN public.quality_employees.qc_role IS
    'Application role. FINAL_CAP can only access Final internal data for the assigned factory.';

COMMIT;
