-- Migration: Add image_path column to qc_defect for product photo evidence
-- Encoding: UTF-8

BEGIN;

ALTER TABLE public.qc_defect
    ADD COLUMN IF NOT EXISTS image_path TEXT;

COMMENT ON COLUMN public.qc_defect.image_path IS 'Path to defect photo, relative to images storage dir (e.g. qc_sp/filename.jpg)';

COMMIT;
