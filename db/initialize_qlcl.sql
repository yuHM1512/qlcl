-- Encoding: UTF-8
-- Initialize schema for qlcl: tables ds_qa and tasks_qa, with seed data

BEGIN;

-- Create enum-like constraint via CHECK for chuc_vu
CREATE TABLE IF NOT EXISTS public.ds_qa (
    ma_nv VARCHAR(16) PRIMARY KEY,
    ho_ten TEXT NOT NULL,
    chuc_vu TEXT NOT NULL,
    CONSTRAINT ds_qa_chuc_vu_check CHECK (chuc_vu IN ('QANL','QAPL','QAQT'))
);

CREATE TABLE IF NOT EXISTS public.tasks_qa (
    id SERIAL PRIMARY KEY,
    chuc_vu TEXT NOT NULL,
    task_name TEXT NOT NULL,
    CONSTRAINT tasks_qa_chuc_vu_check CHECK (chuc_vu IN ('QANL','QAPL','QAQT')),
    CONSTRAINT tasks_qa_unique UNIQUE (chuc_vu, task_name)
);

-- Input records from QA members
CREATE TABLE IF NOT EXISTS public.input_qa (
    id BIGSERIAL PRIMARY KEY,
    ma_nv VARCHAR(16) NOT NULL REFERENCES public.ds_qa(ma_nv) ON UPDATE CASCADE ON DELETE RESTRICT,
    chuc_vu TEXT NOT NULL CHECK (chuc_vu IN ('QANL','QAPL','QAQT')),
    from_date DATE NOT NULL,
    to_date DATE NOT NULL,
    task_name TEXT NOT NULL,
    thuc_hien INTEGER NOT NULL CHECK (thuc_hien >= 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT input_qa_date_range CHECK (to_date >= from_date)
);

CREATE INDEX IF NOT EXISTS idx_input_qa_ma_nv_created_at ON public.input_qa (ma_nv, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_input_qa_date_range ON public.input_qa (from_date, to_date);

-- Records for errors/issues captured by QA
CREATE TABLE IF NOT EXISTS public.input_error (
    id BIGSERIAL PRIMARY KEY,
    ma_nv VARCHAR(16) NOT NULL REFERENCES public.ds_qa(ma_nv) ON UPDATE CASCADE ON DELETE RESTRICT,
    chuc_vu TEXT NOT NULL,
    ngay_ghi_nhan DATE,
    task_name TEXT,
    phan_loai_loi TEXT,
    mo_ta TEXT,
    muc_do_anh_huong TEXT,
    huong_giai_quyet TEXT,
    hanh_dong TEXT,
    trach_nhiem TEXT,
    thoi_han DATE,
    tien_do TEXT DEFAULT 'Chưa hoàn thành',
    ngay_hoan_thanh DATE,
    ket_luan TEXT,
    cap_form TEXT,
    ghi_chu TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_input_error_ma_nv ON public.input_error (ma_nv);
CREATE INDEX IF NOT EXISTS idx_input_error_ngay ON public.input_error (ngay_ghi_nhan);

-- Seed ds_qa (idempotent)
INSERT INTO public.ds_qa (ho_ten, ma_nv, chuc_vu) VALUES
('Nguyễn Thị Diệu Thảo','T0154','QAPL'),
('Nguyễn Thị Thanh Châu','C0226','QAPL'),
('Nguyễn Thị Nga','N1780','QAPL'),
('Lê Thị Thanh Diệu','D0847','QAPL'),
('Nguyễn Thị Ánh Tuyết','T4878','QAPL'),
('Nguyễn Thị Phương Thảo','T0223','QANL'),
('Trần Lệ Dung','D0167','QANL'),
('Lê Thị Ngọc Diệp','D0495','QANL'),
('Nguyễn Thị Hồng Vân','V0866','QAQT'),
('Nguyễn Thị Phương Hà','H0854','QAQT'),
('Mai Thị Linh Sương','S0462','QAQT'),
('Lê Thị Kim Chi','C0607','QAQT'),
('Võ Thị Nga','N0230','QAQT'),
('Trần Thị Mai Tuyết','T2405','QAQT'),
('Nguyễn Thị Thu Điệp','Đ0042','QAQT'),
('Huỳnh Thúy Quyên','Q0386','QAQT'),
('Nguyễn Thị Cúc','C0728','QAQT'),
('Ngô Vương Quốc','Q0273','QAQT')
ON CONFLICT (ma_nv) DO UPDATE SET
    ho_ten = EXCLUDED.ho_ten,
    chuc_vu = EXCLUDED.chuc_vu;

-- Seed tasks_qa (idempotent)
-- QAPL tasks
INSERT INTO public.tasks_qa (chuc_vu, task_name) VALUES
('QAPL','Kiểm tra chất lượng lô phụ liệu'),
('QAPL','Làm việc với khách hàng'),
('QAPL','Giải quyết phát sinh trong sản xuất'),
('QAPL','Xây dựng Control plan'),
('QAPL','Kiểm tra sự tuân thủ Control Plan'),
('QAPL','Lập báo cáo và lưu hồ sơ'),
('QAPL','Chuẩn bị cho các đánh giá về chất lượng')
ON CONFLICT (chuc_vu, task_name) DO NOTHING;

-- QANL tasks
INSERT INTO public.tasks_qa (chuc_vu, task_name) VALUES
('QANL','Kiểm tra chất lượng lô nguyên liệu'),
('QANL','Làm việc với khách hàng'),
('QANL','Làm việc với nhà cung ứng'),
('QANL','Giải quyết phát sinh trong sản xuất'),
('QANL','Kiểm tra % thay thân lỗi'),
('QANL','Xác nhận quyết toán'),
('QANL','Xây dựng Control plan'),
('QANL','Gemba Control Plan'),
('QANL','Lập báo cáo và lưu hồ sơ'),
('QANL','Chuẩn bị cho đánh giá chất lượng')
ON CONFLICT (chuc_vu, task_name) DO NOTHING;

-- QAQT tasks
INSERT INTO public.tasks_qa (chuc_vu, task_name) VALUES
('QAQT','Họp Triển khai Sản xuất'),
('QAQT','Kiểm BTP hình in/ thêu gia công'),
('QAQT','Góp ý chất lượng hàng đầu chuyền'),
('QAQT','Kiểm Endline'),
('QAQT','Kiểm packing'),
('QAQT','Kiểm pre - Final/Final'),
('QAQT','Theo dõi thực hiện HĐKP của xí nghiệp'),
('QAQT','Kiểm tra sự tuân thủ QT/QĐ liên quan đến chất lượng của xí nghiệp'),
('QAQT','Báo cáo theo yêu cầu của khách hàng'),
('QAQT','Kiểm mẫu'),
('QAQT','Phối hợp khi khách hàng làm việc tại công ty'),
('QAQT','Xây dựng control plan'),
('QAQT','Gemba control plan'),
('QAQT','Bàn giao khi luân chuyển xí nghiệp'),
('QAQT','Chuẩn bị cho các đánh giá về chất lượng'),
('QAQT','Kiểm thùng đầu vào')
ON CONFLICT (chuc_vu, task_name) DO NOTHING;

COMMIT;
-- Encoding: UTF-8
-- Initialize schema for qlcl: tables ds_qa and tasks_qa, with seed data

BEGIN;

-- Create enum-like constraint via CHECK for chuc_vu
CREATE TABLE IF NOT EXISTS public.ds_qa (
    ma_nv VARCHAR(16) PRIMARY KEY,
    ho_ten TEXT NOT NULL,
    chuc_vu TEXT NOT NULL,
    CONSTRAINT ds_qa_chuc_vu_check CHECK (chuc_vu IN ('QANL','QAPL','QAQT'))
);

CREATE TABLE IF NOT EXISTS public.tasks_qa (
    id SERIAL PRIMARY KEY,
    chuc_vu TEXT NOT NULL,
    task_name TEXT NOT NULL,
    CONSTRAINT tasks_qa_chuc_vu_check CHECK (chuc_vu IN ('QANL','QAPL','QAQT')),
    CONSTRAINT tasks_qa_unique UNIQUE (chuc_vu, task_name)
);

-- Seed ds_qa (idempotent)
INSERT INTO public.ds_qa (ho_ten, ma_nv, chuc_vu) VALUES
('Nguyễn Thị Diệu Thảo','T0154','QAPL'),
('Nguyễn Thị Thanh Châu','C0226','QAPL'),
('Nguyễn Thị Nga','N1780','QAPL'),
('Lê Thị Thanh Diệu','D0847','QAPL'),
('Nguyễn Thị Ánh Tuyết','T4878','QAPL'),
('Nguyễn Thị Phương Thảo','T0223','QANL'),
('Trần Lệ Dung','D0167','QANL'),
('Lê Thị Ngọc Diệp','D0495','QANL'),
('Nguyễn Thị Hồng Vân','V0866','QAQT'),
('Nguyễn Thị Phương Hà','H0854','QAQT'),
('Mai Thị Linh Sương','S0462','QAQT'),
('Lê Thị Kim Chi','C0607','QAQT'),
('Võ Thị Nga','N0230','QAQT'),
('Trần Thị Mai Tuyết','T2405','QAQT'),
('Nguyễn Thị Thu Điệp','Đ0042','QAQT'),
('Huỳnh Thúy Quyên','Q0386','QAQT'),
('Nguyễn Thị Cúc','C0728','QAQT'),
('Ngô Vương Quốc','Q0273','QAQT')
ON CONFLICT (ma_nv) DO UPDATE SET
    ho_ten = EXCLUDED.ho_ten,
    chuc_vu = EXCLUDED.chuc_vu;

-- Seed tasks_qa (idempotent)
-- QAPL tasks
INSERT INTO public.tasks_qa (chuc_vu, task_name) VALUES
('QAPL','Kiểm tra chất lượng lô phụ liệu'),
('QAPL','Làm việc với khách hàng'),
('QAPL','Giải quyết phát sinh trong sản xuất'),
('QAPL','Xây dựng Control plan'),
('QAPL','Kiểm tra sự tuân thủ Control Plan'),
('QAPL','Lập báo cáo và lưu hồ sơ'),
('QAPL','Chuẩn bị cho các đánh giá về chất lượng')
ON CONFLICT (chuc_vu, task_name) DO NOTHING;

-- QANL tasks
INSERT INTO public.tasks_qa (chuc_vu, task_name) VALUES
('QANL','Kiểm tra chất lượng lô nguyên liệu'),
('QANL','Làm việc với khách hàng'),
('QANL','Làm việc với nhà cung ứng'),
('QANL','Giải quyết phát sinh trong sản xuất'),
('QANL','Kiểm tra % thay thân lỗi'),
('QANL','Xác nhận quyết toán'),
('QANL','Xây dựng Control plan'),
('QANL','Gemba Control Plan'),
('QANL','Lập báo cáo và lưu hồ sơ'),
('QANL','Chuẩn bị cho đánh giá chất lượng')
ON CONFLICT (chuc_vu, task_name) DO NOTHING;

-- QAQT tasks
INSERT INTO public.tasks_qa (chuc_vu, task_name) VALUES
('QAQT','Họp Triển khai Sản xuất'),
('QAQT','Kiểm BTP hình in/ thêu gia công'),
('QAQT','Góp ý chất lượng hàng đầu chuyền'),
('QAQT','Kiểm Endline'),
('QAQT','Kiểm packing'),
('QAQT','Kiểm pre - Final/Final'),
('QAQT','Theo dõi thực hiện HĐKP của xí nghiệp'),
('QAQT','Kiểm tra sự tuân thủ QT/QĐ liên quan đến chất lượng của xí nghiệp'),
('QAQT','Báo cáo theo yêu cầu của khách hàng'),
('QAQT','Kiểm mẫu'),
('QAQT','Phối hợp khi khách hàng làm việc tại công ty'),
('QAQT','Xây dựng control plan'),
('QAQT','Gemba control plan'),
('QAQT','Bàn giao khi luân chuyển xí nghiệp'),
('QAQT','Chuẩn bị cho các đánh giá về chất lượng'),
('QAQT','Kiểm thùng đầu vào')
ON CONFLICT (chuc_vu, task_name) DO NOTHING;

COMMIT;

