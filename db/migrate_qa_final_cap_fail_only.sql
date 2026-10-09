-- Only FAIL Final inspections require CAP 10.1.
-- Keep any previously linked CAP record for audit history, but no longer mark
-- PASS 2 inspections as requiring corrective action.

BEGIN;

ALTER TABLE public.qa_final_inspection
    DROP CONSTRAINT IF EXISTS qa_final_cap_status_check;

UPDATE public.qa_final_inspection
SET cap_required = (final_status_code = '0')
WHERE cap_required IS DISTINCT FROM (final_status_code = '0');

ALTER TABLE public.qa_final_inspection
    ADD CONSTRAINT qa_final_cap_status_check CHECK (
        cap_required = (final_status_code = '0')
    );

COMMIT;
