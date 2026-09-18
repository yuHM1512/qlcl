-- Manual completion is independent of the source system's active status.
ALTER TABLE public.prod_plan
    ADD COLUMN IF NOT EXISTS is_finished BOOLEAN NOT NULL DEFAULT FALSE;
