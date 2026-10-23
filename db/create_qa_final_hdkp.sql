-- HĐKP dành riêng cho Final nội bộ.
-- Không liên kết với input_error/KPI.
BEGIN;

CREATE TABLE IF NOT EXISTS public.qa_final_hdkp (
    id BIGSERIAL PRIMARY KEY,
    inspection_id BIGINT NOT NULL UNIQUE
        REFERENCES public.qa_final_inspection(id) ON UPDATE CASCADE ON DELETE CASCADE,
    created_by VARCHAR(16) NOT NULL REFERENCES public.quality_employees(ma_nv),
    pdf_url TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS public.qa_final_hdkp_mota (
    id BIGSERIAL PRIMARY KEY,
    hdkp_id BIGINT NOT NULL UNIQUE REFERENCES public.qa_final_hdkp(id) ON DELETE CASCADE,
    vd_what TEXT, vd_when TEXT, vd_who TEXT, vd_where TEXT,
    vd_how TEXT, vd_before TEXT, vd_importance TEXT, vd_image TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS public.qa_final_hdkp_kehoach (
    id BIGSERIAL PRIMARY KEY,
    hdkp_id BIGINT NOT NULL REFERENCES public.qa_final_hdkp(id) ON DELETE CASCADE,
    section TEXT NOT NULL, root_cause TEXT, hdkp_tuc_thoi TEXT,
    hd_phong_ngua TEXT, tg_theo_doi TEXT, trach_nhiem TEXT,
    tg_thuc_hien TEXT, thu_tu INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS public.qa_final_hdkp_chitiet (
    id BIGSERIAL PRIMARY KEY,
    hdkp_id BIGINT NOT NULL REFERENCES public.qa_final_hdkp(id) ON DELETE CASCADE,
    cong_viec TEXT, trach_nhiem TEXT, ngay_bat_dau DATE,
    ngay_hoan_thanh DATE, giam_sat TEXT, ket_qua TEXT, ket_luan TEXT,
    thu_tu INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_qa_final_hdkp_kehoach_id ON public.qa_final_hdkp_kehoach(hdkp_id);
CREATE INDEX IF NOT EXISTS idx_qa_final_hdkp_chitiet_id ON public.qa_final_hdkp_chitiet(hdkp_id);
CREATE UNIQUE INDEX IF NOT EXISTS uq_qa_final_hdkp_kehoach_order
    ON public.qa_final_hdkp_kehoach(hdkp_id, section, thu_tu);
CREATE UNIQUE INDEX IF NOT EXISTS uq_qa_final_hdkp_chitiet_order
    ON public.qa_final_hdkp_chitiet(hdkp_id, thu_tu);

-- Migrate previously created Final CAP drafts out of the KPI tables while
-- preserving their content and PDF. The legacy input_error rows remain as
-- audit history and are excluded from KPI queries by the application.
INSERT INTO public.qa_final_hdkp (inspection_id, created_by, pdf_url, created_at, updated_at)
SELECT fi.id, ie.ma_nv, ie.cap_form, COALESCE(ie.created_at, NOW()), COALESCE(ie.created_at, NOW())
FROM public.qa_final_inspection fi
JOIN public.input_error ie ON ie.id = fi.cap_error_id
WHERE fi.cap_error_id IS NOT NULL
  AND COALESCE(ie.ghi_chu, '') LIKE 'Nguồn Final API%'
ON CONFLICT (inspection_id) DO NOTHING;

INSERT INTO public.qa_final_hdkp_mota
    (hdkp_id, vd_what, vd_when, vd_who, vd_where, vd_how, vd_before, vd_importance, vd_image, created_at, updated_at)
SELECT fh.id, cm.vd_what, cm.vd_when, cm.vd_who, cm.vd_where, cm.vd_how,
       cm.vd_before, cm.vd_importance, cm.vd_image, cm.created_at, cm.updated_at
FROM public.qa_final_hdkp fh
JOIN public.qa_final_inspection fi ON fi.id = fh.inspection_id
JOIN public.input_error ie ON ie.id = fi.cap_error_id
JOIN public.cap_mota cm ON cm.error_id = ie.id
ON CONFLICT (hdkp_id) DO NOTHING;

INSERT INTO public.qa_final_hdkp_kehoach
    (hdkp_id, section, root_cause, hdkp_tuc_thoi, hd_phong_ngua, tg_theo_doi,
     trach_nhiem, tg_thuc_hien, thu_tu, created_at, updated_at)
SELECT fh.id, ck.section, ck.root_cause, ck.hdkp_tuc_thoi, ck.hd_phong_ngua,
       ck.tg_theo_doi, ck.trach_nhiem, ck.tg_thuc_hien, ck.thu_tu,
       ck.created_at, ck.updated_at
FROM public.qa_final_hdkp fh
JOIN public.qa_final_inspection fi ON fi.id = fh.inspection_id
JOIN public.input_error ie ON ie.id = fi.cap_error_id
JOIN public.cap_kehoach ck ON ck.error_id = ie.id
ON CONFLICT DO NOTHING;

INSERT INTO public.qa_final_hdkp_chitiet
    (hdkp_id, cong_viec, trach_nhiem, ngay_bat_dau, ngay_hoan_thanh, giam_sat,
     ket_qua, ket_luan, thu_tu, created_at, updated_at)
SELECT fh.id, cc.cong_viec, cc.trach_nhiem, cc.ngay_bat_dau, cc.ngay_hoan_thanh,
       cc.giam_sat, cc.ket_qua, cc.ket_luan, cc.thu_tu, cc.created_at, cc.updated_at
FROM public.qa_final_hdkp fh
JOIN public.qa_final_inspection fi ON fi.id = fh.inspection_id
JOIN public.input_error ie ON ie.id = fi.cap_error_id
JOIN public.cap_chitiet cc ON cc.error_id = ie.id
ON CONFLICT DO NOTHING;

-- These are synthetic KPI rows created by the old Final flow. After the
-- content is copied above, remove them so they cannot reappear in KPI.
DELETE FROM public.input_error
WHERE COALESCE(ghi_chu, '') LIKE 'Nguồn Final API%';

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'update_qa_final_hdkp_updated_at') THEN
        CREATE TRIGGER update_qa_final_hdkp_updated_at BEFORE UPDATE ON public.qa_final_hdkp
        FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
    END IF;
END $$;

COMMIT;
