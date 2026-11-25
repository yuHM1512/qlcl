# Triển khai visual Co-2 theo ngày hiệu lực

Bộ triển khai không cần file PDF trên máy chạy. Dữ liệu portable nằm trong
`scripts/data/co2_visual_catalog.json`; 30 ảnh đã render nằm trong
`scripts/assets/visual_picker` và có checksum trong JSON.

## Nguyên tắc dữ liệu

- Áo vest, Áo khoác thể thao nhiều lớp và Quần tây chỉ được gắn metadata phiên bản;
  nội dung visual và ID hiện hữu được giữ nguyên.
- 10 bộ phận Yếm thể thao cũ được giữ nguyên ID và có hiệu lực đến ngày liền trước
  ngày Co-2. Các phiếu QC lịch sử vẫn tham chiếu đúng các ID này.
- Bộ Yếm Co-2 và ba loại hàng mới có hiệu lực từ ngày được truyền qua
  `--effective-from`.
- App chọn phiên bản theo **ngày báo cáo QC**, không theo ngày deploy máy chủ.

## Các bước trên máy đang chạy

Thay `YYYY-MM-DD` bằng ngày nghiệp vụ đã thống nhất.

```powershell
# 1. Dừng service/app để không có ghi dữ liệu trong lúc migration.

# 2. Sao lưu DB đầy đủ trước khi pull.
pg_dump -Fc -d qlcl -f "qlcl_before_co2.dump"

# 3. Pull code và cập nhật dependency trong đúng virtual environment.
git pull --ff-only origin main
python -m pip install -r requirements.txt

# 4. Kiểm tra rồi áp dụng schema (cả hai lệnh đều idempotent).
python scripts/apply_visual_catalog_migration.py
python scripts/apply_visual_catalog_migration.py --apply

# 5. Kiểm tra transaction dữ liệu; lệnh đầu luôn rollback.
python scripts/deploy_co2_visual_catalog.py --effective-from YYYY-MM-DD
python scripts/deploy_co2_visual_catalog.py --effective-from YYYY-MM-DD --apply

# 6. Khởi động lại app, rồi kiểm tra DB + API + toàn bộ ảnh.
python scripts/verify_co2_visual_deployment.py --effective-from YYYY-MM-DD --base-url http://localhost:8008
```

Script deploy tự sửa sequence trước khi thêm loại hàng, tạo snapshot JSON tại
`scripts/out/deploy_backups`, không xóa bộ phận/chi tiết cũ và dừng transaction nếu
phát hiện tham chiếu `qc_defect` bị hỏng. Có thể chạy lại cùng ngày hiệu lực mà không
tạo thêm version hoặc hotspot.

## Kiểm tra nghiệp vụ sau deploy

Đăng nhập bằng tài khoản kiểm thử, chọn một kế hoạch Yếm thể thao, rồi đổi ngày báo
cáo qua hai phía của mốc hiệu lực:

- Ngày trước mốc: danh sách 10 bộ phận cũ, không hiện visual picker Co-2.
- Đúng ngày mốc hoặc sau đó: visual picker Yếm Co-2 có 12 khối và 155 vị trí.
- Áo đồng phục y tế: 4 khối/50 vị trí, gồm `Cô-11`.
- Quần đồng phục y tế: 3 khối/37 vị trí.
- Quần thể thao: 11 khối/137 vị trí.

Nếu kiểm tra thất bại trước khi app được mở lại cho người dùng, khôi phục bản
`pg_dump`. Sau khi đã phát sinh phiếu QC mới, không xóa catalog Co-2; đóng khoảng
hiệu lực bằng một migration bổ sung để vẫn giữ các khóa ngoại lịch sử.

---

# Visual Co-2 lần 2 (`co2-v2`) — áp dụng từ 2026-11-25

Nguồn: `Co-2 (1).pdf` (dùng trang 1–55; trang 9 trùng trang 5, trang 56 là trang
hình nhãn, từ trang 57 không dùng). QC chọn vị trí trên giao diện giống trang PDF:
hình minh họa + bảng Mã tổng / Chi tiết.

| Loại hàng | Khối | Mã | Ghi chú |
|---|---|---|---|
| Áo đồng phục y tế | 4 | 50 | |
| Quần đồng phục y tế | 4 | 47 | thêm Nhãn mác |
| Quần thể thao | 12 | 152 | thêm Nhãn mác(1) |
| Yếm thể thao | 13 | 170 | thêm Nhãn mác(1) |
| Áo khoác thể thao nhiều lớp | 21 | 218 | hệ mã mới Lớp 1/2/3 |

**Áo vest và Quần tây không đổi** (giữ visual `legacy-current`).

Phiên bản đang mở của 5 loại hàng trên được đóng ở ngày 2026-11-24. Dữ liệu QC cũ
giữ nguyên ID bộ phận/chi tiết cũ; báo cáo có ngày trước 25/11 hiện visual cũ.

```powershell
# 1. Sao lưu DB, dừng app.
pg_dump -Fc -d qlcl -f "qlcl_before_co2_v2.dump"
# 2. Pull code.
git pull --ff-only origin main
# 3. Chạy thử (rollback), đọc kỹ WARNING nếu có, rồi áp dụng.
python scripts/deploy_co2_v2_visual_catalog.py --effective-from 2026-11-25
python scripts/deploy_co2_v2_visual_catalog.py --effective-from 2026-11-25 --apply
# 4. Khởi động lại app.
```

- Máy chủ không cần PDF: dữ liệu ở `scripts/data/co2_v2_visual_catalog.json`, ảnh ở
  `scripts/assets/visual_picker/positions/*/v2/` (có checksum).
- `WARNING ... QC defect(s) since 2026-11-25 use the old visual`: các phiếu nhập
  trong ngày bằng visual cũ trước khi deploy. Phiếu vẫn hợp lệ; nếu muốn ngày đó giữ
  visual cũ thì dùng `--effective-from` là ngày hôm sau.
- Chạy lại cùng ngày là an toàn: phiên bản đã có sẽ được đồng bộ ảnh/tọa độ/tên tại
  chỗ (giữ ID). Thêm/bớt khối hoặc mã thì script từ chối — cần phiên bản mới.

Dựng lại bundle khi PDF đổi (cần PDF, chạy trên máy có font Times New Roman):

```powershell
python scripts/build_co2_v2_bundle.py "E:/Downloads/Co-2 (1).pdf"
```

Các lỗi trong PDF đã được ghi nhận và xử lý trong script build (`SOURCE_FIXES`,
`LABEL_FIXES`, `TABLE_PREFIX_ALIAS`, `ANCHOR_REFERENCES`); mã in sai trên hình được
in đè lại mã đúng. Trang 37 (Tà(1)): hình đánh số 6/7 là dòng 5/6 — QLCL xác nhận
2026-11-25.
