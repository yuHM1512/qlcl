"""Google Sheets reader for Quality Index and RPM detail data.

Supports an in-memory cache with background auto-sync:
  - Quality Index: weekly (default 10080 minutes)
  - RPM Detail: daily (default 1440 minutes)
  - Manual sync via sync_all() / sync_quality_index() / sync_rpm_detail()
"""
from __future__ import annotations

import logging
import os
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

logger = logging.getLogger(__name__)

# ── In-memory cache ──
_cache_lock = threading.Lock()
_quality_index_cache: dict[str, Any] | None = None
_quality_index_cache_time: datetime | None = None
_rpm_detail_cache: dict[str, Any] | None = None
_rpm_detail_cache_time: datetime | None = None

_auto_sync_started = False
_auto_sync_lock = threading.Lock()

SHEETS_READONLY_SCOPE = "https://www.googleapis.com/auth/spreadsheets.readonly"

def _quality_index_sheet_id() -> str:
    return os.getenv("QUALITY_INDEX_SPREADSHEET_ID", "").strip()


def _rpm_detail_sheet_id() -> str:
    return os.getenv("RPM_DETAIL_SPREADSHEET_ID", "").strip()


def _get_service(credentials_file: Path):
    credentials = Credentials.from_service_account_file(
        str(credentials_file), scopes=[SHEETS_READONLY_SCOPE]
    )
    return build("sheets", "v4", credentials=credentials, cache_discovery=False)


def _fetch_values(service, spreadsheet_id: str, range_str: str) -> list[list[Any]]:
    response = (
        service.spreadsheets()
        .values()
        .get(spreadsheetId=spreadsheet_id, range=range_str)
        .execute()
    )
    return response.get("values", [])


def _safe_float(val: Any, default: float | None = None) -> float | None:
    if val is None or str(val).strip() in ("", "-"):
        return default
    try:
        cleaned = str(val).strip().replace(",", ".").replace("%", "").replace(" ", "")
        return float(cleaned)
    except (ValueError, TypeError):
        return default


def _safe_int(val: Any, default: int = 0) -> int:
    if val is None or str(val).strip() == "":
        return default
    try:
        return int(float(str(val).strip().replace(",", "")))
    except (ValueError, TypeError):
        return default


def _cell(row: list, idx: int, default: str = "") -> str:
    if idx < len(row):
        return str(row[idx]).strip()
    return default


def fetch_quality_index(credentials_file: Path, year: int | None = None) -> dict[str, Any]:
    """Fetch quality index dashboard data.

    Quality index sheet columns (0-indexed):
      A(0): Time, B(1): Name, C(2): Month name, D(3): Year, E(4): Customer,
      F(5): cs, G(6): cs_YTD, H(7): cs_HĐKP,
      I(8): qca, J(9): qca_YTD, K(10): qca_HĐKP,
      L(11): rpm, M(12): rpm_YTD, N(13): rpm_HĐKP,
      O(14): nqc, P(15): nqc_YTD, Q(16): nqc_HĐKP,
      R(17): (blank), S(18): CS Target, T(19): RPM Target,
      U(20): QCA Target, V(21): NQC Target,
      W(22): (blank), X(23): month number
    """
    sheet_id = _quality_index_sheet_id()
    if not sheet_id:
        raise ValueError("Chưa cấu hình QUALITY_INDEX_SPREADSHEET_ID trong .env")

    service = _get_service(credentials_file)

    rows = _fetch_values(
        service, sheet_id, "'Quality index'!A2:X100"
    )

    target_rows = _fetch_values(
        service, sheet_id, "'Target'!A2:E20"
    )

    targets_by_year: dict[int, dict] = {}
    for tr in target_rows:
        if not tr:
            continue
        y = _safe_int(tr[0])
        if y:
            targets_by_year[y] = {
                "cs": _safe_float(tr[1] if len(tr) > 1 else None),
                "rpm": _safe_float(tr[2] if len(tr) > 2 else None),
                "qca": _safe_float(tr[3] if len(tr) > 3 else None),
                "nqc": _safe_float(tr[4] if len(tr) > 4 else None),
            }

    available_years: set[int] = set()
    all_data: list[dict] = []

    for row in rows:
        if not row or len(row) < 6:
            continue
        row_year = _safe_int(row[3] if len(row) > 3 else None)
        if not row_year:
            continue
        available_years.add(row_year)
        month_num = _safe_int(row[23] if len(row) > 23 else None)
        if not month_num:
            month_name = _cell(row, 2)
            for i in range(1, 13):
                if f"Tháng {i}" == month_name or f"tháng {i}" == month_name.lower():
                    month_num = i
                    break
        if not month_num:
            continue

        all_data.append({
            "year": row_year,
            "month": month_num,
            "cs": _safe_float(row[5] if len(row) > 5 else None),
            "cs_ytd": _safe_float(row[6] if len(row) > 6 else None),
            "cs_hdkp": _cell(row, 7),
            "qca": _safe_float(row[8] if len(row) > 8 else None),
            "qca_ytd": _safe_float(row[9] if len(row) > 9 else None),
            "rpm": _safe_float(row[11] if len(row) > 11 else None),
            "rpm_ytd": _safe_float(row[12] if len(row) > 12 else None),
            "nqc": _safe_float(row[14] if len(row) > 14 else None),
            "nqc_ytd": _safe_float(row[15] if len(row) > 15 else None),
            "cs_target": _safe_float(row[18] if len(row) > 18 else None),
            "rpm_target": _safe_float(row[19] if len(row) > 19 else None),
            "qca_target": _safe_float(row[20] if len(row) > 20 else None),
            "nqc_target": _safe_float(row[21] if len(row) > 21 else None),
        })

    sorted_years = sorted(available_years, reverse=True)

    if year is None and sorted_years:
        year = sorted_years[0]

    year_data = [d for d in all_data if d["year"] == year]
    year_data.sort(key=lambda d: d["month"])

    prev_year_data = [d for d in all_data if d["year"] == (year - 1 if year else 0)]
    prev_year_lookup = {d["month"]: d for d in prev_year_data}

    months = [f"Tháng {d['month']}" for d in year_data]
    month_nums = [d["month"] for d in year_data]

    cs_scores = [d["cs"] for d in year_data]
    cs_ytd = [d["cs_ytd"] for d in year_data]
    cs_targets = [d["cs_target"] for d in year_data]

    qca_values = [d["qca"] for d in year_data]
    qca_ytd = [d["qca_ytd"] for d in year_data]
    qca_targets = [d["qca_target"] for d in year_data]

    rpm_values = [d["rpm"] for d in year_data]
    rpm_ytd = [d["rpm_ytd"] for d in year_data]
    rpm_targets_raw = [d["rpm_target"] for d in year_data]

    nqc_values = [d["nqc"] for d in year_data]
    nqc_ytd = [d["nqc_ytd"] for d in year_data]
    nqc_targets_raw = [d["nqc_target"] for d in year_data]

    year_target = targets_by_year.get(year, {}) if year else {}
    prev_target = targets_by_year.get(year - 1, {}) if year else {}

    def compute_yoy_change(current_values, prev_lookup, key):
        changes = []
        for d in year_data:
            cur = d.get(key)
            prev = prev_lookup.get(d["month"], {}).get(key) if prev_lookup else None
            if cur is not None and prev is not None and prev != 0:
                changes.append(round((cur - prev) / prev * 100, 1))
            else:
                changes.append(None)
        return changes

    rpm_yoy = compute_yoy_change(rpm_ytd, prev_year_lookup, "rpm_ytd")
    nqc_yoy = compute_yoy_change(nqc_ytd, prev_year_lookup, "nqc_ytd")

    return {
        "years": sorted_years,
        "selected_year": year,
        "months": months,
        "month_nums": month_nums,
        "cs": {
            "scores": cs_scores,
            "ytd": cs_ytd,
            "targets": cs_targets,
        },
        "qca": {
            "values": qca_values,
            "ytd": qca_ytd,
            "targets": qca_targets,
        },
        "rpm": {
            "values": rpm_values,
            "ytd": rpm_ytd,
            "targets_raw": rpm_targets_raw,
            "yoy_change": rpm_yoy,
            "target_change": -5,
        },
        "nqc": {
            "values": nqc_values,
            "ytd": nqc_ytd,
            "targets_raw": nqc_targets_raw,
            "yoy_change": nqc_yoy,
            "target_change": -5,
        },
        "yearly_targets": year_target,
        "all_data": year_data,
    }


def _parse_sheet_date(val: Any) -> tuple[int, int] | None:
    if not val:
        return None
    text = str(val).strip()
    import re
    m = re.match(r"^(\d{1,2})\.(\d{4})$", text)
    if m:
        return (int(m.group(2)), int(m.group(1)))
    m = re.match(r"^(\d{4})\.(\d{1,2})$", text)
    if m:
        return (int(m.group(1)), int(m.group(2)))
    try:
        num = int(float(text))
        if num > 30000:
            from datetime import timedelta
            base = datetime(1899, 12, 30)
            d = base + timedelta(days=num)
            return (d.year, d.month)
    except (ValueError, TypeError):
        pass
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%d.%m.%Y"):
        try:
            d = datetime.strptime(text.split(" ")[0].split("T")[0], fmt)
            return (d.year, d.month)
        except ValueError:
            continue
    return None


def fetch_rpm_detail(
    credentials_file: Path,
    year: int | None = None,
    month: int | None = None,
    ma_hang: str | None = None,
) -> dict[str, Any]:
    """Fetch RPM detail data.

    RPM sheet columns (0-indexed):
      A(0): Tháng (date serial), B(1): Mã hàng, C(2): Bộ phận,
      D(3): Chi tiết, E(4): Dạng lỗi, F(5): Hành động, G(6): Ghi chú
    """
    sheet_id = _rpm_detail_sheet_id()
    if not sheet_id:
        raise ValueError("Chưa cấu hình RPM_DETAIL_SPREADSHEET_ID trong .env")

    service = _get_service(credentials_file)

    rpm_rows = _fetch_values(
        service, sheet_id, "'RPM'!A1:G500"
    )
    cs_rows = _fetch_values(
        service, sheet_id, "'CS'!A1:I500"
    )

    rpm_records = []
    ma_hang_set: set[str] = set()
    months_set: set[str] = set()

    for row in rpm_rows[1:]:
        if not row or len(row) < 5:
            continue
        ym = _parse_sheet_date(row[0])
        if not ym:
            continue

        row_year, row_month = ym
        if year and row_year != year:
            continue
        if month and row_month != month:
            continue

        code = str(row[1]).strip().replace(".0", "") if len(row) > 1 else ""
        if not code:
            continue
        if ma_hang and code != ma_hang:
            continue

        ma_hang_set.add(code)
        months_set.add(f"{row_year}-{row_month:02d}")

        rpm_records.append({
            "thang": f"{row_year}-{row_month:02d}",
            "thang_display": f"Tháng {row_month}/{row_year}",
            "ma_hang": code,
            "bo_phan": _cell(row, 2),
            "chi_tiet": _cell(row, 3),
            "dang_loi": _cell(row, 4),
            "hanh_dong": _cell(row, 5),
            "ghi_chu": _cell(row, 6),
        })

    cs_records = []
    for row in cs_rows[1:]:
        if not row:
            continue
        ym = _parse_sheet_date(row[0])
        if not ym:
            continue

        row_year, row_month = ym
        if year and row_year != year:
            continue
        if month and row_month != month:
            continue

        code = str(row[1]).strip().replace(".0", "") if len(row) > 1 else ""
        if ma_hang and code and code != ma_hang:
            continue

        cs_records.append({
            "thang": f"{row_year}-{row_month:02d}",
            "thang_display": f"Tháng {row_month}/{row_year}",
            "ma_hang": code,
            "bo_phan": _cell(row, 2),
            "chi_tiet": _cell(row, 3),
            "gop_y": _cell(row, 6),
            "hanh_dong": _cell(row, 7),
            "ghi_chu": _cell(row, 8),
        })

    return {
        "rpm": rpm_records,
        "cs": cs_records,
        "ma_hang_options": sorted(ma_hang_set),
        "month_options": sorted(months_set),
    }


# ── Cache helpers ──

def sync_quality_index(credentials_file: Path) -> dict[str, Any]:
    """Fetch Quality Index from Sheets and update cache. Returns summary."""
    global _quality_index_cache, _quality_index_cache_time
    data = fetch_quality_index(credentials_file, year=None)
    all_years = data.get("years", [])
    cache: dict[int, dict] = {}
    for y in all_years:
        cache[y] = fetch_quality_index(credentials_file, year=y)
    with _cache_lock:
        _quality_index_cache = cache
        _quality_index_cache_time = datetime.now()
    logger.info("Quality Index cache updated — %d years", len(all_years))
    return {"years": all_years, "synced_at": _quality_index_cache_time.isoformat()}


def sync_rpm_detail(credentials_file: Path) -> dict[str, Any]:
    """Fetch RPM Detail from Sheets and update cache. Returns summary."""
    global _rpm_detail_cache, _rpm_detail_cache_time
    data = fetch_rpm_detail(credentials_file)
    with _cache_lock:
        _rpm_detail_cache = data
        _rpm_detail_cache_time = datetime.now()
    rpm_count = len(data.get("rpm", []))
    cs_count = len(data.get("cs", []))
    logger.info("RPM Detail cache updated — %d RPM, %d CS records", rpm_count, cs_count)
    return {"rpm": rpm_count, "cs": cs_count, "synced_at": _rpm_detail_cache_time.isoformat()}


def sync_all(credentials_file: Path) -> dict[str, Any]:
    """Sync both Quality Index and RPM Detail."""
    qi = sync_quality_index(credentials_file)
    rpm = sync_rpm_detail(credentials_file)
    return {"quality_index": qi, "rpm_detail": rpm}


def get_cached_quality_index(year: int | None = None) -> dict[str, Any] | None:
    """Return cached Quality Index data for the given year, or None if not cached."""
    with _cache_lock:
        if _quality_index_cache is None:
            return None
        if year is None:
            all_years = sorted(_quality_index_cache.keys(), reverse=True)
            year = all_years[0] if all_years else None
        if year is None:
            return None
        data = _quality_index_cache.get(year)
        if data is None:
            return None
        data = dict(data)
        data["cache_time"] = _quality_index_cache_time.isoformat() if _quality_index_cache_time else None
        return data


def get_cached_rpm_detail(
    year: int | None = None,
    month: int | None = None,
    ma_hang: str | None = None,
) -> dict[str, Any] | None:
    """Return cached RPM Detail data with optional filters, or None if not cached."""
    with _cache_lock:
        if _rpm_detail_cache is None:
            return None
        data = _rpm_detail_cache
    rpm = data.get("rpm", [])
    cs = data.get("cs", [])
    if year:
        rpm = [r for r in rpm if r["thang"].startswith(f"{year}-")]
        cs = [c for c in cs if c["thang"].startswith(f"{year}-")]
    if month:
        m_str = f"-{month:02d}"
        rpm = [r for r in rpm if r["thang"].endswith(m_str)]
        cs = [c for c in cs if c["thang"].endswith(m_str)]
    if ma_hang:
        rpm = [r for r in rpm if r["ma_hang"] == ma_hang]
        cs = [c for c in cs if c.get("ma_hang") == ma_hang]
    all_ma = sorted({r["ma_hang"] for r in rpm if r["ma_hang"]})
    all_months = sorted({r["thang"] for r in rpm})
    return {
        "rpm": rpm,
        "cs": cs,
        "ma_hang_options": all_ma,
        "month_options": all_months,
        "cache_time": _rpm_detail_cache_time.isoformat() if _rpm_detail_cache_time else None,
    }


def get_cache_status() -> dict[str, Any]:
    """Return sync status for both caches."""
    with _cache_lock:
        return {
            "quality_index": {
                "cached": _quality_index_cache is not None,
                "synced_at": _quality_index_cache_time.isoformat() if _quality_index_cache_time else None,
            },
            "rpm_detail": {
                "cached": _rpm_detail_cache is not None,
                "synced_at": _rpm_detail_cache_time.isoformat() if _rpm_detail_cache_time else None,
            },
        }


# ── Auto-sync background threads ──

def _quality_index_sync_interval() -> int:
    """Minutes between Quality Index syncs (default: 10080 = 1 week)."""
    return int(os.getenv("QUALITY_INDEX_SYNC_INTERVAL_MINUTES", "10080"))


def _rpm_detail_sync_interval() -> int:
    """Minutes between RPM Detail syncs (default: 1440 = 1 day)."""
    return int(os.getenv("RPM_DETAIL_SYNC_INTERVAL_MINUTES", "1440"))


def _quality_index_auto_sync_loop(credentials_file: Path) -> None:
    interval = _quality_index_sync_interval()
    logger.info("Quality Index auto-sync started, interval=%d minutes", interval)
    while True:
        try:
            sync_quality_index(credentials_file)
        except Exception:
            logger.exception("Quality Index auto-sync failed")
        time.sleep(interval * 60)


def _rpm_detail_auto_sync_loop(credentials_file: Path) -> None:
    interval = _rpm_detail_sync_interval()
    logger.info("RPM Detail auto-sync started, interval=%d minutes", interval)
    while True:
        try:
            sync_rpm_detail(credentials_file)
        except Exception:
            logger.exception("RPM Detail auto-sync failed")
        time.sleep(interval * 60)


def start_auto_sync(credentials_file: Path) -> None:
    """Start background sync threads for Quality Index (weekly) and RPM Detail (daily)."""
    global _auto_sync_started
    with _auto_sync_lock:
        if _auto_sync_started:
            return
        _auto_sync_started = True

    qi_enabled = os.getenv("QUALITY_INDEX_AUTO_SYNC_ENABLED", "true").lower() in ("1", "true", "yes")
    rpm_enabled = os.getenv("RPM_DETAIL_AUTO_SYNC_ENABLED", "true").lower() in ("1", "true", "yes")

    if qi_enabled:
        threading.Thread(
            target=_quality_index_auto_sync_loop,
            args=(credentials_file,),
            name="quality-index-sync",
            daemon=True,
        ).start()
    else:
        logger.info("Quality Index auto-sync disabled")

    if rpm_enabled:
        threading.Thread(
            target=_rpm_detail_auto_sync_loop,
            args=(credentials_file,),
            name="rpm-detail-sync",
            daemon=True,
        ).start()
    else:
        logger.info("RPM Detail auto-sync disabled")
