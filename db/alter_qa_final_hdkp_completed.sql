-- Add completed_at / completed_by to qa_final_hdkp
-- so "Hoàn thành" is an explicit user action, not just PDF presence.
BEGIN;

ALTER TABLE public.qa_final_hdkp
    ADD COLUMN IF NOT EXISTS completed_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS completed_by VARCHAR(16);

-- Back-fill: treat existing rows that already have a PDF as completed.
UPDATE public.qa_final_hdkp
SET completed_at = updated_at, completed_by = created_by
WHERE pdf_url IS NOT NULL AND completed_at IS NULL;

COMMIT;
