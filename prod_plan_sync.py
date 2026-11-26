"""Đồng bộ kế hoạch sản xuất (QTCN, XNV2, chuyền bệt Google Sheets, chuyền treo) + vòng lặp tự đồng bộ

Tách từ main.py. Hàm/biến dùng chung (DB, đăng nhập, phân quyền, template, cấu hình...) vẫn ở main.py
và được gọi qua `core.<tên>` lúc chạy, nên test patch `main.<tên>` vẫn có hiệu lực.
"""
import json
import psycopg2
import psycopg2.extras
import psycopg2.pool
import re
import threading
import time
from datetime import date, datetime
from fastapi import APIRouter, HTTPException
from flat_line_sync import fetch_sheet_values as fetch_flat_line_sheet_values, parse_flat_line_plans
from pathlib import Path as PathLib
from typing import Any, Dict, List, Optional

from app_core import core


QTCN_LOAI_HANG_MAP = {
    "AOVES": "Áo vest",
    "BOMBER": "Áo vest",
    "GHILE": "Áo vest",
    "QUANVES": "Quần tây",
}
QTCN_SYNC_PLAN_PREFIX = "SYNC-QTCN-XNV2-"
QTCN_SOURCE_SYSTEM = "prod_factory"
_qtcn_auto_sync_started = False
_qtcn_auto_sync_lock = threading.Lock()

_xnv2_auto_sync_started = False
_xnv2_auto_sync_lock = threading.Lock()


def get_xnv2_connection():
    """Kết nối SQL Server của XNV2 — dùng riêng biệt với HANGING_LINE_SQL_SERVER."""
    if not core.PYODBC_AVAILABLE:
        raise RuntimeError("pyodbc chưa được cài đặt. Chạy: pip install pyodbc")
    if not core.XNV2_SQL_SERVER:
        raise RuntimeError("XNV2_SQL_SERVER chưa được cấu hình trong .env")
    conn_str = (
        f"DRIVER={{{core.XNV2_SQL_DRIVER}}};"
        f"SERVER={core.XNV2_SQL_SERVER};"
        f"DATABASE={core.XNV2_APP_DB};"
        "Trusted_Connection=yes;"
        "TrustServerCertificate=yes;"
    )
    return core.pyodbc.connect(conn_str, autocommit=True)


def run_xnv2_auto_sync_loop() -> None:
    core.logger.info("XNV2 auto-sync (PULL) started, interval=%s minutes", core.HL_XNV2_AUTO_SYNC_INTERVAL_MINUTES)
    while True:
        time.sleep(core.HL_XNV2_AUTO_SYNC_INTERVAL_MINUTES * 60)
        try:
            conn = get_xnv2_connection()
            result = sync_hanging_line_prod_plan(conn_override=conn, don_vi_override=core.XNV2_DON_VI)
            core.logger.info(
                "XNV2 auto-sync ok — synced=%s inserted=%s updated=%s skipped=%s",
                result.get("synced", 0),
                result.get("inserted", 0),
                result.get("updated", 0),
                result.get("skipped", 0),
            )
        except Exception:
            core.logger.exception("XNV2 auto-sync failed")


def start_xnv2_auto_sync_if_enabled() -> None:
    global _xnv2_auto_sync_started
    if not core.HL_XNV2_AUTO_SYNC_ENABLED:
        return
    with _xnv2_auto_sync_lock:
        if _xnv2_auto_sync_started:
            return
        t = threading.Thread(target=run_xnv2_auto_sync_loop, name="xnv2-auto-sync", daemon=True)
        t.start()
        _xnv2_auto_sync_started = True
        core.logger.info("XNV2 auto-sync thread started")


def build_prod_plan_display_name(row: Dict[str, Any]) -> str:
    ma_hang = str(row.get("ma_hang") or "").strip()
    san_luong = row.get("san_luong")
    ngay_rc = row.get("ngay_rc")

    if not ma_hang:
        return str(row.get("ke_hoach") or "--")

    parts = [ma_hang]
    if san_luong is not None and str(san_luong).strip() != "":
        parts.append(str(san_luong).strip())
    if ngay_rc:
        if isinstance(ngay_rc, (date, datetime)):
            parts.append(ngay_rc.strftime("%d-%m-%y"))
        else:
            try:
                parts.append(date.fromisoformat(str(ngay_rc)[:10]).strftime("%d-%m-%y"))
            except ValueError:
                parts.append(str(ngay_rc))
    return "_".join(parts) or str(row.get("ke_hoach") or "--")


def normalize_qtcn_to_sx_list(raw: Any) -> List[str]:
    if raw is None:
        return []
    if isinstance(raw, list):
        items = raw
    elif isinstance(raw, str):
        text = raw.strip()
        if not text:
            return []
        try:
            parsed = json.loads(text)
            if isinstance(parsed, list):
                items = parsed
            else:
                items = [text]
        except Exception:
            items = [text]
    else:
        items = [raw]

    out: List[str] = []
    seen = set()
    for item in items:
        text = (str(item or "")).strip()
        if not text:
            continue
        match = re.search(r"(\d+)", text)
        if not match:
            continue
        bo_phan = f"Tổ {int(match.group(1))}"
        if bo_phan not in seen:
            seen.add(bo_phan)
            out.append(bo_phan)
    return out


def normalize_po_info(raw: Any) -> List[Any]:
    if raw is None:
        return []
    if isinstance(raw, list):
        return raw
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return []
        try:
            parsed = json.loads(text)
            return parsed if isinstance(parsed, list) else []
        except Exception:
            return []
    return []


def compute_po_info_total(po_info: List[Any], fallback: Any = None) -> Optional[int]:
    total = 0
    has_quantity = False
    for item in po_info:
        if isinstance(item, dict):
            qty = item.get("quantity")
            try:
                qty_int = int(qty)
            except (TypeError, ValueError):
                continue
            total += qty_int
            has_quantity = True
    if has_quantity:
        return total
    if fallback is None or fallback == "":
        return None
    try:
        return int(fallback)
    except (TypeError, ValueError):
        return None


def build_qtcn_sync_plan_code(source_id: str) -> str:
    safe_id = re.sub(r"[^A-Za-z0-9]+", "", str(source_id or "")).upper()
    return f"{QTCN_SYNC_PLAN_PREFIX}{safe_id}" if safe_id else QTCN_SYNC_PLAN_PREFIX.rstrip("-")


def ensure_prod_plan_is_active(plan_id: Any) -> None:
    try:
        plan_id_int = int(plan_id)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="plan_id không hợp lệ")

    with core.get_db_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT id, COALESCE(is_active, TRUE) AS is_active, is_finished
                FROM public.prod_plan
                WHERE id = %s
                """,
                (plan_id_int,),
            )
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Không tìm thấy kế hoạch")
            if row.get("is_finished"):
                raise HTTPException(status_code=409, detail="Kế hoạch đã kết thúc. Vui lòng chọn lại kế hoạch khác.")
            if not row.get("is_active"):
                raise HTTPException(status_code=409, detail="Kế hoạch đã ngừng hiệu lực. Vui lòng chọn lại kế hoạch khác.")


def sync_qtcn_prod_plan() -> Dict[str, Any]:
    synced = 0
    inserted = 0
    updated = 0
    skipped = 0
    deactivated = 0
    warnings: List[str] = []

    with core.get_prod_factory_connection() as prod_conn:
        with prod_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as prod_cur:
            prod_cur.execute(
                """
                SELECT id, khach_hang, ma_hang, to_sx, ngay_sx, loai_hang, so_po, sl_ke_hoach, status
                FROM public.qtcn_input
                ORDER BY ngay_sx DESC NULLS LAST, created_at DESC
                """
            )
            source_rows = prod_cur.fetchall()

    with core.get_db_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            for row in source_rows:
                source_id = str(row.get("id") or "").strip()
                if not source_id:
                    skipped += 1
                    warnings.append("Bỏ qua 1 record qtcn_input vì thiếu id nguồn")
                    continue

                bo_phan_list = normalize_qtcn_to_sx_list(row.get("to_sx"))
                if not bo_phan_list:
                    skipped += 1
                    warnings.append(f"Bỏ qua {source_id}: không tách được tổ sản xuất")
                    continue

                loai_hang_source = (row.get("loai_hang") or "").strip().upper()
                loai_hang = QTCN_LOAI_HANG_MAP.get(loai_hang_source)
                if not loai_hang:
                    skipped += 1
                    warnings.append(f"Bỏ qua {source_id}: chưa map loại hàng {row.get('loai_hang')}")
                    continue

                source_status = ((row.get("status") or "active").strip() or "active").lower()
                is_active = source_status == "active"
                po_info = normalize_po_info(row.get("so_po"))
                san_luong = compute_po_info_total(po_info, row.get("sl_ke_hoach"))
                ke_hoach = build_qtcn_sync_plan_code(source_id)

                synced += 1
                cur.execute(
                    """
                    UPDATE public.prod_plan
                    SET ke_hoach = %s,
                        don_vi = %s,
                        bo_phan = %s::jsonb,
                        khach_hang = %s,
                        ma_hang = %s,
                        loai_hang = %s,
                        ngay_rc = %s,
                        san_luong = %s,
                        mau = COALESCE(mau, ''),
                        size = COALESCE(size, ''),
                        po_info = %s::jsonb,
                        source_status = %s,
                        is_active = %s,
                        last_synced_at = NOW(),
                        updated_at = NOW()
                    WHERE source_system = %s AND source_record_id = %s
                    """,
                    (
                        ke_hoach,
                        "XNV2",
                        json.dumps(bo_phan_list),
                        (row.get("khach_hang") or "").strip(),
                        (row.get("ma_hang") or "").strip(),
                        loai_hang,
                        row.get("ngay_sx"),
                        san_luong,
                        json.dumps(po_info),
                        source_status,
                        is_active,
                        QTCN_SOURCE_SYSTEM,
                        source_id,
                    ),
                )
                if cur.rowcount:
                    updated += 1
                    if not is_active:
                        deactivated += 1
                    continue

                # Backward compatibility for earlier synced rows keyed only by ke_hoach.
                cur.execute(
                    """
                    UPDATE public.prod_plan
                    SET source_system = %s,
                        source_record_id = %s,
                        ke_hoach = %s,
                        don_vi = %s,
                        bo_phan = %s::jsonb,
                        khach_hang = %s,
                        ma_hang = %s,
                        loai_hang = %s,
                        ngay_rc = %s,
                        san_luong = %s,
                        mau = COALESCE(mau, ''),
                        size = COALESCE(size, ''),
                        po_info = %s::jsonb,
                        source_status = %s,
                        is_active = %s,
                        last_synced_at = NOW(),
                        updated_at = NOW()
                    WHERE ke_hoach = %s
                    """,
                    (
                        QTCN_SOURCE_SYSTEM,
                        source_id,
                        ke_hoach,
                        "XNV2",
                        json.dumps(bo_phan_list),
                        (row.get("khach_hang") or "").strip(),
                        (row.get("ma_hang") or "").strip(),
                        loai_hang,
                        row.get("ngay_sx"),
                        san_luong,
                        json.dumps(po_info),
                        source_status,
                        is_active,
                        ke_hoach,
                    ),
                )
                if cur.rowcount:
                    updated += 1
                    if not is_active:
                        deactivated += 1
                    continue

                cur.execute(
                    """
                    INSERT INTO public.prod_plan
                        (ke_hoach, don_vi, bo_phan, khach_hang, ma_hang, loai_hang,
                         ngay_rc, san_luong, mau, size, po_info,
                         source_system, source_record_id, source_status, is_active, last_synced_at)
                    VALUES (%s, %s, %s::jsonb, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s, NOW())
                    """,
                    (
                        ke_hoach,
                        "XNV2",
                        json.dumps(bo_phan_list),
                        (row.get("khach_hang") or "").strip(),
                        (row.get("ma_hang") or "").strip(),
                        loai_hang,
                        row.get("ngay_sx"),
                        san_luong,
                        "",
                        "",
                        json.dumps(po_info),
                        QTCN_SOURCE_SYSTEM,
                        source_id,
                        source_status,
                        is_active,
                    ),
                )
                inserted += 1
                if not is_active:
                    deactivated += 1
            conn.commit()

    return {
        "status": "ok",
        "synced": synced,
        "inserted": inserted,
        "updated": updated,
        "skipped": skipped,
        "deactivated": deactivated,
        "warnings": warnings[:20],
    }


def run_qtcn_auto_sync_loop() -> None:
    core.logger.info("QTCN auto-sync started with interval %s minutes", core.QTCN_AUTO_SYNC_INTERVAL_MINUTES)
    while True:
        try:
            result = sync_qtcn_prod_plan()
            core.logger.info(
                "QTCN auto-sync completed: synced=%s inserted=%s updated=%s deactivated=%s skipped=%s",
                result.get("synced"),
                result.get("inserted"),
                result.get("updated"),
                result.get("deactivated"),
                result.get("skipped"),
            )
        except Exception:
            core.logger.exception("QTCN auto-sync failed")
        time.sleep(core.QTCN_AUTO_SYNC_INTERVAL_MINUTES * 60)


def start_qtcn_auto_sync_if_enabled() -> None:
    global _qtcn_auto_sync_started
    if not core.QTCN_AUTO_SYNC_ENABLED:
        return
    with _qtcn_auto_sync_lock:
        if _qtcn_auto_sync_started:
            return
        thread = threading.Thread(target=run_qtcn_auto_sync_loop, name="qtcn-auto-sync", daemon=True)
        thread.start()
        _qtcn_auto_sync_started = True


# ==================== FLAT LINE GOOGLE SHEETS SYNC ====================
FLAT_LINE_SOURCE_SYSTEM = "flat_line_sheet"
_flat_line_auto_sync_started = False
_flat_line_auto_sync_lock = threading.Lock()


def normalize_flat_line_don_vi(value: Any) -> str:
    raw = str(value or "").strip().upper()
    aliases = {"XN1": "XN1-V1", "XN1-V1": "XN1-V1", "XN2": "XN2", "XN3": "XN3"}
    return aliases.get(raw, raw)


def get_flat_line_credentials_path() -> PathLib:
    path = PathLib(core.FLAT_LINE_GOOGLE_SERVICE_ACCOUNT_FILE)
    return path if path.is_absolute() else PathLib(__file__).resolve().parent / path


def sync_flat_line_prod_plan(don_vi: str) -> Dict[str, Any]:
    don_vi = normalize_flat_line_don_vi(don_vi)
    config = core.FLAT_LINE_SOURCES.get(don_vi)
    if not config:
        raise ValueError(f"Chưa hỗ trợ nguồn Chuyền bệt cho đơn vị {don_vi}")
    spreadsheet_id = config["spreadsheet_id"]
    if not spreadsheet_id:
        raise ValueError(f"Chưa cấu hình Google Sheet Chuyền bệt cho {don_vi}")
    credentials_path = get_flat_line_credentials_path()
    if not credentials_path.is_file():
        raise FileNotFoundError(f"Không tìm thấy Google service account: {credentials_path}")

    values = fetch_flat_line_sheet_values(
        credentials_path,
        spreadsheet_id,
        core.FLAT_LINE_SHEET_WORKSHEET,
        core.FLAT_LINE_SHEET_RANGE,
    )
    plans, warnings, matched = parse_flat_line_plans(
        values, don_vi, int(config["unit_number"])
    )
    can_reconcile_missing = not warnings
    inserted = updated = deactivated = 0
    source_ids = [plan["source_record_id"] for plan in plans]

    with core.get_db_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT ten_loai FROM public.dm_loai_hang")
            known_product_types = {row["ten_loai"] for row in cur.fetchall()}

            for plan in plans:
                if plan["loai_hang"] not in known_product_types:
                    can_reconcile_missing = False
                    warnings.append(
                        f"Dòng {plan['sheet_row']}: loại hàng chưa có trong QLCL: {plan['loai_hang']}"
                    )
                    continue
                params = (
                    plan["ke_hoach"],
                    plan["don_vi"],
                    json.dumps(plan["bo_phan"], ensure_ascii=False),
                    plan["khach_hang"],
                    plan["ma_hang"],
                    plan["loai_hang"],
                    plan["ngay_rc"],
                    plan["san_luong"],
                    FLAT_LINE_SOURCE_SYSTEM,
                    plan["source_record_id"],
                )
                cur.execute(
                    """
                    UPDATE public.prod_plan
                    SET ke_hoach=%s, don_vi=%s, bo_phan=%s::jsonb,
                        khach_hang=%s, ma_hang=%s, loai_hang=%s,
                        ngay_rc=%s, san_luong=%s,
                        source_status='active', is_active=TRUE,
                        last_synced_at=NOW(), updated_at=NOW()
                    WHERE source_system=%s AND source_record_id=%s
                    """,
                    params,
                )
                if cur.rowcount:
                    updated += 1
                    continue
                cur.execute(
                    """
                    INSERT INTO public.prod_plan
                        (ke_hoach, don_vi, bo_phan, khach_hang, ma_hang, loai_hang,
                         ngay_rc, san_luong, mau, size, po_info,
                         source_system, source_record_id, source_status, is_active, last_synced_at)
                    VALUES (%s,%s,%s::jsonb,%s,%s,%s,%s,%s,'','','[]'::jsonb,%s,%s,'active',TRUE,NOW())
                    """,
                    params,
                )
                inserted += 1

            if can_reconcile_missing:
                cur.execute(
                    """
                    UPDATE public.prod_plan
                    SET source_status='inactive', is_active=FALSE,
                        last_synced_at=NOW(), updated_at=NOW()
                    WHERE source_system=%s AND don_vi=%s
                      AND NOT (source_record_id = ANY(%s))
                      AND COALESCE(is_active, TRUE)=TRUE
                    """,
                    (FLAT_LINE_SOURCE_SYSTEM, don_vi, source_ids),
                )
                deactivated = cur.rowcount
            conn.commit()

    return {
        "status": "ok",
        "source": FLAT_LINE_SOURCE_SYSTEM,
        "don_vi": don_vi,
        "matched": matched,
        "inserted": inserted,
        "updated": updated,
        "skipped": len(warnings),
        "deactivated": deactivated,
        "warnings": warnings[:20],
    }


def sync_all_flat_line_prod_plans() -> Dict[str, Any]:
    """Sync every configured flat-line source and report each factory separately."""
    results = []
    errors = []
    totals = {"inserted": 0, "updated": 0, "deactivated": 0, "skipped": 0}
    for don_vi, config in core.FLAT_LINE_SOURCES.items():
        if not config.get("spreadsheet_id"):
            continue
        try:
            result = sync_flat_line_prod_plan(don_vi)
            results.append(result)
            for key in totals:
                totals[key] += int(result.get(key) or 0)
        except Exception as exc:
            core.logger.exception("Flat-line Sheet sync failed for %s", don_vi)
            errors.append({"don_vi": don_vi, "detail": str(exc)})
    return {
        "status": "ok" if not errors else "partial",
        "factories": results,
        "errors": errors,
        **totals,
    }


def run_flat_line_auto_sync_loop() -> None:
    core.logger.info(
        "Flat-line Sheets auto-sync started, interval=%s minutes",
        core.FLAT_LINE_AUTO_SYNC_INTERVAL_MINUTES,
    )
    while True:
        for don_vi, config in core.FLAT_LINE_SOURCES.items():
            if not config["spreadsheet_id"]:
                continue
            try:
                result = sync_flat_line_prod_plan(don_vi)
                core.logger.info(
                    "Flat-line sync %s ok — matched=%s inserted=%s updated=%s deactivated=%s",
                    don_vi,
                    result["matched"],
                    result["inserted"],
                    result["updated"],
                    result["deactivated"],
                )
            except Exception:
                core.logger.exception("Flat-line sync %s failed", don_vi)
        time.sleep(core.FLAT_LINE_AUTO_SYNC_INTERVAL_MINUTES * 60)


def start_flat_line_auto_sync_if_enabled() -> None:
    global _flat_line_auto_sync_started
    if not core.FLAT_LINE_AUTO_SYNC_ENABLED:
        return
    with _flat_line_auto_sync_lock:
        if _flat_line_auto_sync_started:
            return
        thread = threading.Thread(
            target=run_flat_line_auto_sync_loop,
            name="flat-line-auto-sync",
            daemon=True,
        )
        thread.start()
        _flat_line_auto_sync_started = True


# ==================== HANGING LINE SYNC ====================
# Đồng bộ kế hoạch từ SQL Server chuyền treo → PostgreSQL QLCL
HL_SOURCE_SYSTEM = "hanging_line"
HL_SYNC_PLAN_PREFIX = "HL-"
# LoaiHang trên tPlanMaster lưu trực tiếp tên loại hàng (ten_loai)
# giống bên dm_loai_hang → không cần map nữa.


def build_hl_sync_plan_code(mono: str) -> str:
    """Build ke_hoach code from MONo for hanging-line synced plans."""
    safe = re.sub(r"[^A-Za-z0-9_#\-]+", "", str(mono or "")).strip()
    return f"{HL_SYNC_PLAN_PREFIX}{safe}" if safe else HL_SYNC_PLAN_PREFIX.rstrip("-")


def sync_hanging_line_prod_plan(
    conn_override=None,
    don_vi_override: str | None = None,
) -> Dict[str, Any]:
    """Read tPlanMaster + tDemandRoot + tPlanPO from hanging-line SQL Server
    and upsert into qlcl.prod_plan with source_system='hanging_line'.

    Args:
        conn_override: pyodbc connection đã mở sẵn (dùng cho XNV2 hoặc XN khác).
                       Nếu None thì dùng get_hanging_line_connection() mặc định.
        don_vi_override: ghi đè HANGING_LINE_DON_VI (vd 'XNV2').
    """
    synced = 0
    inserted = 0
    updated = 0
    skipped = 0
    warnings: List[str] = []

    # --- Read from SQL Server ---
    try:
        hl_conn = conn_override if conn_override is not None else core.get_hanging_line_connection()
    except Exception as exc:
        return {"status": "error", "detail": f"Không kết nối được SQL Server chuyền treo: {exc}"}

    try:
        hl_cur = hl_conn.cursor()
        hl_cur.execute("""
            SELECT
                CAST(pm.PlanMaster_guid AS NVARCHAR(36)) AS PlanMaster_guid,
                pm.MONo,
                pm.SoDonHang,
                pm.StyleNo,
                pm.NhuCauMe,
                pm.[LineNo],
                pm.FirstHangDate,
                pm.SLKH,
                pm.Customer,
                pm.LoaiHang,
                dr.DMKT,
                dr.LDBienChe
            FROM app.tPlanMaster pm
            LEFT JOIN app.tDemandRoot dr ON pm.NhuCauMe = dr.NhuCauMe
            ORDER BY pm.FirstHangDate DESC, pm.CreatedAt DESC
        """)
        columns = [col[0] for col in hl_cur.description]
        plan_rows = [dict(zip(columns, row)) for row in hl_cur.fetchall()]

        # Lấy tổng SL PO cho từng plan (QC chỉ cần tổng, không cần chi tiết)
        po_qty_map: Dict[str, int] = {}
        if plan_rows:
            hl_cur.execute("""
                SELECT
                    CAST(PlanMaster_guid AS NVARCHAR(36)) AS PlanMaster_guid,
                    SUM(Qty) AS TotalQty
                FROM app.tPlanPO
                GROUP BY PlanMaster_guid
            """)
            for po_row in hl_cur.fetchall():
                guid = str(po_row[0])
                po_qty_map[guid] = int(po_row[1] or 0)
    finally:
        hl_conn.close()

    # --- Upsert into PostgreSQL ---
    with core.get_db_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            for row in plan_rows:
                mono = str(row.get("MONo") or "").strip()
                if not mono:
                    skipped += 1
                    warnings.append("Bỏ qua 1 record tPlanMaster vì thiếu MONo")
                    continue

                guid_str = str(row["PlanMaster_guid"])
                ke_hoach = build_hl_sync_plan_code(mono)
                line_no = row.get("LineNo") or 0
                don_vi = don_vi_override if don_vi_override is not None else core.HANGING_LINE_DON_VI
                bo_phan_list = [f"Tổ {line_no}"] if line_no else []

                # Loại hàng lấy trực tiếp từ tPlanMaster.LoaiHang (ten_loai)
                loai_hang = (row.get("LoaiHang") or "").strip() or None

                style_no = (row.get("StyleNo") or "").strip()
                customer = (row.get("Customer") or "").strip()
                slkh = row.get("SLKH")
                first_hang = row.get("FirstHangDate")
                po_total = po_qty_map.get(guid_str, 0)
                san_luong = po_total if po_total else slkh

                synced += 1

                # Try UPDATE by (source_system, source_record_id) — primary key
                cur.execute(
                    """
                    UPDATE public.prod_plan
                    SET ke_hoach = %s,
                        don_vi = %s,
                        bo_phan = %s::jsonb,
                        khach_hang = %s,
                        ma_hang = %s,
                        loai_hang = COALESCE(%s, loai_hang),
                        ngay_rc = %s,
                        san_luong = %s,
                        mau = COALESCE(mau, ''),
                        size = COALESCE(size, ''),
                        mono = %s,
                        source_status = 'active',
                        is_active = TRUE,
                        last_synced_at = NOW(),
                        updated_at = NOW()
                    WHERE source_system = %s AND source_record_id = %s
                    """,
                    (
                        ke_hoach,
                        don_vi,
                        json.dumps(bo_phan_list),
                        customer,
                        style_no,
                        loai_hang,
                        first_hang,
                        san_luong,
                        mono,
                        HL_SOURCE_SYSTEM,
                        guid_str,
                    ),
                )
                if cur.rowcount:
                    updated += 1
                    continue

                # Fallback: try UPDATE by mono (nếu đã tồn tại nhưng chưa có source tracking)
                cur.execute(
                    """
                    UPDATE public.prod_plan
                    SET source_system = %s,
                        source_record_id = %s,
                        ke_hoach = %s,
                        don_vi = %s,
                        bo_phan = %s::jsonb,
                        khach_hang = %s,
                        ma_hang = %s,
                        loai_hang = COALESCE(%s, loai_hang),
                        ngay_rc = %s,
                        san_luong = %s,
                        mau = COALESCE(mau, ''),
                        size = COALESCE(size, ''),
                        source_status = 'active',
                        is_active = TRUE,
                        last_synced_at = NOW(),
                        updated_at = NOW()
                    WHERE mono = %s
                    """,
                    (
                        HL_SOURCE_SYSTEM,
                        guid_str,
                        ke_hoach,
                        don_vi,
                        json.dumps(bo_phan_list),
                        customer,
                        style_no,
                        loai_hang,
                        first_hang,
                        san_luong,
                        mono,
                    ),
                )
                if cur.rowcount:
                    updated += 1
                    continue

                # INSERT mới
                cur.execute(
                    """
                    INSERT INTO public.prod_plan
                        (ke_hoach, don_vi, bo_phan, khach_hang, ma_hang, loai_hang,
                         ngay_rc, san_luong, mau, size, mono,
                         source_system, source_record_id, source_status, is_active, last_synced_at)
                    VALUES (%s, %s, %s::jsonb, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                    """,
                    (
                        ke_hoach,
                        don_vi,
                        json.dumps(bo_phan_list),
                        customer,
                        style_no,
                        loai_hang,
                        first_hang,
                        san_luong,
                        "",   # mau
                        "",   # size
                        mono,
                        HL_SOURCE_SYSTEM,
                        guid_str,
                        "active",
                        True,
                    ),
                )
                inserted += 1

            conn.commit()

    return {
        "status": "ok",
        "synced": synced,
        "inserted": inserted,
        "updated": updated,
        "skipped": skipped,
        "warnings": warnings[:20],
    }
