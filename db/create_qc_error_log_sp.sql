-- Migration: QC input by product (per-item) + reuse qc_defect
-- Encoding: UTF-8

BEGIN;

-- 1) Master table for product-based QC input
CREATE TABLE IF NOT EXISTS public.qc_error_log_sp (
    id BIGSERIAL PRIMARY KEY,
    plan_id BIGINT REFERENCES public.prod_plan(id) ON DELETE CASCADE,
    date DATE NOT NULL DEFAULT CURRENT_DATE,
    output INTEGER DEFAULT 0,
    defect_count INTEGER DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_qc_error_log_sp_plan_id ON public.qc_error_log_sp(plan_id);
CREATE INDEX IF NOT EXISTS idx_qc_error_log_sp_date ON public.qc_error_log_sp(date);

-- 2) Extend qc_defect to support product-based input
ALTER TABLE public.qc_defect
    ADD COLUMN IF NOT EXISTS error_log_sp_id BIGINT REFERENCES public.qc_error_log_sp(id) ON DELETE CASCADE,
    ADD COLUMN IF NOT EXISTS mo_ta_loi_id INTEGER REFERENCES public.dm_mo_ta_loi(id),
    ADD COLUMN IF NOT EXISTS sp_index INTEGER,
    ADD COLUMN IF NOT EXISTS lap_lai_3 BOOLEAN DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS rework_done BOOLEAN DEFAULT FALSE;

-- Allow qc_defect to be linked either to qc_error_log (time-based) or qc_error_log_sp (product-based)
ALTER TABLE public.qc_defect
    ALTER COLUMN error_log_id DROP NOT NULL;

ALTER TABLE public.qc_defect
    ADD CONSTRAINT IF NOT EXISTS chk_qc_defect_log_ref
    CHECK (
        (error_log_id IS NOT NULL AND error_log_sp_id IS NULL)
        OR (error_log_id IS NULL AND error_log_sp_id IS NOT NULL)
    );

CREATE INDEX IF NOT EXISTS idx_qc_defect_sp_log_id ON public.qc_defect(error_log_sp_id);
CREATE INDEX IF NOT EXISTS idx_qc_defect_sp_index ON public.qc_defect(error_log_sp_id, sp_index);

COMMIT;
