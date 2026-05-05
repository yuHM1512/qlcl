-- Migration: HDKP for QC CAP (endline) linked to qc_error_dps
-- Encoding: UTF-8

BEGIN;

ALTER TABLE public.qc_error_dps
    ADD COLUMN IF NOT EXISTS hdkp_pdf TEXT;

CREATE TABLE IF NOT EXISTS public.qc_hdkp_mota (
    id BIGSERIAL PRIMARY KEY,
    qc_error_dps_id BIGINT NOT NULL REFERENCES public.qc_error_dps(id) ON UPDATE CASCADE ON DELETE CASCADE,
    vd_what TEXT,
    vd_when TEXT,
    vd_who TEXT,
    vd_where TEXT,
    vd_how TEXT,
    vd_before TEXT,
    vd_importance TEXT,
    vd_image TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT qc_hdkp_mota_dps_unique UNIQUE (qc_error_dps_id)
);

CREATE INDEX IF NOT EXISTS idx_qc_hdkp_mota_dps_id ON public.qc_hdkp_mota (qc_error_dps_id);

CREATE TABLE IF NOT EXISTS public.qc_hdkp_kehoach (
    id BIGSERIAL PRIMARY KEY,
    qc_error_dps_id BIGINT NOT NULL REFERENCES public.qc_error_dps(id) ON UPDATE CASCADE ON DELETE CASCADE,
    section TEXT NOT NULL CHECK (section IN ('A', 'B')),
    root_cause TEXT,
    hdkp_tuc_thoi TEXT,
    hd_phong_ngua TEXT,
    tg_theo_doi TEXT,
    trach_nhiem TEXT,
    tg_thuc_hien TEXT,
    thu_tu INTEGER DEFAULT 1,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_qc_hdkp_kehoach_dps_id ON public.qc_hdkp_kehoach (qc_error_dps_id);
CREATE INDEX IF NOT EXISTS idx_qc_hdkp_kehoach_section ON public.qc_hdkp_kehoach (qc_error_dps_id, section);

CREATE TABLE IF NOT EXISTS public.qc_hdkp_chitiet (
    id BIGSERIAL PRIMARY KEY,
    qc_error_dps_id BIGINT NOT NULL REFERENCES public.qc_error_dps(id) ON UPDATE CASCADE ON DELETE CASCADE,
    cong_viec TEXT,
    trach_nhiem TEXT,
    ngay_bat_dau DATE,
    ngay_hoan_thanh DATE,
    giam_sat TEXT,
    ket_qua TEXT CHECK (ket_qua IN ('Đạt', 'Không đạt', NULL)),
    ket_luan TEXT,
    thu_tu INTEGER DEFAULT 1,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_qc_hdkp_chitiet_dps_id ON public.qc_hdkp_chitiet (qc_error_dps_id);

-- Triggers cập nhật updated_at (reuse function update_updated_at_column)
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_trigger WHERE tgname = 'update_qc_hdkp_mota_updated_at'
    ) THEN
        CREATE TRIGGER update_qc_hdkp_mota_updated_at BEFORE UPDATE ON public.qc_hdkp_mota
            FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_trigger WHERE tgname = 'update_qc_hdkp_kehoach_updated_at'
    ) THEN
        CREATE TRIGGER update_qc_hdkp_kehoach_updated_at BEFORE UPDATE ON public.qc_hdkp_kehoach
            FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_trigger WHERE tgname = 'update_qc_hdkp_chitiet_updated_at'
    ) THEN
        CREATE TRIGGER update_qc_hdkp_chitiet_updated_at BEFORE UPDATE ON public.qc_hdkp_chitiet
            FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
    END IF;
END $$;

COMMIT;
