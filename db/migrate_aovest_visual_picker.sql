-- Migration: add fields for visual position picker (Áo vest pilot)
-- Encoding: UTF-8

BEGIN;

-- 1. Extend dm_bo_phan: nhom + image refs + sort order
ALTER TABLE public.dm_bo_phan
    ADD COLUMN IF NOT EXISTS nhom       VARCHAR(20),
    ADD COLUMN IF NOT EXISTS image_png  VARCHAR(255),
    ADD COLUMN IF NOT EXISTS image_svg  VARCHAR(255),
    ADD COLUMN IF NOT EXISTS sort_order INT DEFAULT 0;

-- 2. Extend dm_chi_tiet: position code + hotspot coords
ALTER TABLE public.dm_chi_tiet
    ADD COLUMN IF NOT EXISTS ma_vi_tri VARCHAR(10),
    ADD COLUMN IF NOT EXISTS x_pct     NUMERIC(7,5),
    ADD COLUMN IF NOT EXISTS y_pct     NUMERIC(7,5),
    ADD COLUMN IF NOT EXISTS w_pct     NUMERIC(7,5),
    ADD COLUMN IF NOT EXISTS h_pct     NUMERIC(7,5),
    ADD COLUMN IF NOT EXISTS rotation  NUMERIC(6,2) DEFAULT 0;

-- 3. Index for picker queries
CREATE INDEX IF NOT EXISTS idx_dm_bo_phan_nhom
    ON public.dm_bo_phan(loai_hang_id, nhom, sort_order);

COMMIT;
