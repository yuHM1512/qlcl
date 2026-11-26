# Hướng dẫn: Đồng bộ Kế hoạch từ Chuyền treo

## Tổng quan

QLCL và app chuyền treo (`hanging_line_factory`) của từng xí nghiệp chạy trên **các server riêng**,
không dùng chung database. Dữ liệu đi qua **API**: app chuyền treo của mỗi XN **tự đẩy (PUSH)** sang QLCL.
QLCL không kết nối thẳng SQL Server chuyền treo (ngoại lệ: chế độ PULL XNV2, mặc định tắt — xem cuối file).

```
App chuyền treo XN1-V1 / XN2 / XN3  (SQL Server riêng, APP_UNIT = đơn vị)
        │  POST + header X-API-Key
        ├─► /api/prod-plan/push-from-hl      kế hoạch (toàn bộ, mặc định 60 phút/lần hoặc bấm tay)
        ├─► /api/qc/hanging-output/push      sản lượng ra chuyền theo MONo + ngày (~2 phút/lần)
        ├─► /api/qc/employees/push-from-hl   danh sách QC + công đoạn
        └─► /api/qc/flat-output/push         sản lượng chuyền bệt (5 mốc giờ)
        ▼
PostgreSQL QLCL: prod_plan (source_system='hanging_line'), qc_hanging_output, qc_flat_output
        ▼
QC chọn kế hoạch trên /qc-input → nhập lỗi theo plan_id
```

Kế hoạch **Chuyền bệt** không đi qua app chuyền treo: QLCL tự đọc Google Sheet của từng XN
(`/api/prod-plan/sync-flat-line`, tự động mỗi `FLAT_LINE_AUTO_SYNC_INTERVAL_MINUTES` phút).

---

## Cấu hình

**QLCL** (`.env`):

```
QLCL_API_KEY=<key dùng chung>
```

Thiếu key → mọi API push trả 403.

**App chuyền treo từng XN** (`.env`): `QLCL_API_KEY` trùng key trên, URL của QLCL, `APP_UNIT` đúng tên
đơn vị trong QLCL (`XN1-V1`, `XN2`, `XN3`), và `QLCL_AUTO_SYNC_ENABLED=true` nếu muốn tự đẩy kế hoạch.
Đẩy tay: nút đồng bộ trên trang admin của app chuyền treo (`POST /admin/api/sync-to-qlcl`).

---

## Dữ liệu kế hoạch nhận được

Body: `{"don_vi": "XN2", "plans": [{guid, mono, ke_hoach, line_no, style_no, customer, loai_hang, first_hang, san_luong}]}`

| Field trong `prod_plan` | Nguồn |
|---|---|
| `source_record_id` | `guid` (`tPlanMaster.PlanMaster_guid`) |
| `mono` | `tPlanMaster.MONo` |
| `ke_hoach` | `HL-<MONo>` |
| `don_vi` | `don_vi` trong payload (`APP_UNIT` của XN) |
| `bo_phan` | `["Tổ <LineNo>"]` |
| `ma_hang` / `khach_hang` / `loai_hang` | `StyleNo` / `Customer` / `LoaiHang` |
| `ngay_rc` | `FirstHangDate` |
| `san_luong` | Sản lượng kế hoạch hiệu lực (SLKH + điều chỉnh) |

### Quy tắc upsert

1. **Cập nhật** nếu `source_system = 'hanging_line'` và `source_record_id = guid`
2. **Cập nhật** nếu `mono` trùng (kế hoạch nhập tay trước đó)
3. **Thêm mới** nếu không tìm thấy

Dữ liệu QC đã nhập **không bị xóa** khi đồng bộ — chỉ thông tin kế hoạch được cập nhật.
Mỗi lần đẩy kế hoạch được bật lại `is_active`, nhưng **không** đụng tới `is_finished` (nút "Kết thúc" trên QLCL).

### Kế hoạch đã xong

Chuyền treo hiện chưa gửi trạng thái kết thúc, nên kế hoạch chỉ ẩn khỏi danh sách QC khi admin bấm
**"Kết thúc"** trên `/qc`.

---

## Xử lý lỗi thường gặp

| Hiện tượng | Nguyên nhân | Cách xử lý |
|---|---|---|
| App chuyền treo báo 403 | `QLCL_API_KEY` hai bên khác nhau hoặc QLCL chưa đặt | Đặt cùng một key ở cả hai `.env`, khởi động lại |
| QC không thấy kế hoạch | `APP_UNIT` khác tên đơn vị của QC trong QLCL, hoặc `LineNo` khác tổ của QC | Sửa `APP_UNIT` / `LineNo` bên chuyền treo rồi đẩy lại |
| `Bỏ qua 1 plan vì thiếu mono` | Kế hoạch bên chuyền treo không có MONo | Kiểm tra dữ liệu bên chuyền treo |
| Sản lượng ra chuyền = 0 | Chưa có lượt push sản lượng cho MONo + ngày đó | Kiểm tra job đẩy sản lượng bên chuyền treo |

---

## Ngoại lệ: QLCL tự PULL kế hoạch XNV2

Chỉ dùng khi XNV2 không tự đẩy được và server QLCL kết nối được SQL Server XNV2:

```
HL_XNV2_AUTO_SYNC_ENABLED=true
HL_XNV2_AUTO_SYNC_INTERVAL_MINUTES=60
XNV2_SQL_SERVER=<server>
XNV2_APP_DB=hanging_app
XNV2_SQL_DRIVER=ODBC Driver 17 for SQL Server
XNV2_DON_VI=XNV2
```

Mặc định tắt. Code: `prod_plan_sync.py` (`run_xnv2_auto_sync_loop` → `sync_hanging_line_prod_plan`).
