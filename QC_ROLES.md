# Phân quyền QC

## Cấu trúc

`quality_employees.chuc_vu` giữ chức vụ nhân sự và nghiệp vụ KPI.
`quality_employees.qc_role` quy định quyền của module QC:

| Role | Quyền | Phạm vi |
| --- | --- | --- |
| QA_ADMIN | Danh mục, visual, tài khoản, kế hoạch, dashboard, CAP | Toàn bộ |
| FACTORY_ADMIN | Tạo/sửa/xóa/đồng bộ kế hoạch; xem dashboard, CAP | `don_vi` được gán |
| QC | Nhập liệu, tái chế; xem dashboard, CAP | `don_vi` được gán |

`qc_role = NULL` nghĩa là chưa được cấp quyền module QC (ví dụ QANL/QAPL).
QC và FACTORY_ADMIN thiếu Xí nghiệp hợp lệ sẽ bị từ chối truy cập dữ liệu.
Quyền được đọc lại từ DB trên mỗi request; không lưu role trong cookie.

## Migration

`db/migrate_qc_roles_20260916.sql` được đăng ký trong schema bootstrap và
chạy tự động khi ứng dụng khởi động. Có thể chạy SQL này trước khi triển khai code.

- QAQT hiện tại → QA_ADMIN; QC hiện tại → QC; giữ nguyên chức vụ.
- Hai chức vụ quản lý cũ FACTORY_MANAGER/FACTORY_DIRECTOR → QC, không tự cấp quyền sửa kế hoạch.
- B0443 — Lê Viết Bình — Điều độ — FACTORY_ADMIN — XN3.
- H1289 — Nguyễn Thị Quỳnh Hương — Điều độ — FACTORY_ADMIN — XN2.
- Chạy lại migration không cấp lại quyền đã thu hồi hoặc ghi đè phân công đã sửa.

## Gán quyền

Đăng nhập QA_ADMIN, mở **Cài đặt → Tài khoản & phân quyền** (`/qc/settings/qc-list`).
Chọn tài khoản, giữ chức vụ, chọn quyền QC và Xí nghiệp rồi lưu.
Chọn “Chưa cấp quyền QC” để thu hồi quyền module QC mà vẫn giữ nhân sự/KPI.
Không cho phép tài khoản đang đăng nhập tự thu hồi QA_ADMIN.

FACTORY_ADMIN chỉ thấy Xí nghiệp của mình trong kế hoạch. QC và FACTORY_ADMIN
được khóa bộ lọc Xí nghiệp ở dashboard/CAP; API cũng kiểm tra phạm vi khi gọi trực tiếp.
QC không chạy đồng bộ kế hoạch thủ công; thao tác này thuộc hai role quản trị.
FACTORY_ADMIN của XN1-V1/XN2/XN3 có nút Sync bệt riêng cho đơn vị. FACTORY_ADMIN
của XNV2 có nút Sync XNV2. QA_ADMIN có Sync XNV2 và một nút Sync bệt chạy toàn bộ
nguồn bệt đã cấu hình.

## Tích hợp

Các API push dữ liệu chuyền treo/chuyền bệt cần cấu hình `QLCL_API_KEY` và gửi
header `X-API-Key`. Không cấu hình key thì API push từ chối request.
`/api/tv3/qc-data` chấp nhận key này từ backend chuyền treo, hoặc tài khoản
đăng nhập với dữ liệu được giới hạn theo Xí nghiệp.

## Kiểm thử

Cài `httpx` trong môi trường phát triển, sau đó chạy:

```powershell
.venv/Scripts/python.exe -m unittest test_qc_roles test_flat_output -v
```

`test_qc_roles` dùng DB cấu hình hiện tại, chạy dữ liệu kiểm thử trong transaction
và rollback sau từng bài. Import ứng dụng sẽ chạy các migration chưa áp dụng;
nên chạy test trên DB phát triển. Sequence PostgreSQL có thể tăng dù rollback.
