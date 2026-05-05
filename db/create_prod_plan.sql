-- Migration: Create prod_plan table for QC Inline/Endline module
-- Encoding: UTF-8

BEGIN;

CREATE TABLE IF NOT EXISTS public.prod_plan (
    id BIGSERIAL PRIMARY KEY,
    ke_hoach TEXT,                   -- Nhu cầu sản xuất
    don_vi TEXT NOT NULL,            -- Đơn vị (XN1-V1, XN2, XN3, XNDT, XNV2)
    bo_phan JSONB NOT NULL DEFAULT '[]'::jsonb, -- Bộ phận (list: ["Tổ 1", "Tổ 2", ...])
    khach_hang TEXT,                 -- Khách hàng
    ma_hang TEXT,                    -- Mã hàng
    loai_hang TEXT,                  -- Loại hàng
    ngay_rc DATE,                   -- Ngày rải chuyền
    san_luong INTEGER,              -- Sản lượng
    mau TEXT,                       -- Màu
    size TEXT,                      -- Size
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_prod_plan_don_vi ON public.prod_plan (don_vi);
CREATE INDEX IF NOT EXISTS idx_prod_plan_bo_phan_gin ON public.prod_plan USING GIN (bo_phan);
CREATE INDEX IF NOT EXISTS idx_prod_plan_ngay_rc ON public.prod_plan (ngay_rc);

COMMIT;
