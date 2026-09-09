-- Migration: refresh KPI error classification dropdown labels
-- Encoding: UTF-8

BEGIN;

UPDATE public.input_error
SET phan_loai_loi = 'Không có khiếu nại khách hàng do sai sót của nhân viên'
WHERE phan_loai_loi = 'Khiếu nại có phạt tiền';

COMMIT;
