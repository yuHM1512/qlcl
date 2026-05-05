-- Migration: convert prod_plan.bo_phan from TEXT to JSONB array
-- Encoding: UTF-8

BEGIN;

-- 1) Add temp jsonb column
ALTER TABLE public.prod_plan
    ADD COLUMN IF NOT EXISTS bo_phan_json JSONB;

-- 2) Backfill from existing text values
UPDATE public.prod_plan
SET bo_phan_json = CASE
    WHEN bo_phan IS NULL OR btrim(bo_phan) = '' THEN '[]'::jsonb
    ELSE (
        SELECT to_jsonb(
            array_remove(
                array_agg(trim(x)),
                ''
            )
        )
        FROM regexp_split_to_table(
            replace(bo_phan, ';', ','),
            ','
        ) AS x
    )
END
WHERE bo_phan_json IS NULL;

-- 3) Replace old column
ALTER TABLE public.prod_plan DROP COLUMN IF EXISTS bo_phan;
ALTER TABLE public.prod_plan RENAME COLUMN bo_phan_json TO bo_phan;

-- 4) Indexes
CREATE INDEX IF NOT EXISTS idx_prod_plan_don_vi ON public.prod_plan (don_vi);
CREATE INDEX IF NOT EXISTS idx_prod_plan_bo_phan_gin ON public.prod_plan USING GIN (bo_phan);

COMMIT;
