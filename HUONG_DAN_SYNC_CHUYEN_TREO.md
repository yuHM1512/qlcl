# Hướng dẫn: Đồng bộ Kế hoạch từ Chuyền treo

## Tổng quan

Module QC (`qlcl`) có thể tự động kéo danh sách kế hoạch sản xuất từ hệ thống chuyền treo (`hanging_app` trên SQL Server) về, dùng làm cơ sở để QC nhập lỗi theo đúng mã sản xuất.

**Luồng dữ liệu:**
```
SQL Server (hanging_app.app.tPlanMaster)
        ↓  sync
PostgreSQL (qlcl.prod_plan)  ←  mono = MONo
        ↓
QC nhập lỗi → dữ liệu sẵn sàng để TV-3 lấy
```

---

## Cài đặt một lần

### 1. Cài pyodbc

```powershell
# Trong venv của qlcl
.\.venv\Scripts\activate
pip install pyodbc==5.1.0
```

> ODBC Driver 17 for SQL Server đã có sẵn trên máy (dùng chung với hanging line app).

### 2. Chạy migration PostgreSQL

```powershell
# Kết nối vào PostgreSQL qlcl rồi chạy:
psql -U postgres -d qlcl -f "db\alter_prod_plan_add_mono.sql"
```

Hoặc khởi động lại app — migration được áp dụng tự động khi startup.

### 3. Kiểm tra file .env

Mở `qlcl\.env`, đảm bảo có 3 dòng sau (chỉnh server/DB nếu cần):

```
HANGING_LINE_SQL_SERVER=.\SQLEXPRESS
HANGING_LINE_APP_DB=hanging_app
HANGING_LINE_SQL_DRIVER=ODBC Driver 17 for SQL Server
```

---

## Cách đồng bộ

### Từ trang Quản lý Kế hoạch (`/qc`)

Nhấn nút **"Đồng bộ Chuyền treo"** trên thanh action bar (bên cạnh nút "Đồng bộ XNV2").

### Từ màn hình Nhập lỗi QC (`/qc-input`)

Nhấn nút **"Chuyền treo"** trên vùng chọn kế hoạch.

Sau khi sync, app hiện thông báo:
> *Đồng bộ chuyền treo xong. Thêm X, cập nhật Y, bỏ qua Z.*

---

## Dữ liệu được sync

| Field trong `prod_plan` | Nguồn từ hanging line |
|---|---|
| `mono` | `tPlanMaster.MONo` (ví dụ: `LINE 1 #324287AW26-001`) |
| `ke_hoach` | `SYNC-HL-LINE1324287AW26-001` (tự sinh) |
| `don_vi` | `"Chuyền treo"` (cố định) |
| `bo_phan` | `["Line 1"]` (từ LineNo) |
| `ma_hang` | `tPlanMaster.StyleNo` |
| `khach_hang` | `tPlanMaster.Customer` |
| `loai_hang` | Map từ `PhanLoaiDH`: `Vest` → `Áo vest` |
| `ngay_rc` | `tPlanMaster.FirstHangDate` |
| `san_luong` | Tổng PO qty hoặc `tPlanMaster.SLKH` |
| `po_info` | Từ `tPlanPO` (PONo, Qty, ShipDate) |

### Lưu ý về Loại hàng

Chỉ `PhanLoaiDH = 'Vest'` được tự động map thành `Áo vest`. Các loại khác (`Mới`, `Lặp lại`, `Đặc biệt`) cần admin chọn loại hàng thủ công trong phần chỉnh sửa kế hoạch sau khi sync.

---

## Quy tắc upsert

Mỗi lần sync, app thực hiện theo thứ tự:

1. **Cập nhật** nếu `source_system = 'hanging_line'` và `source_record_id = PlanMaster_guid`
2. **Cập nhật** nếu `mono = MONo` (backward compat)
3. **Thêm mới** nếu không tìm thấy

Dữ liệu QC đã nhập (lỗi, hình ảnh) **không bị xóa** khi sync — chỉ metadata kế hoạch được cập nhật.

---

## Liên kết với TV-3 (Hanging Line Dashboard)

Sau khi QC nhập lỗi theo kế hoạch đã sync, TV-3 có thể truy vấn dữ liệu lỗi từ QC thông qua `mono` (= MONo):

```
TV3 request: /tv/api/tv3?mono=LINE 1 #324287AW26-001
                ↓ (sau khi tích hợp thêm)
QC DB query:  SELECT ... FROM qc_error_log_sp
              JOIN prod_plan ON prod_plan.id = qc_error_log_sp.plan_id
              WHERE prod_plan.mono = 'LINE 1 #324287AW26-001'
```

> Bước tích hợp TV-3 đọc dữ liệu lỗi từ QC là giai đoạn tiếp theo.

---

## Xử lý lỗi thường gặp

| Thông báo | Nguyên nhân | Cách xử lý |
|---|---|---|
| `Không kết nối được SQL Server chuyền treo` | Hanging app chưa chạy hoặc sai tên server | Kiểm tra `HANGING_LINE_SQL_SERVER` trong `.env` |
| `pyodbc chưa được cài đặt` | Thiếu thư viện | `pip install pyodbc` |
| `Bỏ qua X: thiếu MONo` | Record trong tPlanMaster không có MONo | Kiểm tra dữ liệu bên hanging line |
| Loại hàng trống sau sync | PhanLoaiDH không có trong map | Admin chỉnh tay loại hàng trong trang QC |
