ALTER TABLE public.quality_bulletins
    ADD COLUMN IF NOT EXISTS saved_at TIMESTAMPTZ;

UPDATE public.quality_bulletins
SET saved_at = COALESCE(verified_at, updated_at)
WHERE status = 'verified' AND saved_at IS NULL;
