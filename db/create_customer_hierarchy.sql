-- Migration: Create hierarchical tables for Customer and Product Code
-- Encoding: UTF-8

BEGIN;

-- 1. Master Data: Danh mục Khách hàng
CREATE TABLE IF NOT EXISTS public.dm_khach_hang (
    id SERIAL PRIMARY KEY,
    ten_khach_hang TEXT UNIQUE NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 2. Master Data: Danh mục Mã hàng (thuộc Khách hàng)
CREATE TABLE IF NOT EXISTS public.dm_ma_hang (
    id SERIAL PRIMARY KEY,
    khach_hang_id INTEGER NOT NULL REFERENCES public.dm_khach_hang(id) ON DELETE CASCADE,
    ten_ma_hang TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (khach_hang_id, ten_ma_hang)
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_dm_ma_hang_khach_hang_id ON public.dm_ma_hang(khach_hang_id);

-- Seed some sample data
INSERT INTO public.dm_khach_hang (ten_khach_hang) VALUES ('Client A'), ('Client B') ON CONFLICT DO NOTHING;

DO $$
DECLARE
    client_a_id INTEGER;
BEGIN
    SELECT id INTO client_a_id FROM public.dm_khach_hang WHERE ten_khach_hang = 'Client A';
    
    IF client_a_id IS NOT NULL THEN
        INSERT INTO public.dm_ma_hang (khach_hang_id, ten_ma_hang) 
        VALUES (client_a_id, 'VEST-001'), (client_a_id, 'VEST-002'), (client_a_id, 'PANT-001')
        ON CONFLICT DO NOTHING;
    END IF;
END $$;

COMMIT;
