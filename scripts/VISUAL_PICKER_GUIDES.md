# PDF có đường chỉ dẫn

`Co-2.pdf` lưu ảnh áo, clipping mask, mã vị trí và đường chỉ dẫn ở các
lớp PDF riêng. Trích xuất image xref sẽ lấy ảnh áo đầy đủ nhưng mất đường
chỉ dẫn và mất cả vùng cắt. Parser PDF nhiều lớp cũ còn chỉ nhận mã dạng
`T(2)-1`, không phù hợp mã như `Cô-1` trong PDF này.

Với loại hàng **đã có trong DB**, chạy công cụ sửa riêng:

```powershell
python scripts/repair_visual_picker_guides.py 'E:/Downloads/Co-2.pdf' 'Áo đồng phục y tế' ao_dpyt
# Kiểm tra PNG và manifest trong scripts/out/guided_pdf, sau đó áp dụng:
python scripts/repair_visual_picker_guides.py 'E:/Downloads/Co-2.pdf' 'Áo đồng phục y tế' ao_dpyt --apply
```

Công cụ render ô minh họa của bảng PDF ở tỷ lệ 2x, giữ đường/chấm/mã và
clipping. Tọa độ hotspot được căn theo tâm mã in trên hình, trừ nửa kích
thước hotspot theo quy ước của UI. Tên ảnh chứa hash để tránh cache ảnh cũ.

`--apply` thay ảnh và căn lại tọa độ của loại hàng được chọn; các chỉnh tay
trước đó được lưu trong file `*_before_*.json`. Ảnh cũ vẫn được giữ nguyên.
Công cụ cập nhật các hàng hiện hữu trong một transaction, giữ ID, tên chi
tiết và liên kết lỗi QC. Không dùng importer cũ để sửa ảnh: importer đó xóa
danh mục và đưa khóa ngoại lỗi QC về NULL.

Các mã không có trên hình được báo trong `unmatched` và giữ tọa độ cũ để
người dùng xác minh, không tự suy đoán điểm đích. Chỉ khác dấu tiếng Việt
được chuẩn hóa để đối chiếu (`Co-10` / `Cô-10`, `Lu-1` / `Lư-1`).

## Rà soát toàn bộ Co-2.pdf

Chạy sửa danh mục đã được đối chiếu trực quan trước khi căn tọa độ:

```powershell
python scripts/reconcile_co2_catalog.py
python scripts/reconcile_co2_catalog.py --apply
python scripts/repair_visual_picker_guides.py 'E:/Downloads/Co-2.pdf' 'Áo đồng phục y tế' ao_dpyt --apply
python scripts/repair_visual_picker_guides.py 'E:/Downloads/Co-2.pdf' 'Quần đồng phục y tế' quan_dpyt --apply
python scripts/repair_visual_picker_guides.py 'E:/Downloads/Co-2.pdf' 'Quần thể thao' quan_thethao --apply
python scripts/repair_visual_picker_guides.py 'E:/Downloads/Co-2.pdf' 'Yếm thể thao' yem_thethao --anchor-reference 20 'Lư-7' 8 'Lư-6' --apply
```

Các hiệu chỉnh nguồn được kiểm tra:

- Trang 1 ghi trùng `Cô-10` tại dòng 11. Đã bổ sung `Cô-11 / Can lá cổ`
  dựa trên số dòng và nhãn trên hình, giữ nguyên `Cô-10 / Lá cổ`.
- Trang 16 để trống cột mã tổng, khiến toàn bộ khối Cụm tháo ống bị bỏ qua.
  Đã thêm khối và 10 mã `Tô-1` đến `Tô-10`, lấy tên từ bảng và mã từ hình.
- Trang 2/3 có chữ cũ nằm dưới các lớp sửa. Đã sửa 11 tên chi tiết theo bảng
  nhìn thấy (bao gồm Th-14/Th-15 bị đảo). `Lu-11` là dòng cũ bị che, không
  phải thiếu hình: chỉ xóa khi không có lỗi QC tham chiếu; bảng hiện tại kết
  thúc ở `Lư-10 / Chít ly lưng`.
- Trang 8/20 in `Lư11` không có dấu gạch. Parser hiện nhận được mã này.
- Trang 20 có line tới khuy nhưng thiếu chữ `Lư-7`. Vị trí nhãn được đối
  chiếu với cùng sơ đồ ở trang 8, căn theo nhãn `Lư-6`; đây là tham chiếu đã
  kiểm tra, phải truyền rõ bằng `--anchor-reference`, không tự đoán mã thiếu.
- Trang 3: bảng ghi `Lư-5/6` là Can/Diễu sóng lưng, nhưng line trên hình
  vẫn chỉ gần lai áo. Danh mục theo bảng hiện tại; cần sửa tài liệu gốc để
  thống nhất ý nghĩa điểm đích, không tự vẽ lại line.

Yếm thể thao còn có danh mục cũ không có ảnh. API visual-picker hiện chỉ
trả các khối đã số hóa có ảnh và nhóm; dữ liệu cũ không bị xóa.

Kiểm thử và báo cáo:

```powershell
python scripts/test_visual_picker_guides.py
python scripts/audit_visual_picker.py --base-url http://localhost:8008
```

Đã kiểm tra trực tiếp 7 mặt hàng, 66 khối, 742 hotspot và 85 ảnh PNG/SVG.
Riêng Co-2.pdf: 4 mặt hàng, 30 khối, 379 hotspot; đã thử lưu/đọc lại Cô-11.
Ba mặt hàng ngoài Co-2.pdf còn 27 tâm hotspot nằm ngoài ảnh, được liệt kê
trong `scripts/out/guided_pdf/catalog_audit.json`. Chưa đổi các tọa độ này
thành điểm đoán hoặc ép sát mép ảnh.
