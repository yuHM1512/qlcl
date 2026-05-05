-- Migration: Log each inspected product (QC output) for product-based input
-- Encoding: UTF-8

BEGIN;

CREATE TABLE IF NOT EXISTS public.qc_output_sp_log (
    id BIGSERIAL PRIMARY KEY,
    plan_id BIGINT NOT NULL REFERENCES public.prod_plan(id) ON DELETE CASCADE,
    date DATE NOT NULL DEFAULT CURRENT_DATE,
    delta SMALLINT NOT NULL CHECK (delta IN (-1, 1)),
    status VARCHAR(20) NOT NULL DEFAULT 'Passed' CHECK (status IN ('Passed', 'Failed')),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_qc_output_sp_log_plan_date ON public.qc_output_sp_log(plan_id, date);

COMMIT;
