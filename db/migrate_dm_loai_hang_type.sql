-- Migration: Add dm_loai_hang_target and id_type for dm_loai_hang
-- Encoding: UTF-8

BEGIN;

CREATE TABLE IF NOT EXISTS public.dm_loai_hang_target (
    id_type SERIAL PRIMARY KEY,
    type TEXT UNIQUE NOT NULL,
    target_percent NUMERIC(5,2) NOT NULL CHECK (target_percent >= 0),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

INSERT INTO public.dm_loai_hang_target (type, target_percent) VALUES
('Áo Veston', 12),
('Quần Veston/ Gile', 10),
('Thường', 5)
ON CONFLICT (type) DO UPDATE SET
    target_percent = EXCLUDED.target_percent;

ALTER TABLE public.dm_loai_hang
    ADD COLUMN IF NOT EXISTS id_type INTEGER REFERENCES public.dm_loai_hang_target(id_type);

-- Map existing items to id_type
UPDATE public.dm_loai_hang
SET id_type = (SELECT id_type FROM public.dm_loai_hang_target WHERE type = 'Áo Veston' LIMIT 1)
WHERE id_type IS NULL AND lower(ten_loai) = lower('Áo vest');

UPDATE public.dm_loai_hang
SET id_type = (SELECT id_type FROM public.dm_loai_hang_target WHERE type = 'Quần Veston/ Gile' LIMIT 1)
WHERE id_type IS NULL AND lower(ten_loai) = lower('Quần tây');

UPDATE public.dm_loai_hang
SET id_type = (SELECT id_type FROM public.dm_loai_hang_target WHERE type = 'Thường' LIMIT 1)
WHERE id_type IS NULL AND lower(ten_loai) = lower('Yếm thể thao');

COMMIT;
