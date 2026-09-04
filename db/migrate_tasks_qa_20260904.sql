-- Migration: refresh KPI task dropdowns for QA roles
-- Encoding: UTF-8

BEGIN;

-- Normalize historical task names that are exact semantic matches in the new list.
UPDATE public.input_qa
SET task_name = 'Xây dựng Control Plan'
WHERE chuc_vu IN ('QAPL', 'QANL')
  AND task_name = 'Xây dựng Control plan';

UPDATE public.input_error
SET task_name = 'Xây dựng Control Plan'
WHERE chuc_vu IN ('QAPL', 'QANL')
  AND task_name = 'Xây dựng Control plan';

UPDATE public.input_qa
SET task_name = 'Họp triển khai sản xuất'
WHERE chuc_vu = 'QAQT'
  AND task_name = 'Họp Triển khai Sản xuất';

UPDATE public.input_error
SET task_name = 'Họp triển khai sản xuất'
WHERE chuc_vu = 'QAQT'
  AND task_name = 'Họp Triển khai Sản xuất';

UPDATE public.input_qa
SET task_name = 'Kiểm pre-final/ Final'
WHERE chuc_vu = 'QAQT'
  AND task_name = 'Kiểm pre - Final/Final';

UPDATE public.input_error
SET task_name = 'Kiểm pre-final/ Final'
WHERE chuc_vu = 'QAQT'
  AND task_name = 'Kiểm pre - Final/Final';

UPDATE public.input_qa
SET task_name = 'Kiểm tra sự tuân thủ QT/ QĐ liên quan đến chất lượng của xí nghiệp'
WHERE chuc_vu = 'QAQT'
  AND task_name = 'Kiểm tra sự tuân thủ QT/QĐ liên quan đến chất lượng của xí nghiệp';

UPDATE public.input_error
SET task_name = 'Kiểm tra sự tuân thủ QT/ QĐ liên quan đến chất lượng của xí nghiệp'
WHERE chuc_vu = 'QAQT'
  AND task_name = 'Kiểm tra sự tuân thủ QT/QĐ liên quan đến chất lượng của xí nghiệp';

UPDATE public.input_qa
SET task_name = 'Gemba Control Plan'
WHERE chuc_vu = 'QAQT'
  AND task_name = 'Gemba control plan';

UPDATE public.input_error
SET task_name = 'Gemba Control Plan'
WHERE chuc_vu = 'QAQT'
  AND task_name = 'Gemba control plan';

DELETE FROM public.tasks_qa
WHERE chuc_vu IN ('QAPL', 'QANL', 'QAQT');

INSERT INTO public.tasks_qa (chuc_vu, task_name) VALUES
('QAQT','Xây dựng control plan'),
('QAQT','Họp triển khai sản xuất'),
('QAQT','Kiểm Endline'),
('QAQT','Kiểm pre-final/ Final'),
('QAQT','Kiểm thùng đầu vào'),
('QAQT','Kiểm tra sự tuân thủ QT/ QĐ liên quan đến chất lượng của xí nghiệp'),
('QAQT','Theo dõi thực hiện HĐKP của xí nghiệp'),
('QAQT','Gemba Control Plan'),
('QANL','Kiểm tra chất lượng lô nguyên liệu'),
('QANL','Kiểm tra % thay thân lỗi'),
('QANL','Xác nhận quyết toán'),
('QANL','Xây dựng Control Plan'),
('QANL','Đánh giá nhà cung ứng'),
('QANL','Gemba Control Plan'),
('QAPL','Kiểm tra chất lượng lô phụ liệu'),
('QAPL','Xây dựng Control Plan'),
('QAPL','Đánh giá nhà cung ứng'),
('QAPL','Gemba Control Plan')
ON CONFLICT (chuc_vu, task_name) DO NOTHING;

COMMIT;
