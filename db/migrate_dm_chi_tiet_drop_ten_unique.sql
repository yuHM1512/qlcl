-- Drop UNIQUE(bo_phan_id, ten_chi_tiet) on dm_chi_tiet.
-- Reason: with the visual picker, ma_vi_tri (e.g. T4, T6) is the real unique identifier
-- per bo_phan. Some loại hàng have two positions sharing the same display name
-- (e.g. 'Khuy tay' appears at T4 and T6). The old constraint blocked importing them.
-- Idempotent.

BEGIN;

ALTER TABLE public.dm_chi_tiet
    DROP CONSTRAINT IF EXISTS dm_chi_tiet_bo_phan_id_ten_chi_tiet_key;

COMMIT;
