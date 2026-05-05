-- Migration: Tạo các tables cho HĐKP (Hành động khắc phục phòng ngừa)
-- Encoding: UTF-8

BEGIN;

-- Table I: Mô tả vấn đề (1 row per HĐKP)
CREATE TABLE IF NOT EXISTS public.cap_mota (
    id BIGSERIAL PRIMARY KEY,
    error_id BIGINT NOT NULL REFERENCES public.input_error(id) ON UPDATE CASCADE ON DELETE CASCADE,
    vd_what TEXT,                    -- Vấn đề gì đã xảy ra?
    vd_when TEXT,                    -- Vấn đề phát hiện ra khi nào?
    vd_who TEXT,                     -- Ai là người phát hiện ra vấn đề?
    vd_where TEXT,                   -- Vấn đề xảy ra ở đâu? Bộ phận nào?
    vd_how TEXT,                     -- Vấn đề xảy ra như thế nào? Mô tả tình huống
    vd_before TEXT,                  -- Vấn đề đã từng xảy ra chưa?
    vd_importance TEXT,              -- Tại sao vấn đề này lại nghiêm trọng?
    vd_image TEXT,                   -- Hình ảnh, nếu có (URL hoặc path)
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT cap_mota_error_id_unique UNIQUE (error_id)
);

CREATE INDEX IF NOT EXISTS idx_cap_mota_error_id ON public.cap_mota (error_id);

-- Table II: Kế hoạch khắc phục, phòng ngừa (nhiều rows per HĐKP)
CREATE TABLE IF NOT EXISTS public.cap_kehoach (
    id BIGSERIAL PRIMARY KEY,
    error_id BIGINT NOT NULL REFERENCES public.input_error(id) ON UPDATE CASCADE ON DELETE CASCADE,
    section TEXT NOT NULL CHECK (section IN ('A', 'B')),  -- A: Tại sao xảy ra, B: Tại sao không phát hiện
    root_cause TEXT,                 -- Nguyên nhân cuối cùng
    hdkp_tuc_thoi TEXT,              -- Hành động khắc phục tức thời
    hd_phong_ngua TEXT,              -- Hành động phòng ngừa
    tg_theo_doi TEXT,                -- Thời gian theo dõi
    trach_nhiem TEXT,                -- Trách nhiệm thực hiện
    tg_thuc_hien TEXT,               -- Thời gian thực hiện (từ…đến)
    thu_tu INTEGER DEFAULT 1,        -- Thứ tự của ý trong section
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_cap_kehoach_error_id ON public.cap_kehoach (error_id);
CREATE INDEX IF NOT EXISTS idx_cap_kehoach_section ON public.cap_kehoach (error_id, section);

-- Table III: Chi tiết kế hoạch (To Do List) (nhiều rows per HĐKP)
CREATE TABLE IF NOT EXISTS public.cap_chitiet (
    id BIGSERIAL PRIMARY KEY,
    error_id BIGINT NOT NULL REFERENCES public.input_error(id) ON UPDATE CASCADE ON DELETE CASCADE,
    cong_viec TEXT,                  -- Công việc cụ thể
    trach_nhiem TEXT,                -- Trách nhiệm thực hiện
    ngay_bat_dau DATE,               -- Ngày bắt đầu
    ngay_hoan_thanh DATE,            -- Ngày hoàn thành
    giam_sat TEXT,                   -- Trách nhiệm giám sát, báo cáo
    ket_qua TEXT CHECK (ket_qua IN ('Đạt', 'Không đạt', NULL)),  -- Kết quả kiểm tra, giám sát
    ket_luan TEXT,                   -- Kết luận
    thu_tu INTEGER DEFAULT 1,       -- Thứ tự công việc
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_cap_chitiet_error_id ON public.cap_chitiet (error_id);

-- Function để tự động cập nhật updated_at
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

-- Triggers để tự động cập nhật updated_at
CREATE TRIGGER update_cap_mota_updated_at BEFORE UPDATE ON public.cap_mota
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_cap_kehoach_updated_at BEFORE UPDATE ON public.cap_kehoach
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_cap_chitiet_updated_at BEFORE UPDATE ON public.cap_chitiet
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

COMMIT;

