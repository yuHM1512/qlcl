-- Migration: add station (jsonb) for QC employees
-- Encoding: UTF-8

BEGIN;

ALTER TABLE public.quality_employees
    ADD COLUMN IF NOT EXISTS station JSONB DEFAULT '[]'::jsonb;

UPDATE public.quality_employees
SET station = '[]'::jsonb
WHERE station IS NULL;

COMMIT;
