-- Add MONo column to prod_plan for hanging-line integration.
-- MONo links QC plans to the hanging conveyor system's Manufacturing Order.

ALTER TABLE public.prod_plan
    ADD COLUMN IF NOT EXISTS mono VARCHAR(100);

-- Partial unique index — only one prod_plan per MONo
CREATE UNIQUE INDEX IF NOT EXISTS uq_prod_plan_mono
    ON public.prod_plan (mono)
    WHERE mono IS NOT NULL;
