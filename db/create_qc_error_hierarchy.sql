-- Migration: Create hierarchical tables for QC Error reporting
-- Encoding: UTF-8

BEGIN;

-- 1. Master Data: Danh má»¥c Target theo PhÃ¢n loáº¡i Loáº¡i hÃ ng
CREATE TABLE IF NOT EXISTS public.dm_loai_hang_target (
    id_type SERIAL PRIMARY KEY,
    type TEXT UNIQUE NOT NULL,
    target_percent NUMERIC(5,2) NOT NULL CHECK (target_percent >= 0),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 2. Master Data: Danh má»¥c Loáº¡i hÃ ng
CREATE TABLE IF NOT EXISTS public.dm_loai_hang (
    id SERIAL PRIMARY KEY,
    ten_loai TEXT UNIQUE NOT NULL,
    id_type INTEGER REFERENCES public.dm_loai_hang_target(id_type),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 3. Master Data: Danh má»¥c Bá»™ pháº­n (thuá»™c Loáº¡i hÃ ng)
CREATE TABLE IF NOT EXISTS public.dm_bo_phan (
    id SERIAL PRIMARY KEY,
    loai_hang_id INTEGER NOT NULL REFERENCES public.dm_loai_hang(id) ON DELETE CASCADE,
    ten_bo_phan TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (loai_hang_id, ten_bo_phan)
);

-- 4. Master Data: Danh má»¥c Chi tiáº¿t (thuá»™c Bá»™ pháº­n)
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

-- Seed target phÃ¢n loáº¡i
INSERT INTO public.dm_loai_hang_target (type, target_percent) VALUES
('Ão Veston', 12),
('Quáº§n Veston/ Gile', 10),
('ThÆ°á»ng', 5)
ON CONFLICT (type) DO UPDATE SET
    target_percent = EXCLUDED.target_percent;

-- Seed some sample data for "Ão vest"
INSERT INTO public.dm_loai_hang (ten_loai, id_type)
VALUES (
    'Ão vest',
    (SELECT id_type FROM public.dm_loai_hang_target WHERE type = 'Ão Veston' LIMIT 1)
)
ON CONFLICT DO NOTHING;

DO $$
DECLARE
    vh_id INTEGER;
    bp_ve_id INTEGER;
BEGIN
    SELECT id INTO vh_id FROM public.dm_loai_hang WHERE ten_loai = 'Ão vest';
    
    IF vh_id IS NOT NULL THEN
        -- Add Bo phan
        INSERT INTO public.dm_bo_phan (loai_hang_id, ten_bo_phan) 
        VALUES (vh_id, 'Ve'), (vh_id, 'Cá»•'), (vh_id, 'ThÃ¢n chÃ­nh trÆ°á»›c')
        ON CONFLICT DO NOTHING;
        
        -- Get Ve ID
        SELECT id INTO bp_ve_id FROM public.dm_bo_phan WHERE loai_hang_id = vh_id AND ten_bo_phan = 'Ve';
        
        IF bp_ve_id IS NOT NULL THEN
            -- Add Chi tiet for Ve
            INSERT INTO public.dm_chi_tiet (bo_phan_id, ten_chi_tiet)
            VALUES (bp_ve_id, 'Ve trÃªn'), (bp_ve_id, 'Ve dÆ°á»›i'), (bp_ve_id, 'GÃ³c ve')
            ON CONFLICT DO NOTHING;
        END IF;
    END IF;
END $$;

COMMIT;
