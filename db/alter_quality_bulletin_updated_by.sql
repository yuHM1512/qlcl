ALTER TABLE public.quality_bulletins
    ADD COLUMN IF NOT EXISTS updated_by TEXT;

UPDATE public.quality_bulletins
SET updated_by = COALESCE(updated_by, created_by)
WHERE updated_by IS NULL;
