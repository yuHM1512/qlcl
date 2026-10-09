-- Internal Final QA data synced from po.hachiba.app
-- Encoding: UTF-8

BEGIN;

CREATE TABLE IF NOT EXISTS public.qa_final_inspection (
    id BIGSERIAL PRIMARY KEY,
    source_history_id BIGINT NOT NULL UNIQUE,
    source_plan_id BIGINT,
    source_plan_delegate_id BIGINT NOT NULL,
    source_po_id BIGINT,
    plan_code TEXT,
    po_code TEXT NOT NULL,
    product_id TEXT,
    fg_model TEXT,
    factory TEXT,
    order_type_code TEXT,
    order_type_display TEXT,
    inspector_name TEXT,
    quantity_pcs INTEGER,
    sample_count INTEGER,
    source_amount_qa_check INTEGER,
    qa_check_date DATE,
    source_created_at TIMESTAMPTZ,
    metal_detection TEXT,
    measurement_result TEXT,
    destructive_measurement_result TEXT,
    appearance_result TEXT,
    quality_status_code TEXT,
    final_status_code TEXT,
    final_status_display TEXT,
    cap_required BOOLEAN NOT NULL DEFAULT FALSE,
    cap_error_id BIGINT UNIQUE REFERENCES public.input_error(id) ON UPDATE CASCADE ON DELETE SET NULL,
    image_urls JSONB NOT NULL DEFAULT '[]'::jsonb,
    raw_data JSONB NOT NULL DEFAULT '{}'::jsonb,
    source_updated_at TIMESTAMPTZ,
    synced_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT qa_final_cap_status_check CHECK (
        cap_required = (final_status_code = '0')
    )
);

CREATE INDEX IF NOT EXISTS idx_qa_final_check_date
    ON public.qa_final_inspection (qa_check_date DESC, source_created_at DESC);
CREATE INDEX IF NOT EXISTS idx_qa_final_factory
    ON public.qa_final_inspection (factory, qa_check_date DESC);
CREATE INDEX IF NOT EXISTS idx_qa_final_po
    ON public.qa_final_inspection (po_code);
CREATE INDEX IF NOT EXISTS idx_qa_final_product
    ON public.qa_final_inspection (product_id);
CREATE INDEX IF NOT EXISTS idx_qa_final_status
    ON public.qa_final_inspection (final_status_code, qa_check_date DESC);
CREATE INDEX IF NOT EXISTS idx_qa_final_cap_pending
    ON public.qa_final_inspection (qa_check_date DESC)
    WHERE cap_required = TRUE AND cap_error_id IS NULL;

CREATE TABLE IF NOT EXISTS public.qa_final_defect (
    id BIGSERIAL PRIMARY KEY,
    inspection_id BIGINT NOT NULL REFERENCES public.qa_final_inspection(id) ON UPDATE CASCADE ON DELETE CASCADE,
    source_defect_id BIGINT,
    error_code TEXT,
    error_name TEXT,
    amount INTEGER NOT NULL DEFAULT 0,
    description TEXT,
    level TEXT,
    raw_data JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT qa_final_defect_source_unique UNIQUE (inspection_id, source_defect_id)
);

CREATE INDEX IF NOT EXISTS idx_qa_final_defect_inspection
    ON public.qa_final_defect (inspection_id);
CREATE INDEX IF NOT EXISTS idx_qa_final_defect_code
    ON public.qa_final_defect (error_code);

CREATE TABLE IF NOT EXISTS public.qa_final_sync_run (
    id BIGSERIAL PRIMARY KEY,
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at TIMESTAMPTZ,
    status TEXT NOT NULL DEFAULT 'running' CHECK (status IN ('running', 'success', 'failed')),
    plans_scanned INTEGER NOT NULL DEFAULT 0,
    delegates_scanned INTEGER NOT NULL DEFAULT 0,
    inspections_upserted INTEGER NOT NULL DEFAULT 0,
    error_message TEXT,
    triggered_by TEXT
);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_trigger WHERE tgname = 'update_qa_final_inspection_updated_at'
    ) THEN
        CREATE TRIGGER update_qa_final_inspection_updated_at
        BEFORE UPDATE ON public.qa_final_inspection
        FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
    END IF;
END $$;

COMMIT;
