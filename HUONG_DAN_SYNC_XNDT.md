# Sync XNDT từ b_line

Trong trang Kế hoạch, QA_ADMIN hoặc FACTORY_ADMIN của XNDT bấm **Sync XNDT**.
API: `POST /api/prod-plan/sync-xndt`. QC không có quyền đồng bộ kế hoạch.

QLCL đọc `public.qlcl_outbox` nối `public.source_snapshot` theo snapshot_id và
đơn vị XNDT trong database b_line. App Chuyền bệt phải đồng bộ nguồn trước.
Nút này lấy bản dữ liệu đã lưu trong b_line, không kích hoạt đọc Google Sheets.

Mặc định dùng host/port/user/password từ DATABASE_URL của QLCL, đổi database
thành b_line. Nếu dùng tài khoản khác, cấu hình B_LINE_DATABASE_URL riêng.
Tài khoản nguồn chỉ cần CONNECT, USAGE schema public và SELECT hai bảng trên.

```dotenv
# Tùy chọn: kết nối nguồn riêng
B_LINE_DATABASE_URL=postgresql://USER:PASSWORD@HOST:5432/b_line
# Bật đồng bộ tự động; mặc định tắt cho đến khi triển khai nguồn
B_LINE_AUTO_SYNC_ENABLED=true
B_LINE_AUTO_SYNC_INTERVAL_MINUTES=2
```

Chu kỳ 2 phút là chu kỳ lấy dữ liệu mới; sản lượng vẫn theo 5 mốc 2 giờ do
app Chuyền bệt tổng hợp. Bản ghi nhu cầu/ngày chứa qty và các slot qty/cumulative,
giữ nguyên mốc chưa nhập (null) và số điều chỉnh giảm. Không cộng lặp lũy kế.

Mapping nhu cầu: demand → ke_hoach, teams/team → bo_phan, customer → khach_hang,
style → ma_hang, product_type → loai_hang, first → ngay_rc, quantity → san_luong.
Dùng source_system=flat_line_sheet và source_record_id=XNDT:<demand>, tương thích
luồng đẩy trực tiếp từ app bệt. Loại hàng phải tồn tại trong dm_loai_hang.

Kế hoạch và sản lượng được cập nhật trong một giao dịch, khóa cùng luồng đẩy
trực tiếp. Sync lặp giữ ID kế hoạch và lịch sử QC; sản lượng XNDT được thay bằng
snapshot đầy đủ để nhận cả sửa/xóa. Không tác động dữ liệu đơn vị khác.
Nhu cầu mất khỏi nguồn chuyển inactive khi snapshot không có cảnh báo.
Nếu chưa có snapshot hoặc dữ liệu không hợp lệ, giao dịch không ghi thay đổi.

Nhu cầu XNDT sử dụng giao diện Chuyền bệt và tỷ lệ lỗi trạm cuối chuyền hiện có:
số sản phẩm lỗi / sản lượng ngày × 100. API flat-qc-data hỗ trợ đơn vị XNDT.

Kiểm thử database (rollback mọi thay đổi trong bài test):
`.venv/Scripts/python.exe -m unittest test_xndt_sync -v`
