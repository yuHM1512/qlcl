# DEPLOY.md — App QLCL KPI (server trung tâm)

Hướng dẫn triển khai app QLCL từ đầu đến khi chạy được, bao gồm cấu hình tích hợp multi-factory với các app chuyền treo (XN1, XN2, XN3...).

---

## Kiến trúc tổng quan

```
[XN1 - hanging_line_factory]  ──PUSH kế hoạch──┐
[XN2 - hanging_line_factory]  ──PUSH kế hoạch──┤──▶  [QLCL server - qlcl.hachibavn.com]
[XN3 - hanging_line_factory]  ──PUSH kế hoạch──┘         │  PostgreSQL
                                                           │
[TV-3 tại mỗi XN] ──GET /api/tv3/qc-data ───────────────▶┘
```

- Mỗi XN chạy app `hanging_line_factory` riêng, kết nối SQL Server riêng.
- QLCL server chạy tập trung, nhận kế hoạch PUSH từ các XN, lưu vào PostgreSQL.
- TV-3 tại mỗi XN lấy dữ liệu QC từ QLCL server qua API.

---

## Yêu cầu hệ thống

| Thành phần | Phiên bản |
|---|---|
| Python | 3.11+ |
| PostgreSQL | 14+ |
| Windows | 10 / 11 / Server (nếu cần Excel→PDF) |
| Linux | Ubuntu 22.04+ (nếu không cần Excel→PDF) |

---

## Bước 1 — Lấy code

```powershell
git clone https://github.com/<org>/qlcl.git
cd qlcl

# Hoặc cập nhật
git pull origin main
```

---

## Bước 2 — Tạo virtual environment & cài thư viện

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1   # Windows
# source .venv/bin/activate    # Linux

pip install -r requirements.txt
```

---

## Bước 3 — Cấu hình môi trường (.env)

```powershell
Copy-Item env.example .env
notepad .env
```

### Các biến bắt buộc

```env
# PostgreSQL — thay password thực tế
DATABASE_URL=postgresql://postgres:MAT_KHAU@localhost:5432/qlcl
PROD_FACTORY_DATABASE_URL=postgresql://postgres:MAT_KHAU@localhost:5432/prod_factory
GEMBA_CP_DATABASE_URL=postgresql+psycopg://postgres:MAT_KHAU@localhost:5432/gemba_cp

# Đường dẫn thư mục — sửa theo đường dẫn thực tế trên server
TEMPLATES_DIR=D:\KPI\qlcl\templates
EXCEL_TEMPLATE_PATH=D:\KPI\qlcl\templates\10.1-bm1.xlsx
PDF_STORAGE_DIR=D:\KPI\qlcl\pdf_files
IMAGES_STORAGE_DIR=D:\KPI\qlcl\images
```

### Cấu hình API key cho multi-factory (production)

```env
# Tạo key ngẫu nhiên (chạy 1 lần):
#   python -c "import secrets; print(secrets.token_urlsafe(32))"
# Ví dụ output: T8kXmN2pQr9vYzA4cLwE6tJ_bF1sH3dIo-vKG5

QLCL_API_KEY=<key_vua_tao>
```

**Sau đó** copy đúng key này vào `.env` của từng app XN (`QLCL_API_KEY=<key_vua_tao>`).

### Chú ý: biến KHÔNG cần trong production

```env
# XÓA hoặc comment các dòng này trong production.
# Chỉ dùng khi dev local (QLCL và hanging line cùng máy, dùng PULL sync cũ).
# HANGING_LINE_SQL_SERVER=.\SQLEXPRESS
# HANGING_LINE_APP_DB=hanging_app
# HANGING_LINE_SQL_DRIVER=ODBC Driver 17 for SQL Server
```

---

## Bước 4 — Tạo database PostgreSQL

```powershell
# Tạo database (chạy 1 lần)
psql -U postgres -c "CREATE DATABASE qlcl;"
psql -U postgres -c "CREATE DATABASE prod_factory;"
psql -U postgres -c "CREATE DATABASE gemba_cp;"

# Chạy migration khởi tạo bảng
psql -U postgres -d qlcl -f db\initialize_qlcl.sql
psql -U postgres -d qlcl -f db\create_hdkp_tables.sql
# (chạy lần lượt các file trong db/ theo thứ tự prefix số nếu có)
```

Migration có thể chạy lại an toàn (idempotent với `IF NOT EXISTS`).

---

## Bước 5 — Khởi động app

```powershell
.\.venv\Scripts\Activate.ps1
uvicorn main:app --host 0.0.0.0 --port 8008 --reload
```

App chạy tại: **http://localhost:8008** (hoặc public URL nếu có reverse proxy).

---

## Bước 6 — Xác nhận tích hợp TV-3

Sau khi một app XN đã đồng bộ kế hoạch, kiểm tra:

```
GET https://qlcl.hachibavn.com/api/tv3/qc-data?mono=<MONo>&date=<YYYY-MM-DD>
```

Kết quả mong đợi: JSON có `"found": true` (nếu đã có dữ liệu QC) hoặc `"found": false` (kế hoạch tồn tại nhưng chưa có lỗi nhập).

---

## Cập nhật code

```powershell
# 1. Backup dữ liệu
Copy-Item .env .env.bak
pg_dump -U postgres qlcl > qlcl_backup_$(Get-Date -Format "yyyyMMdd").sql

# 2. Pull code mới
git pull origin main

# 3. Cài thêm thư viện
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# 4. Chạy migration mới (nếu có file mới trong db/)
# psql -U postgres -d qlcl -f db\<file_moi>.sql

# 5. Restart app
```

---

## Chạy như Windows Service (production)

```powershell
# Dùng NSSM (https://nssm.cc)
nssm install QlclApp "D:\qlcl\.venv\Scripts\python.exe"
nssm set QlclApp AppParameters "-m uvicorn main:app --host 0.0.0.0 --port 8008"
nssm set QlclApp AppDirectory "D:\qlcl"
nssm start QlclApp
```

---

## Thêm XN mới vào hệ thống

1. Deploy `hanging_line_factory` lên máy XN mới.
2. Trong `.env` của app XN đó:
   ```env
   QLCL_DON_VI=XN4           # đặt tên đơn vị mới
   QLCL_API_URL=https://qlcl.hachibavn.com
   QLCL_API_KEY=<key_chung>  # lấy từ admin QLCL server
   ```
3. Khởi động app XN → vào Admin → nhấn **Đồng bộ ngay**.
4. Kiểm tra tại QLCL: `prod_plan.don_vi = 'XN4'` đã có bản ghi.
5. TV-3 của XN4 sẽ tự động kết nối và hiển thị dữ liệu QC theo `MONo`.

---

## Xử lý sự cố thường gặp

**App XN báo 403 khi đồng bộ**
→ `QLCL_API_KEY` trong `.env` app XN không trùng với key bên QLCL server.
→ Kiểm tra không có khoảng trắng thừa ở đầu/cuối key.

**TV-3 hiển thị "Không có dữ liệu QC"**
→ Kế hoạch chưa được đồng bộ (chưa có trong `prod_plan`) → chạy Đồng bộ ngay trên Admin.
→ Hoặc chưa có QC nhập liệu cho MONo đó trong ngày.

**PostgreSQL không kết nối được**
→ Kiểm tra service PostgreSQL đang chạy: `Get-Service postgresql*`
→ Kiểm tra `DATABASE_URL` trong `.env` đúng host/port/password.
