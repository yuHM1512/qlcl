-- Migration: Create hierarchical tables for Error Classification
-- Encoding: UTF-8

BEGIN;

-- 1. Master Data: Danh mục Nhóm lỗi
CREATE TABLE IF NOT EXISTS public.dm_nhom_loi (
    id SERIAL PRIMARY KEY,
    ten_nhom TEXT UNIQUE NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 2. Master Data: Danh mục Mã lỗi (thuộc Nhóm lỗi)
CREATE TABLE IF NOT EXISTS public.dm_ma_loi (
    id SERIAL PRIMARY KEY,
    nhom_loi_id INTEGER NOT NULL REFERENCES public.dm_nhom_loi(id) ON DELETE CASCADE,
    ten_ma TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (nhom_loi_id, ten_ma)
);

-- 3. Master Data: Danh mục Mô tả lỗi (thuộc Mã lỗi)
CREATE TABLE IF NOT EXISTS public.dm_mo_ta_loi (
    id SERIAL PRIMARY KEY,
    ma_loi_id INTEGER NOT NULL REFERENCES public.dm_ma_loi(id) ON DELETE CASCADE,
    ten_mo_ta TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (ma_loi_id, ten_mo_ta)
);

-- Index for performance
CREATE INDEX IF NOT EXISTS idx_dm_ma_loi_nhom_id ON public.dm_ma_loi(nhom_loi_id);
CREATE INDEX IF NOT EXISTS idx_dm_mo_ta_loi_ma_id ON public.dm_mo_ta_loi(ma_loi_id);

-- Seed data for "An toàn"
INSERT INTO public.dm_nhom_loi (ten_nhom) VALUES ('An toàn') ON CONFLICT DO NOTHING;

DO $$
DECLARE
    nhom_id INTEGER;
    ma_a1_id INTEGER;
    ma_a2_id INTEGER;
    ma_a3_id INTEGER;
BEGIN
    SELECT id INTO nhom_id FROM public.dm_nhom_loi WHERE ten_nhom = 'An toàn';
    
    IF nhom_id IS NOT NULL THEN
        -- Add Ma loi
        INSERT INTO public.dm_ma_loi (nhom_loi_id, ten_ma) VALUES (nhom_id, 'A1') ON CONFLICT DO NOTHING;
        INSERT INTO public.dm_ma_loi (nhom_loi_id, ten_ma) VALUES (nhom_id, 'A2') ON CONFLICT DO NOTHING;
        INSERT INTO public.dm_ma_loi (nhom_loi_id, ten_ma) VALUES (nhom_id, 'A3') ON CONFLICT DO NOTHING;
        
        -- Get IDs and Add Descriptions
        SELECT id INTO ma_a1_id FROM public.dm_ma_loi WHERE nhom_loi_id = nhom_id AND ten_ma = 'A1';
        IF ma_a1_id IS NOT NULL THEN
            INSERT INTO public.dm_mo_ta_loi (ma_loi_id, ten_mo_ta) VALUES (ma_a1_id, 'Vật sắc nhọn (kim, mạt kim loại…)') ON CONFLICT DO NOTHING;
        END IF;
        
        SELECT id INTO ma_a2_id FROM public.dm_ma_loi WHERE nhom_loi_id = nhom_id AND ten_ma = 'A2';
        IF ma_a2_id IS NOT NULL THEN
            INSERT INTO public.dm_mo_ta_loi (ma_loi_id, ten_mo_ta) VALUES (ma_a2_id, 'Mép sắc nhọn') ON CONFLICT DO NOTHING;
        END IF;
        
        SELECT id INTO ma_a3_id FROM public.dm_ma_loi WHERE nhom_loi_id = nhom_id AND ten_ma = 'A3';
        IF ma_a3_id IS NOT NULL THEN
            INSERT INTO public.dm_mo_ta_loi (ma_loi_id, ten_mo_ta) VALUES (ma_a3_id, 'Độ ẩm vượt chuẩn') ON CONFLICT DO NOTHING;
        END IF;
    END IF;
END $$;

COMMIT;
