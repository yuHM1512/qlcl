BEGIN;

ALTER TABLE public.prod_plan
    ADD COLUMN IF NOT EXISTS source_system TEXT,
    ADD COLUMN IF NOT EXISTS source_record_id TEXT,
    ADD COLUMN IF NOT EXISTS source_status TEXT,
    ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT TRUE,
    ADD COLUMN IF NOT EXISTS last_synced_at TIMESTAMPTZ;

CREATE UNIQUE INDEX IF NOT EXISTS uq_prod_plan_source_record
    ON public.prod_plan (source_system, source_record_id)
    WHERE source_system IS NOT NULL AND source_record_id IS NOT NULL;

UPDATE public.prod_plan
SET is_active = TRUE
WHERE is_active IS NULL;

COMMIT;
