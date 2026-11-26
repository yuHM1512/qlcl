from collections import defaultdict
from datetime import date, datetime
from typing import Any, List, Optional, Dict, Tuple
from contextlib import asynccontextmanager
from datetime import timedelta
from datetime import timezone as _dt_timezone
from pydantic import BaseModel
import os
import re
import random
import sys
import shutil
import logging
import json
import threading
import time
from pathlib import Path as PathLib
import unicodedata
from urllib.parse import quote, unquote

from flat_line_sync import fetch_sheet_values as fetch_flat_line_sheet_values
from flat_line_sync import parse_flat_line_plans
from final_internal_sync import FinalApiClient, sync_final_internal
from bulletin_sync import (
    ensure_weekly_draft,
    get_bulletin_payload,
    parse_date as parse_bulletin_date,
    sync_bulletin_sources,
)

# Load environment variables from .env file
from dotenv import load_dotenv
load_dotenv()

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

from fastapi import FastAPI, Request, Form, Depends, HTTPException, Query, Path, File, UploadFile, Body
from fastapi.responses import RedirectResponse, JSONResponse, FileResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
# from starlette.middleware.sessions import SessionMiddleware

import psycopg2
import psycopg2.extras
import psycopg2.pool
try:
    import pyodbc
    PYODBC_AVAILABLE = True
except ImportError:
    PYODBC_AVAILABLE = False
from openpyxl import load_workbook
from openpyxl.styles import Alignment
from openpyxl.drawing.image import Image
try:
    import win32com.client  # type: ignore
    import pythoncom  # type: ignore
    WIN32_AVAILABLE = True
except ImportError:
    WIN32_AVAILABLE = False

from hdkp_pdf import render_hdkp_pdf


# Lấy cấu hình từ environment variables hoặc file .env
# Tất cả các biến này là bắt buộc, phải được cấu hình trong file .env hoặc environment variables
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise ValueError("DATABASE_URL environment variable is required. Please set it in .env file or environment variables.")

PROD_FACTORY_DATABASE_URL = os.getenv("PROD_FACTORY_DATABASE_URL")
if not PROD_FACTORY_DATABASE_URL:
    raise ValueError("PROD_FACTORY_DATABASE_URL environment variable is required. Please set it in .env file or environment variables.")

TEMPLATES_DIR = os.getenv("TEMPLATES_DIR")
if not TEMPLATES_DIR:
    raise ValueError("TEMPLATES_DIR environment variable is required. Please set it in .env file or environment variables.")

EXCEL_TEMPLATE_PATH = os.getenv("EXCEL_TEMPLATE_PATH")
if not EXCEL_TEMPLATE_PATH:
    raise ValueError("EXCEL_TEMPLATE_PATH environment variable is required. Please set it in .env file or environment variables.")

PDF_STORAGE_DIR = os.getenv("PDF_STORAGE_DIR")
if not PDF_STORAGE_DIR:
    raise ValueError("PDF_STORAGE_DIR environment variable is required. Please set it in .env file or environment variables.")

IMAGES_STORAGE_DIR = os.getenv("IMAGES_STORAGE_DIR")
if not IMAGES_STORAGE_DIR:
    raise ValueError("IMAGES_STORAGE_DIR environment variable is required. Please set it in .env file or environment variables.")


def env_flag(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


QTCN_AUTO_SYNC_ENABLED = env_flag("QTCN_AUTO_SYNC_ENABLED", default=True)
try:
    QTCN_AUTO_SYNC_INTERVAL_MINUTES = max(1, int(os.getenv("QTCN_AUTO_SYNC_INTERVAL_MINUTES", "60")))
except ValueError:
    QTCN_AUTO_SYNC_INTERVAL_MINUTES = 60

# --- Auto-sync PULL từ XNV2 SQL Server (QLCL chủ động kéo dữ liệu) ---
HL_XNV2_AUTO_SYNC_ENABLED = env_flag("HL_XNV2_AUTO_SYNC_ENABLED", default=False)
try:
    HL_XNV2_AUTO_SYNC_INTERVAL_MINUTES = max(1, int(os.getenv("HL_XNV2_AUTO_SYNC_INTERVAL_MINUTES", "60")))
except ValueError:
    HL_XNV2_AUTO_SYNC_INTERVAL_MINUTES = 60
# SQL Server của XNV2 — cấu hình riêng, có thể khác với HANGING_LINE_SQL_SERVER
XNV2_SQL_SERVER = os.getenv("XNV2_SQL_SERVER", "")
XNV2_APP_DB     = os.getenv("XNV2_APP_DB", "hanging_app")
XNV2_SQL_DRIVER = os.getenv("XNV2_SQL_DRIVER", "ODBC Driver 17 for SQL Server")
XNV2_DON_VI     = os.getenv("XNV2_DON_VI", "XNV2")

# --- Kế hoạch chuyền bệt từ Google Sheets ---
FLAT_LINE_GOOGLE_SERVICE_ACCOUNT_FILE = os.getenv(
    "FLAT_LINE_GOOGLE_SERVICE_ACCOUNT_FILE", "credentials_m29.json"
)
FLAT_LINE_SHEET_WORKSHEET = os.getenv("FLAT_LINE_SHEET_WORKSHEET", "Rải chuyền")
FLAT_LINE_SHEET_RANGE = os.getenv("FLAT_LINE_SHEET_RANGE", "A2:M")
FLAT_LINE_AUTO_SYNC_ENABLED = env_flag("FLAT_LINE_AUTO_SYNC_ENABLED", default=True)
try:
    FLAT_LINE_AUTO_SYNC_INTERVAL_MINUTES = max(
        1, int(os.getenv("FLAT_LINE_AUTO_SYNC_INTERVAL_MINUTES", "60"))
    )
except ValueError:
    FLAT_LINE_AUTO_SYNC_INTERVAL_MINUTES = 60
FLAT_LINE_SOURCES = {
    "XN1-V1": {
        "spreadsheet_id": os.getenv("FLAT_LINE_XN1_SPREADSHEET_ID", "").strip()
        or "1esz95MLJKBsgSHPnrmsKLRETzG1814QuAn8EuummsZw",
        "unit_number": 1,
    },
    "XN2": {
        "spreadsheet_id": os.getenv("FLAT_LINE_XN2_SPREADSHEET_ID", "").strip()
        or "1HvyqiIuV8gWXRpELT2UuSXoxNYYOuCCuC7ZtbfBBxK0",
        "unit_number": 2,
    },
    "XN3": {
        "spreadsheet_id": os.getenv("FLAT_LINE_XN3_SPREADSHEET_ID", "").strip()
        or "13vX5BhwE9l7QkTWN-30JyaipyVJLiHPtHHCgNFDe9cw",
        "unit_number": 3,
    },
}

# --- Internal Final QA sync from po.hachiba.app ---
FINAL_QA_API_BASE_URL = os.getenv("FINAL_QA_API_BASE_URL", "https://po.hachiba.app").rstrip("/")
FINAL_QA_API_USERNAME = os.getenv("FINAL_QA_API_USERNAME", "").strip()
FINAL_QA_API_PASSWORD = os.getenv("FINAL_QA_API_PASSWORD", "").strip()
try:
    FINAL_QA_SYNC_PAGE_SIZE = max(1, min(200, int(os.getenv("FINAL_QA_SYNC_PAGE_SIZE", "100"))))
except ValueError:
    FINAL_QA_SYNC_PAGE_SIZE = 100
try:
    FINAL_QA_SYNC_MAX_PAGES = max(0, int(os.getenv("FINAL_QA_SYNC_MAX_PAGES", "0")))
except ValueError:
    FINAL_QA_SYNC_MAX_PAGES = 0
FINAL_QA_AUTO_SYNC_ENABLED = env_flag("FINAL_QA_AUTO_SYNC_ENABLED", default=False)
try:
    FINAL_QA_AUTO_SYNC_INTERVAL_MINUTES = max(
        15, int(os.getenv("FINAL_QA_AUTO_SYNC_INTERVAL_MINUTES", "120"))
    )
except ValueError:
    FINAL_QA_AUTO_SYNC_INTERVAL_MINUTES = 120

BULLETIN_AUTO_SYNC_ENABLED = env_flag("BULLETIN_AUTO_SYNC_ENABLED", default=True)
try:
    BULLETIN_AUTO_SYNC_INTERVAL_MINUTES = max(
        15, int(os.getenv("BULLETIN_AUTO_SYNC_INTERVAL_MINUTES", "60"))
    )
except ValueError:
    BULLETIN_AUTO_SYNC_INTERVAL_MINUTES = 60

FINAL_CAP_ROLE = "FINAL_CAP"
FINAL_FACTORY_BY_DON_VI = {
    "XN1-V1": "XN01",
    "XN2": "XN02",
    "XN3": "XN03",
    "XNDT": "DT01",
}

DB_SCRIPTS_DIR = PathLib(__file__).resolve().parent / "db"
GEMBA_CP_BASE_DIR = PathLib(__file__).resolve().parent / "gemba_cp"
GEMBA_CP_STATIC_DIR = GEMBA_CP_BASE_DIR / "static"
GEMBA_CP_TEMPLATES_DIR = GEMBA_CP_BASE_DIR / "templates"

from gemba_cp.config import get_settings as get_gemba_settings
from gemba_cp.db import Base as GembaCPBase, engine as gemba_cp_engine
from gemba_cp.routers import admin as gemba_admin_router, dashboard as gemba_dashboard_router

gemba_cp_settings = get_gemba_settings()

SCHEMA_BOOTSTRAP_FILES = [
    "initialize_qlcl.sql",
    "migrate_ds_qa_to_quality_employees.sql",
    "alter_quality_employees_add_station.sql",
    "migrate_qc_roles_20260916.sql",
    "create_customer_hierarchy.sql",
    "create_error_classification.sql",
    "create_error_catalog_versioning.sql",
    "create_hdkp_tables.sql",
    "create_qa_final_internal.sql",
    "create_qa_final_hdkp.sql",
    "create_quality_bulletin.sql",
    "alter_quality_bulletin_updated_by.sql",
    "alter_quality_bulletin_saved_at.sql",
    "migrate_qa_final_cap_fail_only.sql",
    "migrate_final_cap_editors.sql",
    "migrate_final_cap_all_qc_leaders.sql",
    "create_prod_plan.sql",
    "migrate_prod_plan_bo_phan_json.sql",
    "create_qc_output_sp_log.sql",
    "migrate_qc_output_sp_log_status.sql",
    "migrate_tasks_qa_20260904.sql",
    "migrate_error_classification_20260909.sql",
    "migrate_kpi_impact_level_20260928.sql",
    "create_qc_error_hierarchy.sql",
    "create_qc_cum.sql",
    "migrate_dm_loai_hang_type.sql",
    "migrate_aovest_visual_picker.sql",
    "migrate_dm_chi_tiet_drop_ten_unique.sql",
    "migrate_visual_catalog_versioning.sql",
    "create_qc_error_log_sp.sql",
    "alter_qc_output_sp_log_add_station.sql",
    "alter_qc_sp_add_ma_nv.sql",
    "create_qc_defect_multi.sql",
    "alter_qc_defect_multi_add_station.sql",
    "alter_qc_defect_add_image_path.sql",
    "create_qc_error_dps.sql",
    "alter_qc_error_dps_add_keys.sql",
    "alter_qc_error_dps_add_station.sql",
    "alter_qc_error_dps_add_bo_phan.sql",
    "migrate_qc_station_names_20260917.sql",
    "create_qc_hdkp_endline.sql",
    "alter_prod_plan_add_po_info.sql",
    "alter_prod_plan_add_sync_fields.sql",
    "alter_prod_plan_add_is_finished.sql",
    "alter_prod_plan_add_mono.sql",
    "create_qc_hanging_output.sql",
    "migrate_perf_indexes_20261028.sql",
    "alter_qa_final_hdkp_completed.sql",
    "create_qc_client_request.sql",
    "migrate_qc_input_perf_20261125.sql",
]

# Tạo thư mục lưu PDF và images nếu chưa có
os.makedirs(PDF_STORAGE_DIR, exist_ok=True)
os.makedirs(IMAGES_STORAGE_DIR, exist_ok=True)
os.makedirs(os.path.join(IMAGES_STORAGE_DIR, "qc_sp"), exist_ok=True)


_db_pool = psycopg2.pool.ThreadedConnectionPool(
    minconn=2, maxconn=10, dsn=DATABASE_URL
)

_prod_factory_pool = psycopg2.pool.ThreadedConnectionPool(
    minconn=1, maxconn=4, dsn=PROD_FACTORY_DATABASE_URL
)


class _PooledConnection:
    """Context manager that returns a connection to the pool on exit."""
    __slots__ = ("_pool", "_conn")

    def __init__(self, pool):
        self._pool = pool
        self._conn = pool.getconn()

    def __enter__(self):
        return self._conn

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is not None:
            self._conn.rollback()
        self._pool.putconn(self._conn)
        return False

    @property
    def autocommit(self):
        return self._conn.autocommit

    @autocommit.setter
    def autocommit(self, value):
        self._conn.autocommit = value

    def cursor(self, *a, **kw):
        return self._conn.cursor(*a, **kw)

    def commit(self):
        return self._conn.commit()

    def rollback(self):
        return self._conn.rollback()


def get_db_connection():
    return _PooledConnection(_db_pool)


def get_prod_factory_connection():
    return _PooledConnection(_prod_factory_pool)


# --- Cache prod_plan.bo_phan column type (avoid information_schema on every request) ---
_PROD_PLAN_BO_PHAN_IS_JSONB: Optional[bool] = None


def _detect_bo_phan_jsonb() -> bool:
    global _PROD_PLAN_BO_PHAN_IS_JSONB
    if _PROD_PLAN_BO_PHAN_IS_JSONB is not None:
        return _PROD_PLAN_BO_PHAN_IS_JSONB
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT data_type FROM information_schema.columns
                WHERE table_schema='public' AND table_name='prod_plan' AND column_name='bo_phan'
                LIMIT 1
            """)
            row = cur.fetchone()
            _PROD_PLAN_BO_PHAN_IS_JSONB = (row[0] == "jsonb") if row else False
    return _PROD_PLAN_BO_PHAN_IS_JSONB


# --- Hanging Line (SQL Server) connection ---
HANGING_LINE_SQL_SERVER = os.getenv("HANGING_LINE_SQL_SERVER", r".\SQLEXPRESS")
HANGING_LINE_APP_DB = os.getenv("HANGING_LINE_APP_DB", "hanging_app")
HANGING_LINE_SQL_DRIVER = os.getenv("HANGING_LINE_SQL_DRIVER", "ODBC Driver 17 for SQL Server")
HANGING_LINE_DON_VI = os.getenv("QLCL_DON_VI", "Chuyền treo")  # don_vi for prod_plan sync


def get_hanging_line_connection():
    """Connect to SQL Server hanging-line DB (read-only, Windows Auth)."""
    if not PYODBC_AVAILABLE:
        raise RuntimeError("pyodbc chưa được cài đặt. Chạy: pip install pyodbc")
    conn_str = (
        f"DRIVER={{{HANGING_LINE_SQL_DRIVER}}};"
        f"SERVER={HANGING_LINE_SQL_SERVER};"
        f"DATABASE={HANGING_LINE_APP_DB};"
        "Trusted_Connection=yes;"
        "TrustServerCertificate=yes;"
    )
    return pyodbc.connect(conn_str, autocommit=True)


def get_effective_defect_catalog_id(cur, effective_date: Optional[str] = None) -> Optional[int]:
    """Return the latest defect catalog effective for a date; defaults to today."""
    date_value = effective_date or datetime.now().strftime("%Y-%m-%d")
    cur.execute(
        """
        SELECT id
        FROM public.dm_defect_catalog
        WHERE effective_from <= %s::date
          AND (effective_to IS NULL OR effective_to >= %s::date)
        ORDER BY effective_from DESC, id DESC
        LIMIT 1
        """,
        (date_value, date_value),
    )
    row = cur.fetchone()
    if isinstance(row, dict):
        return row.get("id")
    return row[0] if row else None


def get_effective_visual_catalog(cur, loai_hang_id: int, effective_date: date) -> Tuple[Optional[Dict], bool]:
    """Return the product visual version for a business date.

    The boolean says whether the product has any version records. It lets old,
    unversioned installations continue to use rows with visual_catalog_id NULL,
    while a date outside a versioned product's ranges correctly returns no rows.
    """
    cur.execute(
        """
        SELECT id, version_code, name, effective_from, effective_to, source_file
        FROM public.dm_visual_catalog
        WHERE loai_hang_id = %s
          AND effective_from <= %s
          AND (effective_to IS NULL OR effective_to >= %s)
        ORDER BY effective_from DESC, id DESC
        LIMIT 1
        """,
        (loai_hang_id, effective_date, effective_date),
    )
    row = cur.fetchone()
    if row:
        return dict(row), True
    cur.execute(
        "SELECT EXISTS(SELECT 1 FROM public.dm_visual_catalog WHERE loai_hang_id = %s)",
        (loai_hang_id,),
    )
    exists_row = cur.fetchone()
    has_versions = bool(
        exists_row.get("exists") if isinstance(exists_row, dict) else exists_row[0]
    )
    return None, has_versions


def bootstrap_qlcl_schema():
    """Run bundled idempotent SQL scripts so a fresh environment can self-bootstrap."""
    with get_db_connection() as conn:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS public.app_schema_bootstrap (
                    script_name TEXT PRIMARY KEY,
                    executed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
            for script_name in SCHEMA_BOOTSTRAP_FILES:
                script_path = DB_SCRIPTS_DIR / script_name
                if not script_path.exists():
                    raise FileNotFoundError(f"Missing schema bootstrap script: {script_path}")
                cur.execute(
                    "SELECT 1 FROM public.app_schema_bootstrap WHERE script_name = %s",
                    (script_name,),
                )
                if cur.fetchone():
                    continue
                logger.info("Bootstrapping schema with %s", script_name)
                sql_text = script_path.read_text(encoding="utf-8-sig")
                cur.execute(sql_text)
                cur.execute(
                    """
                    INSERT INTO public.app_schema_bootstrap (script_name)
                    VALUES (%s)
                    ON CONFLICT (script_name) DO NOTHING
                    """,
                    (script_name,),
                )


def generate_ma_nv_variants(ma_nv: str) -> List[str]:
    """Generate uppercase variants for mã nhân viên, handling Vietnamese characters like Đ."""
    if not ma_nv:
        return []
    base = ma_nv.strip().upper()
    variants = []
    if base:
        variants.append(base)
    simplified = ''.join(
        ch for ch in unicodedata.normalize('NFKD', base)
        if not unicodedata.combining(ch)
    )
    simplified = simplified.replace('Đ', 'D').replace('đ', 'D').upper()
    if simplified and simplified not in variants:
        variants.append(simplified)
    return variants if variants else [base]


KPI_IMPACT_LEVEL_OPTIONS = {
    "Ảnh hưởng đến MTCL công ty",
    "Chưa ảnh hưởng đến MTCL công ty",
    "Ảnh hưởng đến MTCL phòng",
    "Chưa ảnh hưởng đến MTCL phòng",
}

LEGACY_KPI_IMPACT_LEVEL_MAP = {
    "Ảnh hưởng đến MTCL công ty/phòng": "Ảnh hưởng đến MTCL phòng",
    "Chưa ảnh hưởng đến MTCL công ty/phòng": "Chưa ảnh hưởng đến MTCL phòng",
}


def normalize_kpi_impact_level(value: Any) -> Optional[str]:
    """Normalize legacy KPI impact labels and reject unsupported values."""
    if value is None or str(value).strip() == "":
        return None
    normalized = str(value).strip()
    normalized = LEGACY_KPI_IMPACT_LEVEL_MAP.get(normalized, normalized)
    if normalized not in KPI_IMPACT_LEVEL_OPTIONS:
        raise HTTPException(status_code=400, detail="Mức độ ảnh hưởng không hợp lệ")
    return normalized


def encode_ma_nv_cookie(ma_nv: str) -> str:
    """Percent-encode mã nhân viên để lưu trong cookie (tránh lỗi latin-1)."""
    if not ma_nv:
        return ""
    try:
        return quote(ma_nv.strip())
    except Exception:
        return quote(str(ma_nv))


def decode_ma_nv_cookie(value: Optional[str]) -> str:
    """Giải mã giá trị mã nhân viên từ cookie."""
    if not value:
        return ""
    try:
        return unquote(value)
    except Exception:
        return value


def normalize_bo_phan_value(value: Optional[str]) -> str:
    """Normalize team input so 'To 3'/'Tổ 3' become '3'."""
    raw = (value or "").strip()
    if not raw:
        return ""
    match = re.search(r"(\d+)", raw)
    if match:
        return match.group(1)
    return raw


def get_authenticated_user(request: Request, qc_only: bool = False) -> Optional[Dict]:
    """Lấy thông tin nhân viên từ cookie; trả về None nếu chưa đăng nhập hoặc cookie không hợp lệ."""
    ma_nv_cookie = request.cookies.get("ma_nv")
    if not ma_nv_cookie:
        return None

    ma_nv = decode_ma_nv_cookie(ma_nv_cookie)
    ma_nv_variants = generate_ma_nv_variants(ma_nv)
    if not ma_nv_variants:
        return None

    query = """
        SELECT ma_nv, ho_ten as name, chuc_vu as department, qc_role, don_vi, bo_phan, station
        FROM public.quality_employees
        WHERE ma_nv = ANY(%s)
    """
    params: List[Any] = [ma_nv_variants]
    if qc_only:
        query += " AND qc_role = 'QC'"
    query += """
        ORDER BY CASE WHEN ma_nv = %s THEN 0 ELSE 1 END
        LIMIT 1
    """
    params.append(ma_nv)

    with get_db_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(query, tuple(params))
            user = cur.fetchone()

    return dict(user) if user else None


def require_authenticated_api_user(request: Request) -> Dict:
    """Dependency bảo vệ các API chỉ cho người đã đăng nhập."""
    user = get_authenticated_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Chưa đăng nhập")
    return user


def require_qa_admin_api_user(request: Request) -> Dict:
    """Dependency chỉ cho QA_ADMIN — dùng cho thao tác tinh chỉnh master data."""
    return require_qc_role(request, QC_SETTINGS_ROLES)


QC_DON_VI_SCOPED_ROLES = {"FACTORY_ADMIN", "QC"}

QC_KNOWN_ROLES = {"QC", "QA_ADMIN", "FACTORY_ADMIN"}
QC_DASHBOARD_ROLES = QC_KNOWN_ROLES
QC_SETTINGS_ROLES = {"QA_ADMIN"}
QC_EMPLOYEE_MGMT_ROLES = {"QA_ADMIN", "FACTORY_ADMIN"}
QC_PLAN_ROLES = {"QA_ADMIN", "FACTORY_ADMIN"}


def get_qc_role(user: Optional[Dict]) -> str:
    return ((user or {}).get("qc_role") or "").upper()


def get_final_factory_scope(user: Optional[Dict]) -> Optional[str]:
    """Return the source-API factory code assigned to a Final CAP editor."""
    if get_qc_role(user) != FINAL_CAP_ROLE:
        return None
    don_vi = ((user or {}).get("don_vi") or "").strip()
    factory = FINAL_FACTORY_BY_DON_VI.get(don_vi)
    if not factory:
        raise HTTPException(status_code=403, detail="Tài khoản chưa được gán Xí nghiệp Final hợp lệ")
    return factory


def require_final_cap_access(user: Dict, *, factory: Optional[str] = None) -> Optional[str]:
    """Allow QA admins globally and Final CAP editors only inside their factory."""
    role = get_qc_role(user)
    if role == FINAL_CAP_ROLE:
        scoped_factory = get_final_factory_scope(user)
        if factory is not None and factory != scoped_factory:
            raise HTTPException(status_code=403, detail="Không có quyền thao tác dữ liệu Final của Xí nghiệp khác")
        return scoped_factory
    if can_manage_final_sync(user):
        return None
    raise HTTPException(status_code=403, detail="Tài khoản không có quyền nhập HĐKP Final")


def check_final_hdkp_error_access(user: Dict, error_id: int) -> None:
    """Scope Final-linked HĐKP while leaving legacy non-Final HĐKP unchanged."""
    with get_db_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT factory FROM public.qa_final_inspection WHERE cap_error_id = %s",
                (error_id,),
            )
            inspection = cur.fetchone()
    if inspection:
        require_final_cap_access(user, factory=inspection.get("factory"))


def is_qc_don_vi_scoped_role(user: Optional[Dict]) -> bool:
    return get_qc_role(user) in QC_DON_VI_SCOPED_ROLES


def require_qc_role(request: Request, allowed_roles: set) -> Dict:
    user = get_authenticated_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Chưa đăng nhập")
    role = get_qc_role(user)
    if role not in allowed_roles:
        raise HTTPException(status_code=403, detail="Tài khoản không có quyền truy cập chức năng này.")
    if role in QC_DON_VI_SCOPED_ROLES and (user.get("don_vi") or "").strip() not in DON_VI_OPTIONS:
        raise HTTPException(status_code=403, detail="Tài khoản chưa được gán Xí nghiệp hợp lệ.")
    return user


def require_qc_api_user(request: Request) -> Dict:
    return require_qc_role(request, QC_KNOWN_ROLES)


def require_qc_input_user(request: Request) -> Dict:
    return require_qc_role(request, {"QC"})


def require_employee_mgmt_user(request: Request) -> Dict:
    """QA_ADMIN or FACTORY_ADMIN — for employee management."""
    return require_qc_role(request, QC_EMPLOYEE_MGMT_ROLES)


def require_plan_admin(request: Request) -> Dict:
    return require_qc_role(request, QC_PLAN_ROLES)


def check_factory_access(user: Dict, don_vi: Optional[str]) -> None:
    if is_qc_don_vi_scoped_role(user):
        scope = (user.get("don_vi") or "").strip()
        if scope not in DON_VI_OPTIONS or don_vi != scope:
            raise HTTPException(status_code=403, detail="Không có quyền thao tác ngoài Xí nghiệp được gán.")


def check_plan_access(user: Dict, plan_id: int) -> None:
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT don_vi FROM public.prod_plan WHERE id = %s", (plan_id,))
            row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Không tìm thấy kế hoạch")
    check_factory_access(user, row[0])


def require_plan_reader(request: Request, plan_id: int = Query(...)) -> Dict:
    user = require_qc_api_user(request)
    check_plan_access(user, plan_id)
    return user


def resolve_qc_don_vi_scope(request: Request, requested_don_vi: Optional[str]) -> Tuple[Optional[str], Dict]:
    """Resolve the factory filter from application permissions, never from position."""
    user = require_qc_api_user(request)
    if is_qc_don_vi_scoped_role(user):
        scoped_don_vi = (user.get("don_vi") or "").strip()
        if not scoped_don_vi:
            raise HTTPException(status_code=403, detail="Tài khoản chưa được gán đơn vị quản lý.")
        return scoped_don_vi, user
    role = get_qc_role(user)
    if role not in QC_DASHBOARD_ROLES:
        raise HTTPException(status_code=403, detail="Tài khoản không có quyền xem dashboard.")
    return requested_don_vi, user


QC_INPUT_HOME = "/qc-input"


def post_login_target(qc_role: Optional[str], next_url: str = "") -> str:
    '''Trang đích sau đăng nhập: next hợp lệ > QC vào thẳng nhập liệu > trang chủ.'''
    next_url = (next_url or "").strip()
    if next_url.startswith("/") and not next_url.startswith("//") and next_url != "/":
        return next_url
    if (qc_role or "").upper() == "QC":
        return QC_INPUT_HOME
    return "/"


def redirect_to_login_for_current_path(request: Request) -> RedirectResponse:
    path = str(request.url.path)
    if request.url.query:
        path = f"{path}?{request.url.query}"
    return RedirectResponse(url=f"/login?next={quote(path, safe='/?=&%')}", status_code=303)


def resolve_dashboard_default_station(
    cur,
    *,
    station: Optional[str] = None,
    scoped_user: Optional[Dict] = None,
    don_vi: Optional[str] = None,
    bo_phan: Optional[str] = None,
    ma_hang: Optional[str] = None,
    type_name: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    date_before: Optional[str] = None,
    resolved_bo_phan_expr: str = "COALESCE(NULLIF(qe.bo_phan, ''), '')",
) -> str:
    station_clean = (station or "").strip()
    if station_clean:
        return station_clean

    if not is_qc_don_vi_scoped_role(scoped_user):
        return "QC sau seam"

    where_clauses = ["o.station IS NOT NULL", "o.station <> ''"]
    params: List[Any] = []
    if date_from and date_to:
        where_clauses.append("o.date BETWEEN %s AND %s")
        params.extend([date_from, date_to])
    elif date_before:
        where_clauses.append("o.date < %s")
        params.append(date_before)
    if don_vi:
        where_clauses.append("p.don_vi = %s")
        params.append(don_vi)
    if bo_phan:
        where_clauses.append(f"{resolved_bo_phan_expr} = %s")
        params.append(bo_phan)
    if ma_hang:
        where_clauses.append("COALESCE(p.ma_hang, '') = %s")
        params.append(ma_hang)
    if type_name:
        where_clauses.append("COALESCE(tgt.type, '') = %s")
        params.append(type_name)

    cur.execute(
        f"""
        SELECT o.station
        FROM public.qc_output_sp_log o
        JOIN public.prod_plan p ON p.id = o.plan_id
        LEFT JOIN public.quality_employees qe ON qe.ma_nv = o.ma_nv
        LEFT JOIN public.dm_loai_hang lh ON lh.ten_loai = p.loai_hang
        LEFT JOIN public.dm_loai_hang_target tgt ON tgt.id_type = lh.id_type
        WHERE {" AND ".join(where_clauses)}
        GROUP BY o.station
        ORDER BY SUM(CASE WHEN o.delta > 0 THEN o.delta ELSE 0 END) DESC, o.station
        LIMIT 1
        """,
        tuple(params),
    )
    row = cur.fetchone() or {}
    return (row.get("station") or "").strip()


def build_qc_template_context(request: Request, user: Optional[Dict], **extra) -> Dict[str, Any]:
    role = get_qc_role(user)
    context: Dict[str, Any] = {
        "request": request,
        "user": user,
        "qc_role": role,
        "is_qc_role": role == "QC",
        "is_qa_admin": role == "QA_ADMIN",
        "can_manage_plans": role in QC_PLAN_ROLES,
        "is_qc_viewer_role": role in QC_DON_VI_SCOPED_ROLES,
        "qc_scope_don_vi": ((user or {}).get("don_vi") or "") if role in QC_DON_VI_SCOPED_ROLES else "",
    }
    context.update(extra)
    if role in QC_DON_VI_SCOPED_ROLES and "don_vi_options" in context:
        context["don_vi_options"] = [user.get("don_vi")] if user.get("don_vi") in DON_VI_OPTIONS else []
    return context


def build_static_asset_version(asset_path: PathLib) -> str:
    """Use file mtime as a simple cache-busting version for static assets."""
    try:
        return str(int(asset_path.stat().st_mtime))
    except FileNotFoundError:
        return "0"


def _is_merged_cell(ws, cell):
    """
    Kiểm tra xem cell có phải là merged cell không.
    Trả về True nếu là merged cell, False nếu không.
    """
    try:
        # Kiểm tra xem cell có nằm trong merged range không
        for merged_range in ws.merged_cells.ranges:
            if cell.coordinate in merged_range:
                # Kiểm tra xem có phải là top-left cell không
                min_col, min_row, max_col, max_row = merged_range.bounds
                if cell.row == min_row and cell.column == min_col:
                    return False  # Đây là top-left cell, có thể ghi được
                else:
                    return True  # Đây là merged cell nhưng không phải top-left
        return False
    except Exception:
        return False


def fill_excel_template(template_path: str, data: Dict, output_path: str):
    """
    Điền biến {{variable}} hoặc {{variable_N}} vào Excel template.
    
    Template có thể có:
    - Biến có số: {{a_root_cause_1}}, {{a_root_cause_2}}, ...
    - Biến không có số: {{a_root_cause}} ở nhiều dòng (mỗi dòng sẽ điền theo số thứ tự)
    
    Logic:
    1. Xử lý các section (A, B, III) - tìm các dòng có biến không có số và điền theo thứ tự
    2. Xử lý các biến có số - điền trực tiếp
    3. Xử lý các biến khác (Section I)
    4. Nếu có biến nhưng không có dữ liệu, để trống (không điền "trống")
    5. Tự động bật wrap text cho các cell được điền dữ liệu
    """
    try:
        wb = load_workbook(template_path)
        ws = wb.active
        
        # Xử lý Section II A: tìm các dòng có {{a_root_cause}} và điền theo thứ tự
        _fill_section_with_sequential_rows(ws, 'a_root_cause', data, 
                                           ['a_root_cause', 'a_hđkp_tuc_thoi', 'a_hđ_phong_ngua', 
                                            'a_tg_theo_doi', 'a_trach_nhiem', 'a_tg_thuc_hien'])
        
        # Xử lý Section II B
        _fill_section_with_sequential_rows(ws, 'b_root_cause', data,
                                           ['b_root_cause', 'b_hđkp_tuc_thoi', 'b_hđ_phong_ngua',
                                            'b_tg_theo_doi', 'b_trach_nhiem', 'b_tg_thuc_hien'])
        
        # Xử lý Section III
        _fill_section_with_sequential_rows(ws, 'cong_viec', data,
                                           ['stt', 'cong_viec', 'trach_nhiem', 'ngay_bat_dau',
                                            'ngay_hoan_thanh', 'giam_sat', 'ket_qua_dat', 'ket_qua_khong_dat', 'ket_luan'])
        
        # Xử lý hình ảnh (vd_image) - chèn hình ảnh vào cell
        _insert_image_to_cell(ws, data.get('vd_image', ''))
        
        # Xử lý các biến khác (Section I và các biến có số hoặc đơn lẻ)
        for row in ws.iter_rows():
            for cell in row:
                # B? qua merged cells (tr? top-left)
                if _is_merged_cell(ws, cell):
                    continue
                
                if cell.value and isinstance(cell.value, str):
                    # Tìm tất cả các biến {{variable}} hoặc {{variable_N}}
                    pattern = r'\{\{(\w+(?:_\d+)?)\}\}'
                    matches = re.findall(pattern, cell.value)
                    
                    if not matches:
                        continue
                    
                    original_value = cell.value
                    has_replacement = False
                    
                    for var_name in matches:
                        # Bỏ qua vd_image (đã xử lý riêng bằng _insert_image_to_cell)
                        if var_name == 'vd_image':
                            continue
                        
                        # Bỏ qua các biến đã xử lý trong sections (nếu không có số)
                        if var_name in ['a_root_cause', 'b_root_cause', 'cong_viec'] or \
                           var_name.startswith('a_root_cause') or var_name.startswith('b_root_cause') or \
                           var_name.startswith('cong_viec') or var_name.startswith('stt') or \
                           var_name.startswith('ket_qua_dat') or var_name.startswith('ket_qua_khong_dat'):
                            # Chỉ xử lý nếu có số (đã xử lý ở trên)
                            if '_' in var_name and var_name.split('_')[-1].isdigit():
                                continue
                            # Nếu không có số, đã xử lý ở _fill_section_with_sequential_rows
                            continue
                        
                        # Bỏ qua ket_qua: đã được xử lý trong _fill_section_with_sequential_rows cho Section III
                        # Chỉ xử lý ở đây nếu không phải là Section III (không có {{cong_viec}} trong dòng)
                        if var_name == 'ket_qua' or (var_name.startswith('ket_qua') and var_name != 'ket_qua_dat' and var_name != 'ket_qua_khong_dat'):
                            # Kiểm tra xem dòng này có thuộc Section III không (có {{cong_viec}})
                            is_section_iii = False
                            for check_cell in ws[cell.row]:
                                if check_cell.value and isinstance(check_cell.value, str):
                                    if '{{cong_viec}}' in check_cell.value or '{{cong_viec_' in str(check_cell.value):
                                        is_section_iii = True
                                        break
                            
                            # Nếu thuộc Section III, bỏ qua (đã xử lý trong _fill_section_with_sequential_rows)
                            if is_section_iii:
                                continue
                            
                            # Nếu không thuộc Section III, xử lý như bình thường (trường hợp đặc biệt)
                            # Tìm số thứ tự (nếu có)
                            if '_' in var_name and var_name.split('_')[-1].isdigit():
                                idx = int(var_name.split('_')[-1])
                            else:
                                idx = 1  # Mặc định là 1
                            
                            # Chỉ xử lý nếu có dữ liệu tương ứng
                            ket_qua_dat = data.get(f'ket_qua_dat_{idx}', '')
                            ket_qua_khong_dat = data.get(f'ket_qua_khong_dat_{idx}', '')
                            
                            # Chỉ xử lý nếu có dữ liệu
                            if not ket_qua_dat and not ket_qua_khong_dat:
                                continue
                            
                            # Tìm tất cả các cell trong cùng dòng có chứa biến {{ket_qua}} hoặc {{ket_qua_N}}
                            pattern_str = '{{' + var_name + '}}'
                            ket_qua_cells = []
                            
                            # Quét toàn bộ dòng để tìm tất cả các cell có chứa biến này
                            for col in range(1, ws.max_column + 1):
                                try:
                                    row_cell = ws.cell(row=cell.row, column=col)
                                    if row_cell.value and isinstance(row_cell.value, str):
                                        if pattern_str in str(row_cell.value):
                                            ket_qua_cells.append(col)
                                except Exception:
                                    pass
                            
                            # Nếu tìm thấy 2 cell, điền vào: cell đầu tiên = Đạt, cell thứ hai = Không đạt
                            if len(ket_qua_cells) >= 2:
                                # Cell đầu tiên: cột trái (Đạt)
                                try:
                                    cell1 = ws.cell(row=cell.row, column=ket_qua_cells[0])
                                    if cell1.value and isinstance(cell1.value, str):
                                        cell1.value = cell1.value.replace(pattern_str, ket_qua_dat)
                                        if not cell1.value or cell1.value.strip() == '':
                                            cell1.value = None
                                except Exception:
                                    pass
                                
                                # Cell thứ hai: cột phải (Không đạt)
                                try:
                                    cell2 = ws.cell(row=cell.row, column=ket_qua_cells[1])
                                    if cell2.value and isinstance(cell2.value, str):
                                        cell2.value = cell2.value.replace(pattern_str, ket_qua_khong_dat)
                                        if not cell2.value or cell2.value.strip() == '':
                                            cell2.value = None
                                except Exception:
                                    pass
                            elif len(ket_qua_cells) == 1:
                                # Chỉ có 1 cell, điền vào cell hiện tại (cột trái - Đạt)
                                if pattern_str in original_value:
                                    original_value = original_value.replace(pattern_str, ket_qua_dat)
                                    has_replacement = True
                            
                            # Bỏ qua biến này trong vòng lặp tiếp theo
                            continue
                        
                        # Lấy giá trị từ data dict
                        value = data.get(var_name, '')
                        
                        # Nếu không có giá trị, để trống (không điền "trống")
                        if not value:
                            value = ''
                        
                        # Nếu biến không có số, thử lấy từ _1
                        if '_' not in var_name or not var_name.split('_')[-1].isdigit():
                            var_with_1 = var_name + '_1'
                            if var_with_1 in data:
                                value = data.get(var_with_1, '')
                        
                        # Thay thế biến bằng giá trị
                        pattern_str = '{{' + var_name + '}}'
                        if pattern_str in original_value:
                            original_value = original_value.replace(pattern_str, str(value))
                            has_replacement = True
                    
                    # Cập nhật cell và bật wrap text
                    if has_replacement:
                        try:
                            cell.value = original_value if original_value else None
                            if cell.value:
                                _set_wrap_text(cell)
                        except Exception as cell_error:
                            # Nếu có lỗi (merged cell, etc.), bỏ qua
                            logger.debug(f"B? qua cell {cell.coordinate}: {cell_error}")
        
        wb.save(output_path)
        logger.info(f"Đã lưu Excel file: {output_path}")
        return output_path
    except Exception as e:
        logger.error(f"Lá»—i trong fill_excel_template: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Lỗi khi điền Excel template: {str(e)}")


def _fill_section_with_sequential_rows(ws, base_var_name: str, data: Dict, var_patterns: List[str]):
    """
    Tìm các dòng có biến không có số (ví dụ {{a_root_cause}}) và điền theo thứ tự:
    - Dòng đầu tiên: điền với _1
    - Dòng thứ hai: điền với _2
    - Dòng thứ ba: điền với _3
    - Nếu không có dữ liệu, để trống
    """
    # Tìm tất cả các dòng có chứa biến không có số
    rows_with_base_var = []
    
    for row_idx, row in enumerate(ws.iter_rows(), start=1):
        for cell in row:
            if _is_merged_cell(ws, cell):
                continue
            if cell.value and isinstance(cell.value, str):
                if '{{' + base_var_name + '}}' in cell.value:
                    rows_with_base_var.append(row_idx)
                    break
    
    # Tìm số thứ tự tối đa có trong data (tính một lần ở đầu)
    max_idx = 0
    for key in data.keys():
        if key.startswith(base_var_name + '_'):
            try:
                key_idx = int(key.split('_')[-1])
                max_idx = max(max_idx, key_idx)
            except ValueError:
                pass
    
    # Điền dữ liệu vào từng dòng theo thứ tự
    for idx, row_idx in enumerate(rows_with_base_var, start=1):
        # Nếu dòng này vượt quá số lượng items có trong data, để trống
        if idx > max_idx:
            # Xóa tất cả các biến trong dòng này (để trống), bao gồm cả ket_qua
            for cell in ws[row_idx]:
                if _is_merged_cell(ws, cell):
                    continue
                if cell.value and isinstance(cell.value, str):
                    # Xóa tất cả các biến bao gồm ket_qua
                    for var_name in var_patterns:
                        pattern_str = '{{' + var_name + '}}'
                        if pattern_str in cell.value:
                            cell.value = cell.value.replace(pattern_str, '')
                    # Xóa {{ket_qua}} và {{ket_qua_N}} nếu có
                    if '{{ket_qua}}' in cell.value:
                        cell.value = cell.value.replace('{{ket_qua}}', '')
                    if f'{{ket_qua_{idx}}}' in cell.value:
                        cell.value = cell.value.replace(f'{{ket_qua_{idx}}}', '')
                    if not cell.value or cell.value.strip() == '':
                        cell.value = None
        else:
            # Xử lý đặc biệt cho ket_qua: tìm tất cả các cell có {{ket_qua}} hoặc {{ket_qua_N}} trong dòng này
            ket_qua_cells = []
            for cell_temp in ws[row_idx]:
                if _is_merged_cell(ws, cell_temp):
                    continue
                if cell_temp.value and isinstance(cell_temp.value, str):
                    # Tìm {{ket_qua}} hoặc {{ket_qua_N}}
                    if '{{ket_qua}}' in cell_temp.value or f'{{ket_qua_{idx}}}' in cell_temp.value:
                        ket_qua_cells.append(cell_temp.column)
            
            # Nếu tìm thấy 2 cell có {{ket_qua}}, điền vào 2 cell đó (chỉ khi có dữ liệu)
            if len(ket_qua_cells) >= 2:
                ket_qua_dat = data.get(f'ket_qua_dat_{idx}', '')
                ket_qua_khong_dat = data.get(f'ket_qua_khong_dat_{idx}', '')
                
                # Cell đầu tiên: cột trái (Đạt)
                try:
                    cell1 = ws.cell(row=row_idx, column=ket_qua_cells[0])
                    if cell1.value and isinstance(cell1.value, str):
                        cell1.value = cell1.value.replace('{{ket_qua}}', ket_qua_dat).replace(f'{{ket_qua_{idx}}}', ket_qua_dat)
                        if not cell1.value or cell1.value.strip() == '':
                            cell1.value = None
                except Exception:
                    pass
                
                # Cell thứ hai: cột phải (Không đạt)
                try:
                    cell2 = ws.cell(row=row_idx, column=ket_qua_cells[1])
                    if cell2.value and isinstance(cell2.value, str):
                        cell2.value = cell2.value.replace('{{ket_qua}}', ket_qua_khong_dat).replace(f'{{ket_qua_{idx}}}', ket_qua_khong_dat)
                        if not cell2.value or cell2.value.strip() == '':
                            cell2.value = None
                except Exception:
                    pass
            
            # Điền dữ liệu với số thứ tự idx cho các biến khác
            for cell in ws[row_idx]:
                if _is_merged_cell(ws, cell):
                    continue
                if cell.value and isinstance(cell.value, str):
                    original_value = cell.value
                    has_replacement = False
                    
                    # Bỏ qua nếu cell này đã được xử lý cho ket_qua
                    if cell.column in ket_qua_cells:
                        continue
                    
                    for var_name in var_patterns:
                        # Bỏ qua ket_qua_dat và ket_qua_khong_dat vì đã xử lý ở trên
                        if var_name == 'ket_qua_dat' or var_name == 'ket_qua_khong_dat':
                            continue
                        
                        # Tạo biến với số thứ tự
                        var_with_idx = var_name + '_' + str(idx)
                        value = data.get(var_with_idx, '')
                        
                        # Nếu không có giá trị, để trống
                        if not value:
                            value = ''
                        
                        # Thay thế biến (có thể là không có số hoặc có số)
                        pattern_no_num = '{{' + var_name + '}}'
                        pattern_with_num = '{{' + var_name + '_' + str(idx) + '}}'
                        
                        if pattern_no_num in original_value:
                            original_value = original_value.replace(pattern_no_num, str(value))
                            has_replacement = True
                        if pattern_with_num in original_value:
                            original_value = original_value.replace(pattern_with_num, str(value))
                            has_replacement = True
                    
                    if has_replacement:
                        try:
                            cell.value = original_value if original_value else None
                            if cell.value:
                                _set_wrap_text(cell)
                        except Exception as cell_error:
                            logger.debug(f"B? qua cell {cell.coordinate}: {cell_error}")


def _process_section_rows(ws, base_var_name: str, max_items: int, data: Dict, var_patterns: List[str]):
    """
    Xử lý một section: tìm dòng template, điền dữ liệu và duplicate nếu cần.
    """
    # Tìm dòng template (dòng đầu tiên có biến không có số)
    template_row_idx = None
    for row_idx, row in enumerate(ws.iter_rows(), start=1):
        for cell in row:
            if cell.value and isinstance(cell.value, str):
                if '{{' + base_var_name + '}}' in cell.value:
                    template_row_idx = row_idx
                    break
        if template_row_idx:
            break
    
    if not template_row_idx:
        return  # Không tìm thấy template row
    
    # Điền dữ liệu vào dòng đầu tiên (item 1)
    _fill_row_data(ws, template_row_idx, base_var_name, 1, data, var_patterns)
    
    # Nếu có nhiều items, duplicate và điền vào các dòng tiếp theo
    if max_items > 1:
        for idx in range(2, max_items + 1):
            # Tìm dòng trống tiếp theo hoặc duplicate dòng template
            new_row_idx = template_row_idx + (idx - 1)
            
            # Kiểm tra xem dòng này có tồn tại không, nếu không thì insert
            if new_row_idx > ws.max_row:
                ws.insert_rows(new_row_idx)
            
            # Copy format và giá trị từ dòng template
            _copy_row_format(ws, template_row_idx, new_row_idx)
            
            # Điền dữ liệu với số thứ tự idx
            _fill_row_data(ws, new_row_idx, base_var_name, idx, data, var_patterns)


def _fill_row_data(ws, row_idx: int, base_var_name: str, item_idx: int, data: Dict, var_patterns: List[str]):
    """
    Điền dữ liệu vào một dòng với số thứ tự cụ thể.
    """
    for col_idx, cell in enumerate(ws[row_idx], start=1):
        if cell.value and isinstance(cell.value, str):
            new_value = cell.value
            
            # Thay thế các biến trong dòng
            for var_name in var_patterns:
                # Tạo biến với số thứ tự
                var_with_idx = var_name + '_' + str(item_idx)
                value = data.get(var_with_idx, '')
                
                # Thay thế biến (có thể là không có số hoặc có số)
                pattern_no_num = '{{' + var_name + '}}'
                pattern_with_num = '{{' + var_name + '_' + str(item_idx) + '}}'
                
                if pattern_no_num in new_value:
                    new_value = new_value.replace(pattern_no_num, str(value))
                if pattern_with_num in new_value:
                    new_value = new_value.replace(pattern_with_num, str(value))
            
            # Chỉ cập nhật nếu không phải là merged cell (trừ top-left)
            try:
                if not _is_merged_cell(ws, cell):
                    cell.value = new_value
                    _set_wrap_text(cell)
            except Exception as cell_error:
                logger.debug(f"B? qua merged cell {cell.coordinate}: {cell_error}")


def _copy_row_format(ws, source_row_idx: int, dest_row_idx: int):
    """
    Copy format từ dòng nguồn sang dòng đích.
    """
    for col_idx, source_cell in enumerate(ws[source_row_idx], start=1):
        dest_cell = ws.cell(row=dest_row_idx, column=col_idx)
        
        # Copy value (sẽ được thay thế sau)
        if source_cell.value:
            dest_cell.value = source_cell.value
        
        # Copy alignment (giá»¯ wrap_text)
        try:
            if source_cell.alignment:
                dest_cell.alignment = Alignment(
                    horizontal=source_cell.alignment.horizontal,
                    vertical=source_cell.alignment.vertical,
                    wrap_text=True,  # Bật wrap text
                    shrink_to_fit=source_cell.alignment.shrink_to_fit if source_cell.alignment.shrink_to_fit else False,
                    text_rotation=source_cell.alignment.text_rotation if source_cell.alignment.text_rotation else 0,
                    indent=source_cell.alignment.indent if source_cell.alignment.indent else 0
                )
            else:
                dest_cell.alignment = Alignment(wrap_text=True)
        except Exception as e:
            logger.warning(f"Không thể copy alignment: {e}")
        
        # Copy number format
        dest_cell.number_format = source_cell.number_format


def _set_wrap_text(cell):
    """
    Bật wrap text cho cell nếu có dữ liệu.
    """
    if cell.value and str(cell.value).strip():
        try:
            if cell.alignment:
                cell.alignment = Alignment(
                    horizontal=cell.alignment.horizontal,
                    vertical=cell.alignment.vertical,
                    wrap_text=True,
                    shrink_to_fit=cell.alignment.shrink_to_fit if cell.alignment.shrink_to_fit else False,
                    text_rotation=cell.alignment.text_rotation if cell.alignment.text_rotation else 0,
                    indent=cell.alignment.indent if cell.alignment.indent else 0
                )
            else:
                cell.alignment = Alignment(wrap_text=True)
        except Exception as e:
            logger.warning(f"Không thể set wrap_text: {e}")


def _insert_image_to_cell(ws, image_url: str):
    """
    Tìm cell có chứa {{vd_image}} và chèn hình ảnh vào.
    Nếu image_url rỗng hoặc None, chỉ xóa biến {{vd_image}} khỏi cell.
    
    Args:
        ws: Worksheet object
        image_url: URL của hình ảnh (ví dụ: /api/images/filename.png) hoặc rỗng/None
    """
    # Tìm cell có chứa {{vd_image}}
    image_cell = None
    for row in ws.iter_rows():
        for cell in row:
            if _is_merged_cell(ws, cell):
                continue
            if cell.value and isinstance(cell.value, str):
                if '{{vd_image}}' in cell.value:
                    image_cell = cell
                    break
        if image_cell:
            break
    
    if not image_cell:
        logger.debug("Không tìm thấy cell có chứa {{vd_image}}")
        return
    
    # Xóa text {{vd_image}} trong cell (luôn luôn xóa, kể cả khi không có hình ảnh)
    cell_value = str(image_cell.value) if image_cell.value else ''
    cell_value = cell_value.replace('{{vd_image}}', '')
    image_cell.value = cell_value if cell_value.strip() else None
    
    # Nếu không có image_url hoặc rỗng, chỉ xóa biến và return
    if not image_url or not image_url.strip():
        logger.debug("Không có hình ảnh để chèn, đã xóa biến {{vd_image}}")
        return
    
    # Chuyển đổi URL thành đường dẫn file system
    # URL có dạng: /api/images/filename.png
    # Cần chuyển thành: D:\Data Analyst\Tools\kpi\qlcl\images\filename.png
    try:
        if image_url.startswith('/api/images/'):
            filename = image_url.replace('/api/images/', '')
            image_path = os.path.join(IMAGES_STORAGE_DIR, filename)
        else:
            # Nếu là đường dẫn tuyệt đối hoặc relative
            image_path = image_url
        
        # Kiểm tra file có tồn tại không
        if not os.path.exists(image_path):
            logger.warning(f"Hình ảnh không tồn tại: {image_path}")
            return

        # Chèn hình ảnh vào cell (image_cell đã được tìm ở trên)
        try:
            img = Image(image_path)
            
            # Lấy kích thước cell (width và height)
            col_letter = image_cell.column_letter
            row_idx = image_cell.row
            
            # Lấy column width (nếu không có, dùng default width = 8.43 characters)
            col_width = ws.column_dimensions[col_letter].width
            if col_width is None:
                col_width = 8.43  # Default column width
            
            # Lấy row height (nếu không có, dùng default height = 15 points)
            row_height = ws.row_dimensions[row_idx].height
            if row_height is None:
                row_height = 15.0  # Default row height
            
            # Chuyển đổi sang pixels - ĐIỀU CHỈNH HỆ SỐ CHUYỂN ĐỔI
            # Column width: 1 unit ≈ 7-8 pixels (tùy DPI)
            # Row height: 1 point â‰ˆ 1.33-1.5 pixels
            cell_width_px = col_width * 7.5  # Tăng hệ số từ 7 lên 7.5
            cell_height_px = row_height * 1.5  # Tăng hệ số từ 1.33 lên 1.5
            
            # Tính kích thước hình ảnh
            # Yêu cầu: chiều rộng ảnh = 120 pixels, chiều cao scale theo tỉ lệ
            img_width = img.width
            img_height = img.height
            aspect_ratio = img_width / img_height if img_height > 0 else 1
            
            # Đặt chiều rộng = 120 pixels (cố định)
            new_width = 120
            
            # Tính chiều cao theo tỉ lệ thuận (giữ aspect ratio)
            new_height = int(new_width / aspect_ratio)
            
            # Đảm bảo không vượt quá chiều cao cell
            # Nếu chiều cao vượt quá chiều cao cell, scale lại theo chiều cao cell
            if new_height > cell_height_px:
                new_height = int(cell_height_px)
                new_width = int(new_height * aspect_ratio)
            
            # HOẶC CÁCH 2: Fill toàn bộ cell (giữ tỉ lệ, fit vào cạnh lớn hơn)
            # Uncomment phần dưới nếu muốn ảnh lấp đầy cell hơn
            """
            width_ratio = cell_width_px / img_width
            height_ratio = cell_height_px / img_height
            
            # Chọn tỉ lệ LỚN HƠN để lấp đầy (thay vì min như trước)
            scale_ratio = max(width_ratio, height_ratio) * 0.95  # 0.95 để có chút padding
            
            new_width = int(img_width * scale_ratio)
            new_height = int(img_height * scale_ratio)
            """
            
            img.width = new_width
            img.height = new_height
            
            # Đặt vị trí hình ảnh tại cell
            image_cell_name = image_cell.coordinate
            img.anchor = image_cell_name
            
            # Thêm hình ảnh vào worksheet
            ws.add_image(img)
            
            logger.info(f"Đã chèn hình ảnh vào cell {image_cell_name}: {image_path} "
                       f"(kích thước: {new_width}x{new_height}px, cell: {cell_width_px:.1f}x{cell_height_px:.1f}px)")
        except Exception as img_error:
            logger.error(f"Lỗi khi chèn hình ảnh: {img_error}", exc_info=True)
            
    except Exception as e:
        logger.error(f"Lỗi khi xử lý hình ảnh: {e}", exc_info=True)


def _duplicate_section_rows(ws, base_var_name: str, max_items: int, data: Dict):
    """
    Tìm dòng có chứa biến {{base_var_name}} và duplicate nó thành nhiều dòng với số thứ tự.
    Template có biến không có số (ví dụ {{a_root_cause}}), code sẽ:
    1. Thay thế biến trong dòng template thành {{a_root_cause_1}}
    2. Duplicate dòng và tạo {{a_root_cause_2}}, {{a_root_cause_3}}, ...
    """
    template_row_idx = None
    
    # Tìm dòng template (dòng đầu tiên chứa biến {{base_var_name}} không có số)
    for row_idx, row in enumerate(ws.iter_rows(), start=1):
        for cell in row:
            if cell.value and isinstance(cell.value, str):
                # Tìm biến không có số (ví dụ {{a_root_cause}})
                if f'{{{{{base_var_name}}}}}' in cell.value:
                    template_row_idx = row_idx
                    break
        if template_row_idx:
            break
    
    if not template_row_idx:
        return  # Không tìm thấy template row
    
    # Xác định các biến cần thay thế dựa trên section
    var_patterns = []
    if base_var_name == 'a_root_cause':
        var_patterns = ['a_root_cause', 'a_hđkp_tuc_thoi', 'a_hđ_phong_ngua', 
                       'a_tg_theo_doi', 'a_trach_nhiem', 'a_tg_thuc_hien']
    elif base_var_name == 'b_root_cause':
        var_patterns = ['b_root_cause', 'b_hđkp_tuc_thoi', 'b_hđ_phong_ngua',
                       'b_tg_theo_doi', 'b_trach_nhiem', 'b_tg_thuc_hien']
    elif base_var_name == 'cong_viec':
        var_patterns = ['stt', 'cong_viec', 'trach_nhiem', 'ngay_bat_dau', 
                       'ngay_hoan_thanh', 'giam_sat', 'ket_qua', 'ket_luan']
    
    # Thay thế biến trong dòng template thành số 1
    for col_idx, template_cell in enumerate(ws[template_row_idx], start=1):
        if template_cell.value and isinstance(template_cell.value, str):
            new_value = template_cell.value
            for var_name in var_patterns:
                # Thay thế {{var_name}} thành {{var_name_1}}
                old_pattern = '{{' + var_name + '}}'
                new_pattern = '{{' + var_name + '_1' + '}}'
                new_value = new_value.replace(old_pattern, new_pattern)
            template_cell.value = new_value
    
    # Nếu chỉ có 1 item, không cần duplicate
    if max_items <= 1:
        return
    
    # Duplicate rows: chèn các dòng mới sau dòng template
    for idx in range(2, max_items + 1):
        # Insert row sau dòng template + (idx - 2)
        new_row_idx = template_row_idx + (idx - 1)
        ws.insert_rows(new_row_idx)
        
        # Copy format và công thức từ template row
        for col_idx, template_cell in enumerate(ws[template_row_idx], start=1):
            new_cell = ws.cell(row=new_row_idx, column=col_idx)
            
            # Copy value và thay thế biến
            if template_cell.value:
                if isinstance(template_cell.value, str):
                    # Thay thế tất cả các biến từ {{var_name_1}} thành {{var_name_idx}}
                    new_value = template_cell.value
                    for var_name in var_patterns:
                        # Tránh dùng f-string với quá nhiều dấu ngoặc nhọn
                        # Pattern: {{{{var_name}_1}}}} â†’ {{{{var_name}_{idx}}}}}}
                        old_pattern = '{{' + var_name + '_1' + '}}'
                        new_pattern = '{{' + var_name + '_' + str(idx) + '}}'
                        new_value = new_value.replace(old_pattern, new_pattern)
                    new_cell.value = new_value
                else:
                    new_cell.value = template_cell.value
            
            # Copy style - chỉ copy các thuộc tính cơ bản để tránh lỗi StyleProxy
            try:
                # Copy alignment (quan trọng nhất cho format)
                if template_cell.alignment and template_cell.alignment.horizontal is not None:
                    new_cell.alignment = Alignment(
                        horizontal=template_cell.alignment.horizontal,
                        vertical=template_cell.alignment.vertical,
                        wrap_text=template_cell.alignment.wrap_text if template_cell.alignment.wrap_text else False,
                        shrink_to_fit=template_cell.alignment.shrink_to_fit if template_cell.alignment.shrink_to_fit else False
                    )
                # Copy number format (string, an toàn)
                if template_cell.number_format:
                    new_cell.number_format = template_cell.number_format
            except Exception as style_error:
                # Nếu copy style lỗi, chỉ copy number_format
                logger.warning(f"Không thể copy style: {style_error}")
                try:
                    new_cell.number_format = template_cell.number_format
                except:
                    pass


EXCEL_MAX_ROW_HEIGHT = 409.0  # giới hạn cứng của Excel
XL_SHEET_VISIBLE = -1
XL_CALCULATION_MANUAL = -4135


def _grow_row_heights_to_fit_text(sheet):
    """
    Giãn chiều cao các dòng cho vừa nội dung đã wrap.

    Excel AutoFit bỏ qua ô đã merge, mà biểu mẫu HĐKP merge gần hết vùng nhập
    liệu (C:J, C:E, F:G), nên nội dung dài bị cắt ngang. Ở đây đo chiều cao cần
    thiết bằng một ô nháp đặt ngoài vùng in rồi áp lại cho dòng.

    Chỉ tăng, không bao giờ giảm, để giữ nguyên bố cục gốc của biểu mẫu.
    """
    used = sheet.UsedRange
    first_row, last_row = used.Row, used.Row + used.Rows.Count - 1
    first_col, last_col = used.Column, used.Column + used.Columns.Count - 1

    # Ghim vùng in vào nội dung thật để ô nháp không lọt vào PDF
    if not sheet.PageSetup.PrintArea:
        sheet.PageSetup.PrintArea = used.Address

    # Đọc cả vùng bằng một lệnh COM. UsedRange có thể phình tới hàng nghìn dòng
    # dù chỉ vài chục ô có chữ, duyệt từng ô qua COM sẽ mất hàng phút.
    values = used.Value2
    if not isinstance(values, tuple):
        values = ((values,),)

    heights = {}
    pending = defaultdict(list)  # độ rộng cần đo -> các ô dùng chung độ rộng đó
    for row_offset, row_values in enumerate(values):
        if not any(v is not None and str(v).strip() for v in row_values):
            continue
        row_idx = first_row + row_offset
        for col_offset, value in enumerate(row_values):
            if value is None or not str(value).strip():
                continue
            cell = sheet.Cells(row_idx, first_col + col_offset)
            if not cell.WrapText:
                continue
            area = cell.MergeArea
            # Chỉ đo từ ô gốc của vùng merge; bỏ qua merge dọc vì nội dung
            # của nó thuộc về cả khối chứ không riêng dòng nào
            if cell.Row != area.Row or cell.Column != area.Column:
                continue
            if area.Rows.Count > 1:
                continue
            text = cell.Text
            if text is None or not str(text).strip():
                continue
            text = str(text)
            width = sum(
                sheet.Columns(x).ColumnWidth
                for x in range(area.Column, area.Column + area.Columns.Count)
            )
            # Đơn vị ColumnWidth xấp xỉ số ký tự vừa một dòng; chuỗi ngắn hơn
            # nhiều thì chắc chắn không xuống dòng nên khỏi tốn một lượt đo
            if "\n" not in text and len(text) <= width * 0.75:
                continue
            if row_idx not in heights:
                heights[row_idx] = sheet.Rows(row_idx).RowHeight
            font = cell.Font
            pending[(round(width, 2), font.Name, font.Size, bool(font.Bold))].append(
                (row_idx, text))

    if not pending:
        return

    probe_row, probe_col = last_row + 4, last_col + 2
    probe_rows = max(len(entries) for entries in pending.values())
    probe_area = sheet.Range(
        sheet.Cells(probe_row, probe_col),
        sheet.Cells(probe_row + probe_rows - 1, probe_col),
    )
    saved_width = sheet.Columns(probe_col).ColumnWidth
    app = sheet.Application
    saved_calc = None
    needed = dict(heights)
    try:
        # Mỗi lần đổi ColumnWidth Excel vẽ lại cả sheet; tắt đi nhanh hơn gấp đôi
        for prop, val in (("ScreenUpdating", False), ("EnableEvents", False)):
            try:
                setattr(app, prop, val)
            except Exception:
                pass
        try:
            saved_calc = app.Calculation
            app.Calculation = XL_CALCULATION_MANUAL
        except Exception:
            saved_calc = None

        # Đo cả nhóm trong một lượt: xếp các chuỗi cùng độ rộng và cùng font
        # xuống các dòng nháp liên tiếp rồi AutoFit một lần cho cả khối
        for (width, font_name, font_size, font_bold), entries in pending.items():
            sheet.Columns(probe_col).ColumnWidth = width
            block = sheet.Range(
                sheet.Cells(probe_row, probe_col),
                sheet.Cells(probe_row + len(entries) - 1, probe_col),
            )
            block.WrapText = True
            block.Font.Name = font_name
            block.Font.Size = font_size
            block.Font.Bold = font_bold
            block.Value = tuple((text,) for _, text in entries)
            block.Rows.AutoFit()
            for offset, (row_idx, _) in enumerate(entries):
                measured = sheet.Rows(probe_row + offset).RowHeight
                if measured > needed[row_idx]:
                    needed[row_idx] = measured
            block.Clear()

        for row_idx, height in needed.items():
            if height > heights[row_idx]:
                sheet.Rows(row_idx).RowHeight = min(height, EXCEL_MAX_ROW_HEIGHT)
    finally:
        probe_area.Clear()
        sheet.Columns(probe_col).ColumnWidth = saved_width
        # Trả Calculation về trước khi export, nếu không template có công thức
        # sẽ in ra giá trị cũ
        if saved_calc is not None:
            try:
                app.Calculation = saved_calc
            except Exception:
                pass
        for prop in ("ScreenUpdating", "EnableEvents"):
            try:
                setattr(app, prop, True)
            except Exception:
                pass


class RevalidatedStaticFiles(StaticFiles):
    """Phục vụ file nhưng bắt trình duyệt và CDN hỏi lại server mỗi lần.

    File PDF của một HĐKP được dựng lại mỗi khi nội dung thay đổi mà tên file
    giữ nguyên. Nếu để cache theo mặc định thì người xem nhận bản cũ hàng giờ
    sau khi HĐKP đã sửa. Dùng no-cache chứ không phải no-store nên vẫn còn
    ETag: file không đổi thì server trả 304, không tốn băng thông.
    """

    def file_response(self, *args, **kwargs):
        response = super().file_response(*args, **kwargs)
        response.headers["Cache-Control"] = "no-cache, must-revalidate"
        return response


def excel_to_pdf(excel_path: str, pdf_path: str):
    """
    Chuyển đổi Excel sang PDF sử dụng win32com (Windows only).
    Thiết lập page setup để fit to page width và loại bỏ margins thừa.
    """
    if not WIN32_AVAILABLE:
        raise HTTPException(status_code=500, detail="Không thể xuất PDF: win32com không khả dụng. Chỉ hỗ trợ trên Windows.")
    
    # Event loop thread của FastAPI chưa khởi tạo COM apartment
    pythoncom.CoInitialize()
    excel = None
    workbook = None
    try:
        # DispatchEx tạo process Excel riêng thay vì bám vào instance đang mở
        # (instance cũ có thể đang treo dialog và từ chối mọi lệnh automation)
        excel = win32com.client.DispatchEx("Excel.Application")
        for prop in ("Visible", "DisplayAlerts"):
            try:
                setattr(excel, prop, False)
            except Exception:
                pass

        # Má»Ÿ file Excel
        workbook = excel.Workbooks.Open(os.path.abspath(excel_path))

        # Thiết lập page setup cho tất cả các sheets
        for sheet in workbook.Worksheets:
            # Thiết lập margins nhỏ để tránh lề thừa
            sheet.PageSetup.LeftMargin = excel.InchesToPoints(0.25)  # 0.25 inch
            sheet.PageSetup.RightMargin = excel.InchesToPoints(0.25)
            sheet.PageSetup.TopMargin = excel.InchesToPoints(0.25)
            sheet.PageSetup.BottomMargin = excel.InchesToPoints(0.25)
            sheet.PageSetup.HeaderMargin = excel.InchesToPoints(0.1)
            sheet.PageSetup.FooterMargin = excel.InchesToPoints(0.1)
            
            # Fit to page width (1 page wide) để tránh tạo trang thừa do lề
            sheet.PageSetup.FitToPagesWide = 1
            sheet.PageSetup.FitToPagesTall = False  # Không giới hạn số trang theo chiều cao
            
            # Đảm bảo sử dụng fit to page
            sheet.PageSetup.Zoom = False

            # Sheet ẩn không vào PDF, biểu mẫu kèm theo chúng lại rất rộng
            if sheet.Visible == XL_SHEET_VISIBLE:
                try:
                    _grow_row_heights_to_fit_text(sheet)
                except Exception:
                    # Bố cục chưa giãn vẫn hơn là không có PDF
                    logger.warning("Không thể giãn chiều cao dòng cho sheet %s", sheet.Name, exc_info=True)

        # Xuất sang PDF
        workbook.ExportAsFixedFormat(0, os.path.abspath(pdf_path))  # 0 = xlTypePDF

        return pdf_path
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Lỗi khi chuyển Excel sang PDF: {str(e)}")
    finally:
        # Không cleanup thì mỗi lần lỗi để lại một EXCEL.EXE treo,
        # lần gọi sau bám vào nó và hỏng theo kiểu khác
        if workbook is not None:
            try:
                workbook.Close(False)
            except Exception:
                pass
        if excel is not None:
            try:
                excel.Quit()
            except Exception:
                pass
        pythoncom.CoUninitialize()


def create_hdkp_pdf(error_id: int, hdkp_data: Dict) -> str:
    """
    Tạo file PDF HĐKP từ template Excel và dữ liệu.
    Returns: đường dẫn file PDF
    """
    try:
        # Format tên file
        filename = f"SAISOT_{hdkp_data.get('ma_nv', 'UNKNOWN')}_{hdkp_data.get('ngay_ghi_nhan', '').replace('-', '')}.pdf"
        pdf_path = os.path.join(PDF_STORAGE_DIR, filename)
        logger.info(f"Tạo PDF: {pdf_path}")

        logo_path = os.path.join(TEMPLATES_DIR, "Logo.png") if TEMPLATES_DIR else None
        render_hdkp_pdf(hdkp_data, pdf_path,
                        images_dir=IMAGES_STORAGE_DIR, logo_path=logo_path)
        logger.info(f"Đã tạo PDF thành công: {pdf_path}")

        # Trả về URL để truy cập file
        return f"/api/pdf/{filename}"

    except Exception as e:
        logger.error(f"Lỗi trong create_hdkp_pdf: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Lỗi khi tạo file PDF: {str(e)}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    _detect_bo_phan_jsonb()
    startup_auto_sync()
    yield
    _db_pool.closeall()
    _prod_factory_pool.closeall()


app = FastAPI(title="QLCL KPI", lifespan=lifespan)
# app.add_middleware(SessionMiddleware, secret_key="qlcl-kpi-secret-please-change")
templates = Jinja2Templates(directory=TEMPLATES_DIR)
gemba_cp_templates = Jinja2Templates(directory=str(GEMBA_CP_TEMPLATES_DIR))
# Serve logo and other assets from templates folder under /templates
app.mount("/templates", StaticFiles(directory=TEMPLATES_DIR), name="templates")
# Serve PDF files
app.mount("/api/pdf", RevalidatedStaticFiles(directory=PDF_STORAGE_DIR), name="pdf")
# Serve uploaded images
app.mount("/api/images", StaticFiles(directory=IMAGES_STORAGE_DIR), name="images")
app.mount("/static", StaticFiles(directory=str(GEMBA_CP_STATIC_DIR)), name="gemba-static")
# CSS/JS tách khỏi template (VD: assets/qc_input/*.js)
ASSETS_DIR = PathLib(__file__).resolve().parent / "assets"
app.mount("/assets", StaticFiles(directory=str(ASSETS_DIR)), name="assets")


def asset_url(path: str) -> str:
    """URL tới file trong assets/ kèm ?v=<mtime> để trình duyệt (tablet QC) không dùng bản cache cũ."""
    try:
        version = int((ASSETS_DIR / path).stat().st_mtime)
    except OSError:
        version = 0
    return f"/assets/{path}?v={version}"


templates.env.globals["asset_url"] = asset_url

bootstrap_qlcl_schema()
GembaCPBase.metadata.create_all(bind=gemba_cp_engine)
app.include_router(gemba_dashboard_router.router, dependencies=[Depends(require_authenticated_api_user)])
app.include_router(gemba_admin_router.router, dependencies=[Depends(require_authenticated_api_user)])


FINAL_CAP_PUBLIC_PATHS = {"/", "/login", "/logout", "/healthz", "/favicon.ico"}
FINAL_CAP_ALLOWED_PREFIXES = (
    "/final-noi-bo",
    "/final-internal/",
    "/api/final-internal",
    "/hdkp-form/",
    "/api/hdkp/",
    "/api/upload-image",
    "/api/pdf/",
    "/api/images/",
    "/templates/",
    "/static/",
)


@app.middleware("http")
async def restrict_final_cap_editor_routes(request: Request, call_next):
    """Keep FINAL_CAP accounts inside the Final internal workflow."""
    path = request.url.path
    if path in FINAL_CAP_PUBLIC_PATHS or path.startswith(("/templates/", "/static/")):
        return await call_next(request)
    if not request.cookies.get("ma_nv"):
        return await call_next(request)
    user = get_authenticated_user(request)
    if get_qc_role(user) != FINAL_CAP_ROLE:
        return await call_next(request)
    if path.startswith(FINAL_CAP_ALLOWED_PREFIXES):
        return await call_next(request)
    if path.startswith("/api/"):
        return JSONResponse(status_code=403, content={"detail": "Tài khoản chỉ được truy cập module Final nội bộ"})
    return RedirectResponse(url="/final-noi-bo", status_code=303)


_final_sync_lock = threading.Lock()
_final_sync_state: Dict[str, Any] = {
    "running": False,
    "started_at": None,
    "finished_at": None,
    "result": None,
    "error": None,
}


def final_qa_sync_is_configured() -> bool:
    return bool(FINAL_QA_API_BASE_URL and FINAL_QA_API_USERNAME and FINAL_QA_API_PASSWORD)


def run_final_qa_sync(triggered_by: str = "system", max_pages: Optional[int] = None) -> Dict[str, Any]:
    if not final_qa_sync_is_configured():
        raise RuntimeError("Chưa cấu hình FINAL_QA_API_USERNAME và FINAL_QA_API_PASSWORD")
    if not _final_sync_lock.acquire(blocking=False):
        raise RuntimeError("Đồng bộ Final đang chạy")
    _final_sync_state.update(
        running=True,
        started_at=datetime.now().isoformat(),
        finished_at=None,
        result=None,
        error=None,
    )
    try:
        effective_max_pages = max_pages
        if effective_max_pages is None:
            effective_max_pages = FINAL_QA_SYNC_MAX_PAGES or None
        with FinalApiClient(
            FINAL_QA_API_BASE_URL,
            FINAL_QA_API_USERNAME,
            FINAL_QA_API_PASSWORD,
        ) as client:
            result = sync_final_internal(
                get_db_connection,
                client,
                page_size=FINAL_QA_SYNC_PAGE_SIZE,
                max_pages=effective_max_pages,
                triggered_by=triggered_by,
            )
        _final_sync_state["result"] = result
        return result
    except Exception as exc:
        _final_sync_state["error"] = str(exc)
        logger.exception("Internal Final sync failed")
        raise
    finally:
        _final_sync_state["running"] = False
        _final_sync_state["finished_at"] = datetime.now().isoformat()
        _final_sync_lock.release()


def _final_qa_auto_sync_loop() -> None:
    while True:
        try:
            run_final_qa_sync(triggered_by="auto")
        except RuntimeError as exc:
            logger.warning("Internal Final auto-sync skipped: %s", exc)
        except Exception:
            pass
        time.sleep(FINAL_QA_AUTO_SYNC_INTERVAL_MINUTES * 60)


def start_final_qa_auto_sync_if_enabled() -> None:
    if not FINAL_QA_AUTO_SYNC_ENABLED:
        return
    if not final_qa_sync_is_configured():
        logger.warning("FINAL_QA_AUTO_SYNC_ENABLED but API credentials are missing")
        return
    threading.Thread(target=_final_qa_auto_sync_loop, daemon=True, name="final-qa-sync").start()


_bulletin_sync_lock = threading.Lock()
_bulletin_sync_state: Dict[str, Any] = {
    "running": False,
    "started_at": None,
    "finished_at": None,
    "result": None,
    "error": None,
}


def bulletin_sync_is_configured() -> bool:
    credentials_path = (
        os.getenv("BULLETIN_GOOGLE_SERVICE_ACCOUNT_FILE", "").strip()
        or os.getenv("GEMBA_CP_GOOGLE_SERVICE_ACCOUNT_FILE", "").strip()
        or str(GEMBA_CP_TEMPLATES_DIR / "credentials_m29.json")
    )
    return PathLib(credentials_path).exists()


def run_bulletin_sync(triggered_by: str = "system", trigger_type: str = "manual") -> Dict[str, Any]:
    if not bulletin_sync_is_configured():
        raise RuntimeError("Chưa cấu hình BULLETIN_GOOGLE_SERVICE_ACCOUNT_FILE")
    if not _bulletin_sync_lock.acquire(blocking=False):
        raise RuntimeError("Đồng bộ bản tin đang chạy")
    _bulletin_sync_state.update(
        running=True,
        started_at=datetime.now().isoformat(),
        finished_at=None,
        result=None,
        error=None,
    )
    try:
        counts = sync_bulletin_sources(
            get_db_connection,
            triggered_by=triggered_by,
            trigger_type=trigger_type,
        )
        bulletin = ensure_weekly_draft(
            get_db_connection,
            created_by=triggered_by,
        )
        result = {"source_counts": counts, "bulletin_id": bulletin["id"]}
        _bulletin_sync_state["result"] = result
        return result
    except Exception as exc:
        _bulletin_sync_state["error"] = str(exc)
        logger.exception("Quality bulletin sync failed")
        raise
    finally:
        _bulletin_sync_state["running"] = False
        _bulletin_sync_state["finished_at"] = datetime.now().isoformat()
        _bulletin_sync_lock.release()


def _bulletin_auto_sync_loop() -> None:
    while True:
        try:
            run_bulletin_sync(triggered_by="system", trigger_type="auto")
        except RuntimeError as exc:
            logger.warning("Bulletin auto-sync skipped: %s", exc)
        except Exception:
            pass
        time.sleep(BULLETIN_AUTO_SYNC_INTERVAL_MINUTES * 60)


def start_bulletin_auto_sync_if_enabled() -> None:
    if not BULLETIN_AUTO_SYNC_ENABLED:
        return
    if not bulletin_sync_is_configured():
        logger.warning("BULLETIN_AUTO_SYNC_ENABLED but Google service-account file is missing")
        return
    threading.Thread(target=_bulletin_auto_sync_loop, daemon=True, name="quality-bulletin-sync").start()


def startup_auto_sync():
    from xndt_sync import start_auto_sync
    start_auto_sync(get_db_connection, DATABASE_URL)
    start_qtcn_auto_sync_if_enabled()
    start_xnv2_auto_sync_if_enabled()
    start_flat_line_auto_sync_if_enabled()
    start_final_qa_auto_sync_if_enabled()
    start_bulletin_auto_sync_if_enabled()


@app.get("/")
def home(request: Request):
    user_data = get_authenticated_user(request)
    if not user_data:
        response = RedirectResponse(url="/login", status_code=303)
        response.delete_cookie("ma_nv")
        return response

    user_qc_role = get_qc_role(user_data)
    if user_qc_role == "QC":
        return RedirectResponse(url=QC_INPUT_HOME, status_code=303)
    final_only = user_qc_role == FINAL_CAP_ROLE
    is_qc_role = user_qc_role == "QC"
    final_factory_scope = get_final_factory_scope(user_data)
    final_cap_pending = 0
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            pending_sql = """
                SELECT COUNT(*)
                FROM public.qa_final_inspection fi
                LEFT JOIN public.qa_final_hdkp fh ON fh.inspection_id = fi.id
                WHERE fi.cap_required = TRUE
                  AND fh.pdf_url IS NULL
            """
            pending_params: List[Any] = []
            if final_factory_scope:
                pending_sql += " AND fi.factory = %s"
                pending_params.append(final_factory_scope)
            cur.execute(pending_sql, tuple(pending_params))
            final_cap_pending = int(cur.fetchone()[0] or 0)
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "user": user_data,
            "final_cap_pending": final_cap_pending,
            "final_only": final_only,
            "is_qc_role": is_qc_role,
        },
    )


def can_manage_final_sync(user: Optional[Dict]) -> bool:
    if not user:
        return False
    return get_qc_role(user) == "QA_ADMIN" or (user.get("department") or "").upper() == "QAQT"


@app.get("/gemba-control-plan")
def gemba_control_plan_dashboard(request: Request):
    if not get_authenticated_user(request):
        return RedirectResponse(url=f"/login?next={quote(str(request.url.path), safe='/')}", status_code=303)
    dashboard_js_version = build_static_asset_version(GEMBA_CP_STATIC_DIR / "dashboard.js")
    return gemba_cp_templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "app_name": gemba_cp_settings.app_name,
            "sheet_name": gemba_cp_settings.google_sheets_worksheet,
            "dashboard_js_version": dashboard_js_version,
        },
    )


def prepare_hdkp_data_for_pdf(
    error_id: int,
    error_row: Dict,
    table_names: Tuple[str, str, str] = ("cap_mota", "cap_kehoach", "cap_chitiet"),
    key_column: str = "error_id",
) -> Dict:
    """
    Chuẩn bị dữ liệu từ 3 tables để tạo PDF.
    Tập hợp tất cả dữ liệu và format cho mapping vào Excel template.
    """
    with get_db_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            # Lấy Section I: Mô tả vấn đề
            mota_table, kehoach_table, chitiet_table = table_names
            cur.execute(f"SELECT * FROM public.{mota_table} WHERE {key_column} = %s", (error_id,))
            mota = cur.fetchone()
            
            # Lấy Section II: Kế hoạch (section A và B)
            cur.execute(
                f"SELECT * FROM public.{kehoach_table} WHERE {key_column} = %s ORDER BY section, thu_tu",
                (error_id,)
            )
            kehoach_rows = cur.fetchall()
            
            # Lấy Section III: Chi tiết
            cur.execute(
                f"SELECT * FROM public.{chitiet_table} WHERE {key_column} = %s ORDER BY thu_tu",
                (error_id,)
            )
            chitiet_rows = cur.fetchall()
            
            # Lấy họ và tên của người điền input error
            ho_ten = ''
            ma_nv_error = error_row.get('ma_nv')
            if ma_nv_error:
                cur.execute("SELECT ho_ten FROM public.quality_employees WHERE ma_nv = %s", (ma_nv_error,))
                ho_ten_row = cur.fetchone()
                if ho_ten_row:
                    ho_ten = ho_ten_row.get('ho_ten', '')
    
    # Format created_at từ cap_mota thành dd/mm/yyyy
    created_at_formatted = ''
    if mota and mota.get('created_at'):
        try:
            # created_at là datetime object từ psycopg2
            created_at = mota.get('created_at')
            if isinstance(created_at, str):
                # Parse string thành datetime (nếu là string)
                created_at = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
            
            # Format thành dd/mm/yyyy
            if isinstance(created_at, datetime):
                created_at_formatted = created_at.strftime('%d/%m/%Y')
            elif isinstance(created_at, date):
                created_at_formatted = created_at.strftime('%d/%m/%Y')
        except Exception as e:
            logger.warning(f"Không thể format created_at: {e}")
            created_at_formatted = ''
    
    # Tạo data dict với các biến {{...}}
    data = {
        'ma_nv': error_row.get('ma_nv', ''),
        'ngay_ghi_nhan': str(error_row.get('ngay_ghi_nhan', '')),
        'created_at': created_at_formatted,
        'ho_ten': ho_ten,
    }
    
    # Section I: Mô tả vấn đề
    if mota:
        data.update({
            'vd_what': mota.get('vd_what', ''),
            'vd_when': mota.get('vd_when', ''),
            'vd_who': mota.get('vd_who', ''),
            'vd_where': mota.get('vd_where', ''),
            'vd_how': mota.get('vd_how', ''),
            'vd_before': mota.get('vd_before', ''),
            'vd_importance': mota.get('vd_importance', ''),
            'vd_image': mota.get('vd_image', ''),
        })
    
    # Section II: Kế hoạch - Format theo section A và B với số thứ tự
    section_a_items = [r for r in kehoach_rows if r.get('section') == 'A']
    section_b_items = [r for r in kehoach_rows if r.get('section') == 'B']
    
    # Format section A vá»›i sá»‘ thá»© tá»± (1, 2, 3, ...)
    for idx, item in enumerate(section_a_items, start=1):
        data.update({
            f'a_root_cause_{idx}': item.get('root_cause', ''),
            f'a_hđkp_tuc_thoi_{idx}': item.get('hdkp_tuc_thoi', ''),
            f'a_hđ_phong_ngua_{idx}': item.get('hd_phong_ngua', ''),
            f'a_tg_theo_doi_{idx}': item.get('tg_theo_doi', ''),
            f'a_trach_nhiem_{idx}': item.get('trach_nhiem', ''),
            f'a_tg_thuc_hien_{idx}': item.get('tg_thuc_hien', ''),
        })
    
    # Format section B vá»›i sá»‘ thá»© tá»± (1, 2, 3, ...)
    for idx, item in enumerate(section_b_items, start=1):
        data.update({
            f'b_root_cause_{idx}': item.get('root_cause', ''),
            f'b_hđkp_tuc_thoi_{idx}': item.get('hdkp_tuc_thoi', ''),
            f'b_hđ_phong_ngua_{idx}': item.get('hd_phong_ngua', ''),
            f'b_tg_theo_doi_{idx}': item.get('tg_theo_doi', ''),
            f'b_trach_nhiem_{idx}': item.get('trach_nhiem', ''),
            f'b_tg_thuc_hien_{idx}': item.get('tg_thuc_hien', ''),
        })
    
    # Section III: Chi tiết với số thứ tự (1, 2, 3, ...) và thêm {{stt}}
    for idx, item in enumerate(chitiet_rows, start=1):
        ket_qua = (item.get('ket_qua') or '').strip()
        # Tách ket_qua thành 2 cột: Đạt (trái) và Không đạt (phải)
        ket_qua_dat = ''  # Cột trái (Đạt)
        ket_qua_khong_dat = ''  # Cột phải (Không đạt)
        if ket_qua == 'Đạt':
            ket_qua_dat = 'x'
        elif ket_qua == 'Không đạt':
            ket_qua_khong_dat = 'x'
        
        data.update({
            f'stt_{idx}': str(idx),  # Số thứ tự tăng dần
            f'cong_viec_{idx}': item.get('cong_viec', ''),
            f'trach_nhiem_{idx}': item.get('trach_nhiem', ''),
            f'ngay_bat_dau_{idx}': str(item.get('ngay_bat_dau', '')) if item.get('ngay_bat_dau') else '',
            f'ngay_hoan_thanh_{idx}': str(item.get('ngay_hoan_thanh', '')) if item.get('ngay_hoan_thanh') else '',
            f'giam_sat_{idx}': item.get('giam_sat', ''),
            f'ket_qua_dat_{idx}': ket_qua_dat,  # Cột trái: "x" nếu Đạt, trống nếu không
            f'ket_qua_khong_dat_{idx}': ket_qua_khong_dat,  # Cột phải: "x" nếu Không đạt, trống nếu không
            f'ket_luan_{idx}': item.get('ket_luan', ''),
        })
    
    return data


# ==================== QC MODULE ====================

DON_VI_OPTIONS = ["XN1-V1", "XN2", "XN3", "XNDT", "XNV2"]


# Đồng bộ kế hoạch sản xuất (QTCN, XNV2, chuyền bệt Google Sheets, chuyền treo) + vòng lặp tự đồng bộ -> prod_plan_sync.py
# Re-export: route modules gọi core.<tên>, test patch main.<tên>.
import app_core
app_core.bind(sys.modules[__name__])
from prod_plan_sync import (  # noqa: E402
    FLAT_LINE_SOURCE_SYSTEM,
    HL_SOURCE_SYSTEM,
    HL_SYNC_PLAN_PREFIX,
    QTCN_LOAI_HANG_MAP,
    QTCN_SOURCE_SYSTEM,
    QTCN_SYNC_PLAN_PREFIX,
    build_hl_sync_plan_code,
    build_prod_plan_display_name,
    build_qtcn_sync_plan_code,
    compute_po_info_total,
    ensure_prod_plan_is_active,
    get_flat_line_credentials_path,
    get_xnv2_connection,
    normalize_flat_line_don_vi,
    normalize_po_info,
    normalize_qtcn_to_sx_list,
    run_flat_line_auto_sync_loop,
    run_qtcn_auto_sync_loop,
    run_xnv2_auto_sync_loop,
    start_flat_line_auto_sync_if_enabled,
    start_qtcn_auto_sync_if_enabled,
    start_xnv2_auto_sync_if_enabled,
    sync_all_flat_line_prod_plans,
    sync_flat_line_prod_plan,
    sync_hanging_line_prod_plan,
    sync_qtcn_prod_plan,
)


# API key cho push từ hanging line app — set trong .env của QLCL server
_PUSH_API_KEY = os.getenv("QLCL_API_KEY", "")


@app.get("/healthz")
def healthz():
    return {"status": "ok"}


from flat_output import register as register_flat_output
register_flat_output(app, get_db_connection, _PUSH_API_KEY)

from quality_index_routes import register as register_quality_index
register_quality_index(
    app,
    get_authenticated_user=get_authenticated_user,
    redirect_to_login=redirect_to_login_for_current_path,
    templates=templates,
    credentials_path_fn=get_flat_line_credentials_path,
)

# Các nhóm route đã tách khỏi main.py (thứ tự include = thứ tự cũ trong file); app_core.bind() đã gọi ở trên
import final_internal_routes, kpi_routes, bulletin_routes, auth_routes, qc_hdkp_routes, qc_pages_routes, qc_dashboard_routes, qc_employees_routes, qc_cap_routes, prod_plan_routes, catalog_routes, tv3_routes, qc_input_routes
for _routes_module in (final_internal_routes, kpi_routes, bulletin_routes, auth_routes, qc_hdkp_routes, qc_pages_routes, qc_dashboard_routes, qc_employees_routes, qc_cap_routes, prod_plan_routes, catalog_routes, tv3_routes, qc_input_routes,):
    app.include_router(_routes_module.router)
api_summary_quarterly = kpi_routes.api_summary_quarterly  # giữ main.api_summary_quarterly cho code/test cũ

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8008, reload=True)
