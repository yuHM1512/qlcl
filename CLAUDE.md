# QLCL - App Quản Lý Chất Lượng May Mặc

## Tổng quan

App nội bộ phục vụ QC/QA/QAQT/quản lý chuyền tại các xí nghiệp may (XN2, XN3, XN1-V1...).  
Có liên kết với hệ thống chuyền treo (hanging app) để sync nhân sự QC và công đoạn.

---

## Tech Stack

| Layer | Công nghệ |
|-------|-----------|
| Backend | **FastAPI 0.115** + Uvicorn, Python 3.x |
| Templating | **Jinja2 3.1** (server-rendered, mỗi page là file HTML standalone) |
| Database | **PostgreSQL** (psycopg2 + psycopg3 + SQLAlchemy 2.0) |
| Sync nguồn ngoài | pyodbc (SQL Server / chuyền treo), google-api-python-client (Google API) |
| Frontend (QC module) | **Tailwind CSS via CDN** + vanilla JS `fetch()` + Material Symbols icon font |
| Frontend (QC Input) | **Bootstrap 5** + Font Awesome 6 + vanilla JS (mobile-first, khác stack với các trang khác) |
| State management | Không có framework — dùng biến JS page-local + `localStorage` |
| Excel export/import | openpyxl |

> **Lưu ý quan trọng**: Trang `qc_input_sp.html` dùng **Bootstrap 5 + Font Awesome**, trong khi TẤT CẢ các trang khác dùng **Tailwind + Material Symbols**. Đây là sự không nhất quán cần chú ý khi refactor.

---

## Cấu trúc thư mục

```
qlcl/
├── main.py                    # ⚠️ File DUY NHẤT chứa TẤT CẢ routes + business logic (~307KB)
├── .env / env.example         # Config database, storage paths
├── requirements.txt           # Python dependencies
├── templates/                 # Jinja2 HTML pages (flat, không có subfolder)
│   ├── index.html             # Landing page - chọn module (KPI / QC)
│   ├── login.html             # Login form (dùng chung KPI + QC via qc_mode flag)
│   ├── qc.html                # QC home - Kế hoạch sản xuất (có sidebar đầy đủ)
│   ├── qc_input_sp.html       # ⭐ Nhập liệu QC sản phẩm (Bootstrap, mobile-first, KHÔNG sidebar)
│   ├── qc_rework_2.html       # Nhập liệu rework
│   ├── cap.html               # Hành động khắc phục (CAP)
│   ├── qc_dashboard.html      # Dashboard tỉ lệ lỗi
│   ├── qc_settings_customer.html  # Master data: Khách hàng - Mã hàng
│   ├── qc_settings_details.html   # Master data: Bộ phận - Chi tiết
│   ├── qc_settings_qcs.html       # Master data: Danh sách QC
│   ├── qc_settings_visual_picker.html # Master data: Visual picker / vị trí
│   ├── hdkp_form.html         # Form HĐKP (Hành động khắc phục chi tiết)
│   ├── hdkp_form_endline.html # Form HĐKP endline
│   ├── kpi.html               # KPI System home
│   ├── kpi_input.html         # KPI data entry
│   ├── view_kpi.html          # KPI viewer
│   ├── dashboard_summary.html # KPI dashboard
│   └── Logo.png               # Logo served as static
├── db/                        # Raw SQL schema/migration files
│   ├── create_*.sql
│   ├── alter_*.sql
│   └── migrate_*.sql
├── scripts/                   # One-off import scripts
├── images/                    # User-uploaded images (served at /api/images/)
├── pdf_files/                 # Generated PDFs (served at /api/pdf/)
├── visual_type/               # Excel files cho Visual Picker feature
└── gemba_cp/                  # Sub-app "Gemba Control Plan" (riêng biệt)
    ├── static/
    └── (own Jinja2 templates)
```

---

## Routes (Page Routes)

### Landing & Auth
| Route | Template | Mô tả |
|-------|----------|-------|
| `GET /` | `index.html` | Landing page, chọn module KPI hoặc QC |
| `GET /login` | `login.html` | Login chung |
| `POST /login` | — | Xử lý login |
| `POST /logout` | — | Logout |

### QC Module (sidebar pages)
| Route | Template | Sidebar item |
|-------|----------|-------------|
| `GET /qc` | `qc.html` | **Kế hoạch sản xuất** (active) |
| `GET /qc/cap` | `cap.html` | **Hành động khắc phục** (active) |
| `GET /qc/dashboard` | `qc_dashboard.html` | **Dashboard** (active) |
| `GET /qc/settings/customer` | `qc_settings_customer.html` | Cài đặt > **Khách hàng - Mã hàng** |
| `GET /qc/settings/details` | `qc_settings_details.html` | Cài đặt > **Bộ phận - Chi tiết** |
| `GET /qc/settings/qc-list` | `qc_settings_qcs.html` | Cài đặt > **Danh sách QC** |
| `GET /qc/settings/visual-picker` | `qc_settings_visual_picker.html` | Cài đặt > **Sắp xếp vị trí** |

### QC Input (KHÔNG có sidebar, mobile-first)
| Route | Template | Mô tả |
|-------|----------|-------|
| `GET /qc-input` | `qc_input_sp.html` | Nhập liệu QC (inline) |
| `GET /qc-input-2` | `qc_input_sp.html` | Nhập liệu QC (endline) |
| `GET /qc-input/rework` | `qc_rework_2.html` | Nhập rework (inline) |
| `GET /qc-input-2/rework` | `qc_rework_2.html` | Nhập rework (endline) |

### HĐKP Forms
| Route | Template |
|-------|----------|
| `GET /hdkp-form/{error_id}` | `hdkp_form.html` |
| `GET /hdkp-form-endline/{dps_id}` | `hdkp_form_endline.html` |

### KPI Module
| Route | Template |
|-------|----------|
| `GET /kpi` | `kpi.html` |
| `GET /kpi-input` | `kpi_input.html` |
| `GET /view-kpi` | `view_kpi.html` |
| `GET /dashboard-summary` | `dashboard_summary.html` |

---

## API Endpoints

### Master Data (`/api/dm/`)
| Endpoint | Methods | Mô tả |
|----------|---------|-------|
| `/api/dm/khach-hang` | GET, POST, DELETE | Khách hàng |
| `/api/dm/ma-hang` | GET, POST, DELETE | Mã hàng (theo khách hàng) |
| `/api/dm/loai-hang` | GET, POST, DELETE | Loại hàng |
| `/api/dm/loai-hang-target` | GET, POST, DELETE | Target theo loại hàng |
| `/api/dm/bo-phan` | GET, POST, DELETE | Bộ phận |
| `/api/dm/qc-cum` | GET, POST, DELETE | QC cụm |
| `/api/dm/chi-tiet` | GET, POST, DELETE | Chi tiết |
| `/api/dm/nhom-loi` | GET, POST, DELETE | Nhóm lỗi |
| `/api/dm/ma-loi` | GET, POST, DELETE | Mã lỗi |
| `/api/dm/mo-ta-loi` | GET, POST, DELETE | Mô tả lỗi |
| `/api/dm/ma-loi-options` | GET | Dropdown options mã lỗi |

### QC Operations (`/api/qc/`)
| Endpoint | Methods | Mô tả |
|----------|---------|-------|
| `/api/qc/dashboard` | GET | Dashboard data |
| `/api/qc/dashboard/filters` | GET | Filter options cho dashboard |
| `/api/qc/dashboard/prev-date` | GET | Ngày trước đó có data |
| `/api/qc/employees` | GET, POST, PUT, DELETE | CRUD nhân sự QC |
| `/api/qc/employees/push-from-hl` | POST | Sync nhân sự từ chuyền treo |
| `/api/qc/cap` | GET | Danh sách CAP |
| `/api/qc/cap/action` | POST | Xử lý action CAP |
| `/api/qc/cap/heartbeat` | POST | Heartbeat CAP |
| `/api/qc/cap/filters` | GET | Filter options CAP |
| `/api/qc/error-log-sp` | POST | Ghi log lỗi sản phẩm |
| `/api/qc/output-sp-log` | GET | Log output sản phẩm |
| `/api/qc/output-sp` | POST | Ghi output sản phẩm |
| `/api/qc/upload-sp-image` | POST | Upload ảnh sản phẩm |
| `/api/qc/visual-picker` | GET | Visual picker data |
| `/api/qc/input/pos-summary` | GET | Tóm tắt vị trí |
| `/api/qc/input/quick-defect-combos` | GET | Quick defect combos |
| `/api/qc/rework-2` | POST | Ghi rework |
| `/api/qc/hdkp/{dps_id}` | GET, POST | HĐKP data |

### Production Plan (`/api/prod-plan/`)
| Endpoint | Methods | Mô tả |
|----------|---------|-------|
| `/api/prod-plan` | GET, POST, PUT, DELETE | CRUD kế hoạch sản xuất |
| `/api/prod-plan/sync-qtcn` | POST | Sync từ hệ thống QTCN |
| `/api/prod-plan/sync-hanging-line` | POST | Sync từ chuyền treo |
| `/api/prod-plan/push-from-hl` | POST | Push data từ hanging line |

### KPI & Others
| Endpoint | Methods |
|----------|---------|
| `/api/summary`, `/api/summary/monthly` | GET |
| `/api/input`, `/api/input-edit`, `/api/input-error` | POST/GET |
| `/api/hdkp/{error_id}`, `/api/hdkp/{error_id}/regenerate-pdf` | GET/POST |
| `/api/upload-image` | POST |
| `/api/tasks` | GET |
| `/healthz` | GET |

---

## Sidebar Navigation

### Vấn đề hiện tại
Sidebar được **copy-paste vào mỗi template riêng lẻ**, không có shared partial/include. Dẫn đến:
1. **3 biến thể sidebar khác nhau** đang tồn tại:
   - **Biến thể A** (`qc.html`, `qc_settings_*.html`): Full menu, collapsible settings submenu, không role-based filtering
   - **Biến thể B** (`cap.html`, `qc_dashboard.html`): Role-based filtering (`is_qc_role`, `is_qc_viewer_role`, `is_qaqt_role`), settings tách thành items riêng
   - **Biến thể C** (`qc_input_sp.html`): KHÔNG CÓ sidebar — là trang mobile-first hoàn toàn khác
2. **Styling khác nhau**: biến thể A dùng `bg-surface-lowest`, biến thể B dùng `bg-surface-high/70`
3. **Menu items khác nhau**: biến thể B thay "Kế hoạch sản xuất" bằng "Nhập liệu" khi `is_qc_role`

### Cấu trúc sidebar mong muốn (chuẩn)
```
📦 Kế hoạch sản xuất      → /qc
📊 Dashboard               → /qc/dashboard
✅ Hành động khắc phục     → /qc/cap
⚙️ Cài đặt danh mục       → (collapsible)
   ├─ Khách hàng - Mã hàng → /qc/settings/customer
   ├─ Bộ phận - Chi tiết    → /qc/settings/details
   ├─ Danh sách QC          → /qc/settings/qc-list
   └─ Sắp xếp vị trí       → /qc/settings/visual-picker
```

---

## Design Tokens (Tailwind config)

```js
colors: {
  surface:              '#f8f9fa',   // page background
  'surface-lowest':     '#ffffff',   // cards, containers
  'surface-low':        '#f3f4f6',   // input bg, hover states
  'surface-high':       '#e7e8e9',   // sidebar bg variant B
  'on-surface':         '#191c1d',   // primary text
  'on-surface-variant': '#424654',   // secondary text, labels
  primary:              '#0040a1',   // brand blue
  'primary-container':  '#0056d2',   // button gradient end
  'secondary-container':'#9cb4fe',   // badge active, toast success
  'error-container':    '#ffdad6',   // error states
}
fontFamily: {
  sans:    ['Inter', 'sans-serif'],
  display: ['Manrope', 'sans-serif'],
}
```

### CSS Classes chung (custom)
- `.glass-header` — sticky header với backdrop-filter blur
- `.btn-primary` — gradient button (#0040a1 → #0056d2)
- `.btn-tertiary` — transparent button, text primary
- `.input-field` — bg surface-low, border-none, rounded-xl
- `.data-table` — full-width table, sticky headers
- `.table-row` — hover effect with shadow
- `.badge` / `.badge-active` — pill badges
- `.modal-overlay` / `.modal-box` — centered modal with backdrop blur
- `.toast` / `.toast-success` / `.toast-error` — fixed bottom-right notification

---

## User Roles

Backend truyền các flag vào template context:
- `is_qc_role` — QC operator (thấy "Nhập liệu" thay vì "Kế hoạch sản xuất")
- `is_qc_viewer_role` — QC viewer (ẩn link Nhập liệu/Kế hoạch)
- `is_qaqt_role` — QAQT staff (thấy settings items)
- `user.name`, `user.don_vi`, `user.bo_phan` — thông tin user hiển thị header

---

## Quy tắc khi chỉnh sửa

### KHÔNG ĐƯỢC
- ❌ Thay đổi URL patterns của API endpoints (frontend JS đang gọi trực tiếp)
- ❌ Thay đổi response schema của API (key names trong JSON response)
- ❌ Đổi tên biến Jinja2 context (user, don_vi_options, is_qc_role, etc.)
- ❌ Xóa hoặc rename route paths (/qc, /qc/cap, /qc/dashboard, etc.)
- ❌ Thay đổi cấu trúc `main.py` mà không test lại toàn bộ flow
- ❌ Mix thêm framework CSS mới (đã có 2 framework rồi)

### NÊN LÀM
- ✅ Tách sidebar thành Jinja2 `{% include %}` partial để dùng chung
- ✅ Thống nhất Tailwind config/design tokens giữa các trang
- ✅ Chuẩn hóa role-based menu logic
- ✅ Thêm empty/loading/error states nhất quán
- ✅ Giữ nguyên `fetch()` + vanilla JS pattern, không thêm framework
- ✅ Tối ưu cho thao tác nhanh, lặp lại — ưu tiên ít click

### Khi thêm trang mới
1. Copy design tokens từ `qc.html` (Tailwind config block)
2. Include sidebar partial (khi đã tách)
3. Dùng `.glass-header`, `.input-field`, `.data-table`, `.modal-overlay` classes
4. Dùng Material Symbols Outlined cho icons
5. Dùng font Inter (body) + Manrope (headings)

---

## Static Mounts

| URL path | Serves from |
|----------|-------------|
| `/templates` | `templates/` directory (Logo.png, etc.) |
| `/api/pdf` | `pdf_files/` |
| `/api/images` | `images/` |
| `/static` | `gemba_cp/static/` |
