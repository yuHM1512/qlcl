-- Migration: Table for QC CAP "Nguyen nhan & Hanh dong" form data
-- Encoding: UTF-8

BEGIN;

CREATE TABLE IF NOT EXISTS public.qc_error_dps (
    id BIGSERIAL PRIMARY KEY,
    plan_id BIGINT NOT NULL REFERENCES public.prod_plan(id) ON DELETE CASCADE,
    date DATE NOT NULL,
    time_bucket TEXT NOT NULL,
    bo_phan TEXT,
    loai_loi TEXT NOT NULL,
    ma_loi TEXT,
    vi_tri TEXT,
    -- Nguyen nhan phan loai (checkboxes)
    nn_cong_nhan BOOLEAN DEFAULT FALSE,
    nn_may_moc BOOLEAN DEFAULT FALSE,
    nn_phuong_phap BOOLEAN DEFAULT FALSE,
    nn_nguyen_phu_lieu BOOLEAN DEFAULT FALSE,
    nn_moi_truong BOOLEAN DEFAULT FALSE,
    -- Noi dung form
    mo_ta TEXT,
    giai_phap TEXT,
    tram_ap_dung TEXT,
    tien_do TEXT DEFAULT 'Dang thuc hien',
    ngay_hoan_thanh DATE,
    ket_luan TEXT,
    ghi_chu TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_qc_error_dps_plan_id ON public.qc_error_dps(plan_id);
CREATE INDEX IF NOT EXISTS idx_qc_error_dps_date_bucket ON public.qc_error_dps(date, time_bucket);
CREATE INDEX IF NOT EXISTS idx_qc_error_dps_loai_loi ON public.qc_error_dps(loai_loi);
CREATE INDEX IF NOT EXISTS idx_qc_error_dps_ma_loi ON public.qc_error_dps(ma_loi);

CREATE UNIQUE INDEX IF NOT EXISTS uq_qc_error_dps_key
ON public.qc_error_dps(plan_id, date, time_bucket, bo_phan, loai_loi, COALESCE(ma_loi, ''), COALESCE(vi_tri, ''));

COMMIT;
