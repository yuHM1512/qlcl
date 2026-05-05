-- Migration: Rename ds_qa → quality_employees, add don_vi & bo_phan columns
-- Run this BEFORE deploying updated main.py code
-- Encoding: UTF-8

BEGIN;

-- 1. Rename table
ALTER TABLE public.ds_qa RENAME TO quality_employees;

-- 2. Drop old CHECK constraint on chuc_vu (to allow QC roles in the future)
ALTER TABLE public.quality_employees DROP CONSTRAINT IF EXISTS ds_qa_chuc_vu_check;

-- 3. Add new columns
ALTER TABLE public.quality_employees ADD COLUMN IF NOT EXISTS don_vi TEXT;
ALTER TABLE public.quality_employees ADD COLUMN IF NOT EXISTS bo_phan TEXT;

-- 4. Backfill existing QA rows
UPDATE public.quality_employees
SET don_vi = chuc_vu,
    bo_phan = 'P.QLCL'
WHERE bo_phan IS NULL;

-- 5. Update FK in input_qa: drop old FK, add new FK pointing to quality_employees
ALTER TABLE public.input_qa DROP CONSTRAINT IF EXISTS input_qa_ma_nv_fkey;
ALTER TABLE public.input_qa
    ADD CONSTRAINT input_qa_ma_nv_fkey
    FOREIGN KEY (ma_nv) REFERENCES public.quality_employees(ma_nv)
    ON UPDATE CASCADE ON DELETE RESTRICT;

-- 6. Update FK in input_error: drop old FK, add new FK pointing to quality_employees
ALTER TABLE public.input_error DROP CONSTRAINT IF EXISTS input_error_ma_nv_fkey;
ALTER TABLE public.input_error
    ADD CONSTRAINT input_error_ma_nv_fkey
    FOREIGN KEY (ma_nv) REFERENCES public.quality_employees(ma_nv)
    ON UPDATE CASCADE ON DELETE RESTRICT;

COMMIT;
