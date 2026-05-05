-- Migration: Create hierarchical tables for QC Error reporting
-- Encoding: UTF-8

BEGIN;

-- 1. Master Data: Danh mục Target theo Phân loại Loại hàng
CREATE TABLE IF NOT EXISTS public.dm_loai_hang_target (
    id_type SERIAL PRIMARY KEY,
    type TEXT UNIQUE NOT NULL,
    target_percent NUMERIC(5,2) NOT NULL CHECK (target_percent >= 0),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 2. Master Data: Danh mục Loại hàng
CREATE TABLE IF NOT EXISTS public.dm_loai_hang (
    id SERIAL PRIMARY KEY,
    ten_loai TEXT UNIQUE NOT NULL,
    id_type INTEGER REFERENCES public.dm_loai_hang_target(id_type),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 3. Master Data: Danh mục Bộ phận (thuộc Loại hàng)
CREATE TABLE IF NOT EXISTS public.dm_bo_phan (
    id SERIAL PRIMARY KEY,
    loai_hang_id INTEGER NOT NULL REFERENCES public.dm_loai_hang(id) ON DELETE CASCADE,
    ten_bo_phan TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (loai_hang_id, ten_bo_phan)
);

-- 4. Master Data: Danh mục Chi tiết (thuộc Bộ phận)
CREATE TABLE IF NOT EXISTS public.dm_chi_tiet (
    id SERIAL PRIMARY KEY,
    bo_phan_id INTEGER NOT NULL REFERENCES public.dm_bo_phan(id) ON DELETE CASCADE,
    ten_chi_tiet TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (bo_phan_id, ten_chi_tiet)
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_dm_bo_phan_loai_hang_id ON public.dm_bo_phan(loai_hang_id);
CREATE INDEX IF NOT EXISTS idx_dm_chi_tiet_bo_phan_id ON public.dm_chi_tiet(bo_phan_id);

-- Seed target phân loại
INSERT INTO public.dm_loai_hang_target (type, target_percent) VALUES
('Áo Veston', 12),
('Quần Veston/ Gile', 10),
('Thường', 5)
ON CONFLICT (type) DO UPDATE SET
    target_percent = EXCLUDED.target_percent;

-- Seed some sample data for "Áo vest"
INSERT INTO public.dm_loai_hang (ten_loai, id_type)
VALUES (
    'Áo vest',
    (SELECT id_type FROM public.dm_loai_hang_target WHERE type = 'Áo Veston' LIMIT 1)
)
ON CONFLICT DO NOTHING;

DO $$
DECLARE
    vh_id INTEGER;
    bp_ve_id INTEGER;
BEGIN
    SELECT id INTO vh_id FROM public.dm_loai_hang WHERE ten_loai = 'Áo vest';
    
    IF vh_id IS NOT NULL THEN
        -- Add Bo phan
        INSERT INTO public.dm_bo_phan (loai_hang_id, ten_bo_phan) 
        VALUES (vh_id, 'Ve'), (vh_id, 'Cổ'), (vh_id, 'Thân chính trước')
        ON CONFLICT DO NOTHING;
        
        -- Get Ve ID
        SELECT id INTO bp_ve_id FROM public.dm_bo_phan WHERE loai_hang_id = vh_id AND ten_bo_phan = 'Ve';
        
        IF bp_ve_id IS NOT NULL THEN
            -- Add Chi tiet for Ve
            INSERT INTO public.dm_chi_tiet (bo_phan_id, ten_chi_tiet)
            VALUES (bp_ve_id, 'Ve trên'), (bp_ve_id, 'Ve dưới'), (bp_ve_id, 'Góc ve')
            ON CONFLICT DO NOTHING;
        END IF;
    END IF;
END $$;

COMMIT;
