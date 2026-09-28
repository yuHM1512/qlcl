-- Split the combined company/department KPI impact labels.
-- Historical combined values are classified as department impact per business rule.
BEGIN;

UPDATE public.input_error
SET muc_do_anh_huong = CASE BTRIM(muc_do_anh_huong)
    WHEN 'Ảnh hưởng đến MTCL công ty/phòng' THEN 'Ảnh hưởng đến MTCL phòng'
    WHEN 'Chưa ảnh hưởng đến MTCL công ty/phòng' THEN 'Chưa ảnh hưởng đến MTCL phòng'
END
WHERE BTRIM(muc_do_anh_huong) IN (
    'Ảnh hưởng đến MTCL công ty/phòng',
    'Chưa ảnh hưởng đến MTCL công ty/phòng'
);

COMMIT;
