# Deploy Checklist

## 1. Backup

- Backup `.env`
- Backup thư mục `images/`
- Backup thư mục `pdf_files/`
- Nếu cần an toàn hơn, đổi tên bản app cũ thành `qlcl_old`

## 2. Pull Code

- Clone repo hoặc `git pull` bản mới nhất của nhánh `main`
- Xác nhận có các thư mục:
  - `gemba_cp/`
  - `templates/`
  - `db/`

## 3. Restore Config

- Tạo lại `.env` từ `env.example` nếu máy chưa có
- Kiểm tra tối thiểu các biến sau:
  - `DATABASE_URL`
  - `GEMBA_CP_DATABASE_URL`
  - `TEMPLATES_DIR`
  - `EXCEL_TEMPLATE_PATH`
  - `PDF_STORAGE_DIR`
  - `IMAGES_STORAGE_DIR`
  - `GEMBA_CP_GOOGLE_SERVICE_ACCOUNT_FILE`

- Nếu deploy ở path khác máy dev, sửa lại toàn bộ path tuyệt đối trong `.env`

## 4. Restore Secrets

- Đảm bảo file credentials Google Sheets tồn tại tại:
  - `gemba_cp/templates/credentials_m29.json`

- File này đang bị ignore khỏi git, nên phải copy thủ công trên máy deploy

## 5. Setup Python

- Tạo hoặc dùng `.venv` riêng của project
- Cài dependency:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## 6. Check Database

- Đảm bảo DB chính `qlcl` truy cập được
- Đảm bảo DB `gemba_cp` truy cập được
- User DB phải có quyền tạo bảng/index/trigger

Lưu ý:
- App sẽ tự bootstrap schema khi startup
- Một số unique index legacy sẽ được bỏ qua nếu DB cũ đang có dữ liệu trùng, để tránh crash khi deploy

## 7. Start App

Chạy bằng `.venv`:

```powershell
.\.venv\Scripts\python.exe -m uvicorn main:app --host 0.0.0.0 --port 8008 --reload
```

Hoặc:

```powershell
.\.venv\Scripts\python.exe main.py
```

## 8. Smoke Test

- Mở `http://localhost:8008/healthz`
- Mở `http://localhost:8008/login`
- Đăng nhập bằng mã nhân viên hợp lệ
- Mở menu `/`
- Mở `/dashboard-summary`
- Bấm vào `Dashboard KPI Gemba Control Plan`
- Kiểm tra dashboard Gemba load được

## 9. Gemba Validation

- Kiểm tra route:
  - `/gemba-control-plan`
  - `/api/dashboard/meta`
  - `/api/dashboard/overview`

- Bấm `Đồng bộ` trong dashboard Gemba
- Xác nhận không lỗi quyền Google Sheets
- Xác nhận dữ liệu trong DB `gemba_cp` được nạp

## 10. QC Validation

- Mở `/qc`
- Kiểm tra `/qc-input`
- Kiểm tra dashboard QC và các màn hình settings chính

## 11. If Rollback Needed

- Dừng app mới
- Khôi phục thư mục app cũ hoặc chuyển lại `qlcl_old`
- Restore `.env`, `images/`, `pdf_files/`
- Chạy lại bản cũ
