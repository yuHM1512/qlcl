# Hướng dẫn Deploy Ứng dụng QLCL KPI

## Yêu cầu hệ thống

- Python 3.8+ (khuyến nghị Python 3.11+)
- PostgreSQL 12+
- Windows (để sử dụng `pywin32` cho chức năng Excel to PDF)
- Microsoft Excel hoặc Excel Runtime (để chuyển đổi Excel sang PDF)

## Các bước triển khai

### Bước 1: Copy code sang máy mới

1. Copy toàn bộ thư mục `qlcl` sang máy mới
2. Đảm bảo copy đầy đủ các thư mục và file:
   - `main.py`
   - `requirements.txt`
   - `templates/` (bao gồm file `10.1-bm1.xlsx`)
   - `db/` (chứa các file SQL)
   - Các file khác nếu có

**Lưu ý**: 
- **KHÔNG cần** copy folder `__pycache__` (Python sẽ tự tạo khi chạy)
- **KHÔNG cần** copy các file dữ liệu trong `pdf_files/` và `images/` (trừ khi muốn giữ lại dữ liệu cũ)
- Có thể xóa các file `.pyc` nếu có

### Bước 2: Cài đặt Python và dependencies

1. **Cài đặt Python** (nếu chưa có):
   - Tải từ https://www.python.org/downloads/
   - Chọn "Add Python to PATH" khi cài đặt

2. **Tạo virtual environment** (khuyến nghị):
   ```bash
   cd D:\Data Analyst\Tools\kpi\qlcl
   python -m venv venv
   venv\Scripts\activate
   ```

3. **Cài đặt dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

### Bước 3: Cấu hình Database PostgreSQL

1. **Cài đặt PostgreSQL** (nếu chưa có):
   - Tải từ https://www.postgresql.org/download/windows/
   - Ghi nhớ username và password của PostgreSQL

2. **Tạo database**:
   ```sql
   CREATE DATABASE qlcl;
   ```

3. **Chạy các script SQL** để tạo bảng:
   ```bash
   # Kết nối PostgreSQL và chạy:
   psql -U postgres -d qlcl -f db/initialize_qlcl.sql
   psql -U postgres -d qlcl -f db/create_hdkp_tables.sql
   ```

   Hoặc sử dụng pgAdmin để chạy các file SQL.

### Bước 4: Cấu hình Environment Variables (Bảo mật)

Ứng dụng sử dụng environment variables để lưu cấu hình nhạy cảm. Có 2 cách:

#### Cách 1: Set Environment Variables trong Windows (Khuyến nghị)

1. **Mở System Properties**:
   - Nhấn `Win + R`, gõ `sysdm.cpl` và Enter
   - Hoặc: Settings > System > About > Advanced system settings

2. **Thêm Environment Variables**:
   - Click "Environment Variables"
   - Trong "User variables" hoặc "System variables", click "New"
   - Thêm biến sau:
     - **Variable name**: `DATABASE_URL`
     - **Variable value**: `postgresql://postgres:YOUR_PASSWORD@localhost:5432/qlcl`
       (Thay `YOUR_PASSWORD` bằng password PostgreSQL của bạn)

3. **Các biến tùy chọn** (nếu cần thay đổi đường dẫn mặc định):
   - `TEMPLATES_DIR`: Đường dẫn thư mục templates
   - `EXCEL_TEMPLATE_PATH`: Đường dẫn file template Excel
   - `PDF_STORAGE_DIR`: Đường dẫn lưu PDF
   - `IMAGES_STORAGE_DIR`: Đường dẫn lưu images

4. **Restart** terminal/command prompt sau khi set để áp dụng thay đổi.

#### Cách 2: Set trong Command Prompt (Tạm thời)

```bash
# Set trong session hiện tại (chỉ có hiệu lực trong cửa sổ terminal đó)
set DATABASE_URL=postgresql://postgres:YOUR_PASSWORD@localhost:5432/qlcl

# Sau đó chạy ứng dụng
python main.py
```

#### Cách 3: Tạo file .env (Khuyến nghị - đã được tích hợp sẵn)

**LƯU Ý QUAN TRỌNG**: Tất cả các biến cấu hình là **BẮT BUỘC**. Ứng dụng sẽ không chạy nếu thiếu bất kỳ biến nào.

1. **Copy file mẫu**:
   ```bash
   copy env.example .env
   ```

2. **Chỉnh sửa file `.env`** và cập nhật TẤT CẢ các giá trị:
   ```
   # BẮT BUỘC: Thay YOUR_PASSWORD bằng password PostgreSQL thực tế
   DATABASE_URL=postgresql://postgres:YOUR_PASSWORD@localhost:5432/qlcl
   
   # BẮT BUỘC: Cập nhật các đường dẫn theo vị trí thực tế trên máy của bạn
   TEMPLATES_DIR=D:\Data Analyst\Tools\kpi\qlcl\templates
   EXCEL_TEMPLATE_PATH=D:\Data Analyst\Tools\kpi\qlcl\templates\10.1-bm1.xlsx
   PDF_STORAGE_DIR=D:\Data Analyst\Tools\kpi\qlcl\pdf_files
   IMAGES_STORAGE_DIR=D:\Data Analyst\Tools\kpi\qlcl\images
   ```

3. **Kiểm tra file `.env`**:
   - Đảm bảo tất cả 5 biến đều được set
   - Đảm bảo không có khoảng trắng thừa
   - Đảm bảo đường dẫn đúng với vị trí thực tế

**Lưu ý**: 
- File `.env` đã được tích hợp sẵn trong code (không cần thêm gì)
- Ứng dụng sẽ tự động load file `.env` khi khởi động
- **Nếu thiếu bất kỳ biến nào, ứng dụng sẽ dừng với thông báo lỗi rõ ràng**
- **KHÔNG commit file `.env` vào git** (nếu dùng git)
- Đảm bảo thay `YOUR_PASSWORD` bằng password thực tế của bạn
- Đảm bảo các đường dẫn thư mục đúng với vị trí thực tế trên máy

### Bước 5: Tạo các thư mục cần thiết

Các thư mục sau sẽ được tạo tự động khi chạy ứng dụng, nhưng bạn có thể tạo trước:

```bash
mkdir pdf_files
mkdir images
```

Hoặc đảm bảo các thư mục này tồn tại trong thư mục `qlcl`.

### Bước 6: Kiểm tra file template Excel

Đảm bảo file `templates/10.1-bm1.xlsx` tồn tại và có đầy đủ các biến `{{...}}` cần thiết.

### Bước 7: Import dữ liệu (nếu cần)

Nếu bạn muốn copy dữ liệu từ máy cũ sang máy mới:

1. **Export dữ liệu từ máy cũ**:
   ```bash
   pg_dump -U postgres -d qlcl > backup.sql
   ```

2. **Import vào máy mới**:
   ```bash
   psql -U postgres -d qlcl < backup.sql
   ```

### Bước 8: Chạy ứng dụng

1. **Kích hoạt virtual environment** (nếu có):
   ```bash
   venv\Scripts\activate
   ```

2. **Chạy ứng dụng**:
   ```bash
   python main.py
   ```

   Hoặc:
   ```bash
   .\.venv\Scripts\python.exe -m uvicorn main:app --host 0.0.0.0 --port 8008 --reload
   ```

3. **Kiểm tra ứng dụng**:
   - Mở trình duyệt: http://localhost:8008
   - Kiểm tra các endpoint: http://localhost:8008/healthz

### Bước 9: Cấu hình chạy tự động (tùy chọn)

#### Chạy như Windows Service:

1. Sử dụng **NSSM** (Non-Sucking Service Manager):
   - Tải từ: https://nssm.cc/download
   - Cài đặt service:
     ```bash
     nssm install QLCL_KPI "C:\Python\python.exe" "D:\Data Analyst\Tools\kpi\qlcl\main.py"
     ```

#### Hoặc tạo file batch để khởi động:

Tạo file `start.bat`:
```batch
@echo off
cd /d D:\Data Analyst\Tools\kpi\qlcl
venv\Scripts\activate
python main.py
pause
```

## Kiểm tra và Troubleshooting

### Kiểm tra kết nối database:
```python
python -c "import psycopg2; conn = psycopg2.connect('postgresql://postgres:PASSWORD@localhost:5432/qlcl'); print('OK')"
```

### Kiểm tra dependencies:
```bash
pip list
```

### Lỗi thường gặp:

1. **Lỗi kết nối database**:
   - Kiểm tra PostgreSQL đang chạy
   - Kiểm tra username/password trong `DATABASE_URL`
   - Kiểm tra database `qlcl` đã được tạo

2. **Lỗi import win32com**:
   - Chỉ chạy được trên Windows
   - Cài đặt: `pip install pywin32`
   - Nếu vẫn lỗi, chạy: `python Scripts/pywin32_postinstall.py -install`

3. **Lỗi không tìm thấy file template**:
   - Kiểm tra đường dẫn `EXCEL_TEMPLATE_PATH` trong `main.py`
   - Đảm bảo file `10.1-bm1.xlsx` tồn tại

4. **Lỗi quyền truy cập thư mục**:
   - Đảm bảo ứng dụng có quyền ghi vào `pdf_files` và `images`

## Checklist triển khai

- [ ] Copy code sang máy mới (bỏ qua `__pycache__`, `pdf_files`, `images`)
- [ ] Cài đặt Python 3.8+
- [ ] Cài đặt PostgreSQL
- [ ] Tạo database `qlcl`
- [ ] Chạy các script SQL để tạo bảng
- [ ] Cài đặt dependencies (`pip install -r requirements.txt`)
- [ ] Tạo file `.env` từ `env.example` và cấu hình `DATABASE_URL`
- [ ] Kiểm tra các đường dẫn trong `.env` (hoặc dùng giá trị mặc định)
- [ ] Tạo thư mục `pdf_files` và `images` (hoặc để tự động tạo)
- [ ] Kiểm tra file template Excel tồn tại
- [ ] Import dữ liệu (nếu cần)
- [ ] Chạy ứng dụng và kiểm tra
- [ ] Cấu hình chạy tự động (nếu cần)

## Các folder/file KHÔNG cần copy

- `__pycache__/` - Python tự tạo khi chạy
- `*.pyc` - File bytecode, tự động tạo
- `pdf_files/` - File PDF đã tạo (trừ khi muốn giữ lại)
- `images/` - Hình ảnh đã upload (trừ khi muốn giữ lại)
- `venv/` - Virtual environment (nên tạo mới trên máy mới)
- `excel_files/` - File Excel tạm (nếu có)

## Thông tin kết nối

- **URL ứng dụng**: http://localhost:8008
- **API Health check**: http://localhost:8008/healthz
- **Database**: PostgreSQL, database `qlcl`
- **Port**: 8008 (có thể thay đổi trong `main.py`)


