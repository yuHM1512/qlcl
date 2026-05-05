-- Migration: add image_path for qc_defect (QC SP images)
-- Encoding: UTF-8

BEGIN;

ALTER TABLE public.qc_defect
    ADD COLUMN IF NOT EXISTS image_path TEXT;

CREATE INDEX IF NOT EXISTS idx_qc_defect_image_path ON public.qc_defect(image_path);

COMMIT;
