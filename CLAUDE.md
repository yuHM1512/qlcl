# CLAUDE.md - QLCL Project

Tài liệu để Claude nắm logic dự án qua các phiên làm việc.

## Tổng quan dự án

- App FastAPI (`main.py`) + templates Jinja2 (`templates/*.html`)
- PostgreSQL (schema seed/migration trong `db/*.sql`)
- File ảnh được serve qua `/api/images/<path>` từ thư mục `IMAGES_STORAGE_DIR` (env, mặc định `./images`)
- Mục đích: quản lý KPI QC sản xuất may mặc — kế hoạch sản xuất, nhập lỗi QC theo loại hàng / bộ phận / chi tiết, dashboard, rework.

## Module quan trọng đã có

| Module | Template | Backend prefix |
|---|---|---|
| QC Input (Sản phẩm) | `qc_input_sp.html` | `/api/qc/*`, `/qc-input` |
| QC Rework | `qc_rework_2.html` | `/qc-input/rework` |
| QC Dashboard | `qc_dashboard.html`, `qc.html` | `/api/qc/*` |
| KPI Input | `kpi_input.html` | `/api/kpi/*` |
| HDKP (Hoạt động kế hoạch) | `hdkp_form*.html` | `/api/hdkp/*` |
| Master data QC | `qc_settings_*.html` | `/api/dm/*` |

---

## ⭐ Visual Picker (Số hoá vị trí lỗi)

Tính năng cho phép QC chọn vị trí lỗi bằng cách **bấm trực tiếp lên hình ảnh sản phẩm** thay vì chọn combobox text. Đã triển khai cho **Áo vest** và **Quần tây**.

### Pipeline 3 bước (generic, 1 file Excel có thể chứa nhiều loại hàng)

```
Excel (.xlsx) — 1 sheet = 1 nhóm của 1 loại hàng
    │  scripts/parse_visual_picker_excel.py <xlsx> <out_dir>
    ▼
scripts/out/visual_picker.json   +   scripts/out/positions/<slug>/<nhom>/*.png|*.svg
    │  scripts/import_visual_picker_to_db.py
    ▼
PostgreSQL (dm_bo_phan + dm_chi_tiet với hotspot coords)
    +
images/positions/<slug>/<nhom>/*.png|*.svg   ← copy vào IMAGES_STORAGE_DIR
```

### Định dạng Excel mà parser yêu cầu

File mẫu hiện tại: `visual_type/CHI TIET HANG VEST....xlsx` (4 sheet visible: Áo vest CHÍNH/LÓT/NHẬN DIỆN + QUAN TAY).

**Cấu hình ánh xạ sheet** trong `scripts/parse_visual_picker_excel.py` ở biến `SHEET_MAP`:
```python
SHEET_MAP = {
    "AO VEST -CHINH":      ("aovest",  "chinh"),
    "AO VEST - LOT":       ("aovest",  "lot"),
    "AO VEST - NHAN DIEN": ("aovest",  "nhan_dien"),
    "QUAN TAY":            ("quantay", "chinh"),
}
# (sheet_name -> (loai_hang_slug, nhom_key))
```

**Bố cục sheet** (parser hardcode đọc theo cột A/B/D/E):
- **Header khối**: col A = prefix ngắn 1-3 chữ in hoa (`T`, `C`, `V`, `TN`, `TS`, `TT`, `L`, `B`...), col B = tên khối (`Tay`, `Cổ`, `Ve`, `Thân trước`, `Barget`...).
- **Rows tiếp theo trong cùng khối**: col D = nhãn vị trí (`Đỉnh vai`, `Khuy tay`...), col E = mã vị trí (`T1`, `T2`, `C1`...). Khối kết thúc khi gặp header khối tiếp theo.
- **Ảnh khối** (PNG, có kèm SVG nếu file Excel có) được đặt trong sheet. Ảnh có thể neo TẠI hoặc tới **5 row TRƯỚC** header khối tương ứng — parser dùng prefix của textbox bên trong ảnh (T1,T2,T3 → 'T') để khớp đúng khoi nếu row matching không đủ chính xác.
- **Mã vị trí trên ảnh**: textbox (autoshape) đặt trên ảnh, text trùng với mã trong col E. Parser tính `x_pct/y_pct/w_pct/h_pct` của textbox so với bbox ảnh để render hotspot.
- **Trùng tên chi tiết trong 1 bộ phận** OK (vd T4='Khuy tay' và T6='Khuy tay'): import script đã drop constraint `UNIQUE(bo_phan_id, ten_chi_tiet)` — uniqueness được đảm bảo qua `ma_vi_tri`.

### DB schema visual picker

- `db/migrate_aovest_visual_picker.sql`: thêm các cột `nhom/image_png/image_svg/sort_order` vào `dm_bo_phan` và `ma_vi_tri/x_pct/y_pct/w_pct/h_pct/rotation` vào `dm_chi_tiet`.
- `db/migrate_dm_chi_tiet_drop_ten_unique.sql`: drop `UNIQUE(bo_phan_id, ten_chi_tiet)` cũ (cho phép trùng tên chi tiết, vì `ma_vi_tri` mới là khoá thật). Import script tự chạy `DROP CONSTRAINT IF EXISTS` mỗi lần — idempotent.

```sql
-- dm_bo_phan cột mở rộng
nhom VARCHAR(20),           -- 'chinh' | 'lot' | 'nhan_dien'
image_png VARCHAR(255),     -- 'positions/aovest/chinh/chinh_t_3.png'
image_svg VARCHAR(255),
sort_order INT DEFAULT 0;

-- dm_chi_tiet cột mở rộng
ma_vi_tri VARCHAR(10),      -- 'T1', 'C3', ...
x_pct, y_pct, w_pct, h_pct NUMERIC(7,5),
rotation NUMERIC(6,2);
```

### Backend (`main.py`)

- `GET /api/qc/visual-picker?loai_hang_id=<id>` (main.py:4580-4643):
  - Trả `{has_visual_picker: bool, nhoms: [{nhom, label, khoi: [{bo_phan_id, ten_khoi, image_png, image_svg, hotspots: [{chi_tiet_id, ma_vi_tri, label, x/y/w/h_pct, rotation}]}]}]}`
  - `has_visual_picker = True` khi có ít nhất 1 `dm_bo_phan` của loại hàng đó có cả `image_png` và `nhom`.
  - `NHOM_LABELS` hardcode ở `main.py:4578`: `{"chinh":"Chính","lot":"Lót","nhan_dien":"Nhận diện"}`.
  - Thứ tự nhóm: `nhom_order = ["chinh", "lot", "nhan_dien"]` (`main.py:4629`).

### Frontend (`templates/qc_input_sp.html`)

- `selectPlan()` (~line 719): khi chọn kế hoạch → gọi song song `/api/dm/bo-phan` và `/api/qc/visual-picker`. Nếu visual picker có → set `visualPickerData`.
- `addBoPhanBlock()` (~line 1091): nếu `visualPickerData.has_visual_picker` → render `renderVpBlockHTML` (tabs nhóm + grid khối + ảnh có hotspot), ngược lại render combo cũ.
- Click hotspot → `vpSelectHotspot()` → fill 2 hidden `<select>` `.sel-bo-phan` + `.sel-chi-tiet` → các bước Mã lỗi / Mức độ vẫn dùng combo như cũ.
- Submit (`submitReport`) đọc giá trị từ `.sel-bo-phan` + `.sel-chi-tiet` ẩn — **không cần đổi logic submit** khi bật/tắt visual picker.

### Khi thêm loại hàng mới

Checklist:
1. **Chuẩn bị file Excel** theo đúng bố cục cột A/B/D/E như trên, ảnh có textbox mã vị trí.
2. Update **`scripts/parse_visual_picker_excel.py` → `SHEET_MAP`**: thêm dòng `"TÊN SHEET CỦA LOẠI HÀNG": ("<slug>", "<nhom_key>")`. Slug ngắn, lowercase, không dấu (vd `quantay`, `aoso_mi`...).
3. Update **`scripts/import_visual_picker_to_db.py` → `SLUG_TO_TEN_LOAI`**: thêm dòng `"<slug>": "<ten_loại_hàng_chính_xác>"`. Import script tự INSERT `dm_loai_hang` nếu chưa có.
4. **Nếu loại hàng dùng nhóm ngoài** `chinh/lot/nhan_dien`:
   - Update `NHOM_LABELS` ở `main.py:4578` (hiển thị tab tên Việt).
   - Update `nhom_order` ở `main.py:4629`.
5. **Chạy lệnh**:
   ```powershell
   python scripts/parse_visual_picker_excel.py "visual_type/CHI TIET HANG VEST....xlsx" scripts/out
   python scripts/import_visual_picker_to_db.py
   ```
6. Khởi động lại app, mở `/qc-input`, chọn kế hoạch của loại hàng vừa import → kiểm tra hotspot vị trí đúng trên ảnh.

### Khi chỉ đổi ảnh cho loại hàng đã có

Format Excel giữ nguyên (sheet name không đổi) → chạy lại 2 lệnh ở bước 5. Import script:
1. SET NULL trên `qc_defect.bo_phan_id` / `chi_tiet_id` đang trỏ đến loại hàng cũ.
2. DELETE `dm_bo_phan` cũ (cascade `dm_chi_tiet`).
3. Insert lại từ JSON mới + copy ảnh đè `images/positions/<slug>/`.

⚠ Dữ liệu lỗi QC lịch sử sẽ bị mất link đến bộ phận/chi tiết (giữ lại `qc_defect` row nhưng FK null).

### File tham chiếu nhanh

| Việc | File |
|---|---|
| Parser Excel → JSON + ảnh | `scripts/parse_visual_picker_excel.py` |
| Import JSON → DB + copy ảnh | `scripts/import_visual_picker_to_db.py` |
| Schema visual picker | `db/migrate_aovest_visual_picker.sql` + `db/migrate_dm_chi_tiet_drop_ten_unique.sql` |
| API serve picker data | `main.py:4576-4643` |
| UI render hotspot | `templates/qc_input_sp.html` (search `vp-` / `visualPickerData`) |
| Ảnh đã import | `images/positions/<slug>/<nhom>/*.png\|*.svg` |
| JSON snapshot | `scripts/out/visual_picker.json` |
| File Excel nguồn | `visual_type/CHI TIET HANG VEST....xlsx` |

### Trạng thái hiện tại (2026-06-11)

| Loại hàng | id | n_bo_phan | n_chi_tiet | Nhóm |
|---|---|---|---|---|
| Áo vest | 1 | 12 | 132 | chinh (7) + lot (4) + nhan_dien (1) |
| Quần tây | 3 | 7 | 84 | chinh (7) |

---

## Quy ước chung khác

- **Tiếng Việt** dùng trong toàn bộ UI label và domain term — giữ nguyên trong code khi không cần dịch.
- **PowerShell** là shell mặc định trên máy này (Windows 11). Khi cần chạy lệnh shell trong tài liệu, ưu tiên cú pháp PowerShell.
- **psycopg2** + `RealDictCursor` cho hầu hết query trả JSON.
- **Date format**: `YYYY-MM-DD` ở API, frontend tự build từ local timezone.
- **Station** (QC làm việc ở trạm nào): lưu trong `quality_employees.station` (JSON array), filter theo `station` ở các API output/error log.
