-- Complaint request/creation dates are not due dates.
-- Remove deadlines that were populated from the old automatic mapping while
-- preserving unrelated manually entered deadlines where possible.
BEGIN;

UPDATE public.quality_bulletin_items AS i
SET deadline = NULL,
    updated_at = NOW()
FROM public.bulletin_source_records AS sr
WHERE i.source_record_id = sr.id
  AND i.source_type = 'complaint'
  AND sr.source_type = 'complaint'
  AND i.deadline IS NOT NULL
  AND (
      (sr.source_deadline IS NOT NULL AND i.deadline = sr.source_deadline)
      OR (
          NULLIF(sr.payload ->> 'Ngày yêu cầu làm HĐKP', '') IS NOT NULL
          AND i.deadline = CASE
              WHEN left(sr.payload ->> 'Ngày yêu cầu làm HĐKP', 10) ~ '^\d{2}/\d{2}/\d{4}$'
              THEN to_date(left(sr.payload ->> 'Ngày yêu cầu làm HĐKP', 10), 'DD/MM/YYYY')
          END
      )
  );

-- Ensure the source table cannot reintroduce the old automatic deadline.
UPDATE public.bulletin_source_records
SET source_deadline = NULL,
    synced_at = NOW()
WHERE source_type = 'complaint';

COMMIT;
