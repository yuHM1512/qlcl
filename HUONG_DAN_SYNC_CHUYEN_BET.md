# Đồng bộ kế hoạch Chuyền bệt từ Google Sheets

QLCL đọc tab `Rải chuyền`, vùng `A2:M`, và chỉ lấy các dòng có cột
`Loại chuyền` bằng `Chuyền bệt` sau khi chuẩn hóa khoảng trắng và dấu tiếng Việt.

## Mapping XN1-V1, XN2 và XN3

| Google Sheet | `prod_plan` | Quy tắc |
|---|---|---|
| Nhu cầu bắt đầu | `ke_hoach` | Tương đương `NhuCauMe` của app Chuyền treo |
| Nhu cầu bắt đầu | `source_record_id` | Ghép thành `<đơn vị>:<Nhu cầu>` để không phụ thuộc STT/dòng Sheet |
| — | `source_system` | `flat_line_sheet` |
| — | `don_vi` | `XN1-V1`, `XN2` hoặc `XN3` theo cấu hình nguồn |
| Tổ | `bo_phan` | `U3 - L7` → `["Tổ 7"]`; `XN1-V1-L2` → `["Tổ 2"]`; `U3 - L1+8` → `["Tổ 1", "Tổ 8"]` |
| Mã hàng | `ma_hang` | Giữ nguyên chuỗi hiển thị |
| Loại hàng | `loai_hang` | Phải trùng tên trong `dm_loai_hang` để ghép visual picker |
| Ngày rải chuyền | `ngay_rc` | Đọc định dạng `d/m/YYYY` |
| Sản lượng KH | `san_luong` | Chuyển thành số nguyên |
| Khách hàng | `khach_hang` | Giữ nguyên |

Các cột ĐMKT, Phân loại ĐH, LĐ biên chế và Đơn giá chưa có trường tương ứng trong
`prod_plan`, nên chưa được ghi vào QLCL.

Mỗi lần sync, dòng hợp lệ đang mang `Chuyền bệt` được insert/update và đặt active.
Các kế hoạch cùng nguồn/đơn vị đã sync trước đó nhưng không còn trong tập hiện tại
được chuyển inactive; ID không bị xóa nên dữ liệu QC lịch sử vẫn giữ nguyên.

## Cấu hình máy chạy

Copy file service-account vào thư mục app và giữ file ngoài Git. Thêm vào `.env`:

```dotenv
FLAT_LINE_GOOGLE_SERVICE_ACCOUNT_FILE=credentials_m29.json
FLAT_LINE_SHEET_WORKSHEET=Rải chuyền
FLAT_LINE_SHEET_RANGE=A2:M
FLAT_LINE_XN3_SPREADSHEET_ID=13vX5BhwE9l7QkTWN-30JyaipyVJLiHPtHHCgNFDe9cw
FLAT_LINE_XN2_SPREADSHEET_ID=1HvyqiIuV8gWXRpELT2UuSXoxNYYOuCCuC7ZtbfBBxK0
FLAT_LINE_XN1_SPREADSHEET_ID=1esz95MLJKBsgSHPnrmsKLRETzG1814QuAn8EuummsZw
FLAT_LINE_AUTO_SYNC_ENABLED=false
FLAT_LINE_AUTO_SYNC_INTERVAL_MINUTES=60
```

QLCL quy đổi alias `XN1` thành đơn vị hiện hành `XN1-V1`.

## Cách chạy

- QAQT: vào trang Kế hoạch sản xuất và bấm nút Chuyền bệt tương ứng XN1-V1, XN2 hoặc XN3.
- QC XN1-V1/XN2/XN3: bấm `Chuyền bệt` tại màn hình chọn kế hoạch; backend tự lấy
  đơn vị từ tài khoản và không cho QC sync chéo xí nghiệp.
- Có thể bật auto-sync bằng `FLAT_LINE_AUTO_SYNC_ENABLED=true`, mặc định mỗi 60 phút.

API dùng cho kiểm thử:

```text
POST /api/prod-plan/sync-flat-line?don_vi=XN3
```
