-- Migration: Cache daily MES output pushed from hanging line apps
-- Encoding: UTF-8

BEGIN;

CREATE TABLE IF NOT EXISTS public.qc_hanging_output (
    id BIGSERIAL PRIMARY KEY,
    don_vi VARCHAR(20) NOT NULL,
    mono VARCHAR(100) NOT NULL,
    report_date DATE NOT NULL,
    qty INTEGER NOT NULL DEFAULT 0,
    synced_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_qc_hanging_output_donvi_mono_date
    ON public.qc_hanging_output(don_vi, mono, report_date);

CREATE INDEX IF NOT EXISTS idx_qc_hanging_output_mono_date
    ON public.qc_hanging_output(mono, report_date);

COMMIT;
