"""Google Sheets -> QLCL weekly quality bulletin sync and draft builder."""

from __future__ import annotations

import json
import os
import re
import unicodedata
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import psycopg2.extras
from google.oauth2 import service_account
from googleapiclient.discovery import build


SHEETS_SCOPE = ["https://www.googleapis.com/auth/spreadsheets.readonly"]

ENDLINE_FINAL_SHEET_ID = os.getenv(
    "BULLETIN_ENDLINE_FINAL_SHEET_ID", "1Ii9MdvSFmzK4GI435QYRgzyfw3Ea_LUB9nAZgrMzGz0"
)
PROBLEM_SHEET_ID = os.getenv(
    "BULLETIN_PROBLEM_SHEET_ID", "15LWOqy7vl4AkEXVymNlbnehu2P7zc6h9sMuVutrCm3I"
)
SURVEY_SHEET_ID = os.getenv(
    "BULLETIN_SURVEY_SHEET_ID", "1vzlatbajMVFbWSbVVa2RUQ5EEXikR2QAqFToGuHYODQ"
)
EVALUATION_SHEET_ID = os.getenv(
    "BULLETIN_EVALUATION_SHEET_ID", "1mqnn7_xXdo0rY7zEjZm2T9KHQpsRfeCxsS6fitkQlns"
)

SHEET_SOURCES = (
    ("final", ENDLINE_FINAL_SHEET_ID, "FINAL", "A:T", 280210348),
    ("endline", ENDLINE_FINAL_SHEET_ID, "INLINE", "A:AH", 1139302328),
    ("endline_cap", ENDLINE_FINAL_SHEET_ID, "CAP (1)", "A:N", 598258570),
    ("complaint", PROBLEM_SHEET_ID, "Complaint", "A:V", 1257874888),
    ("problem_raw", PROBLEM_SHEET_ID, "GQVĐ", "A:AJ", 1522864433),
    ("problem_action", PROBLEM_SHEET_ID, "HĐKP", "A:L", None),
    ("survey_internal", SURVEY_SHEET_ID, "1.1 DATA KH NỘI BỘ", "A:N", None),
    ("survey_external", SURVEY_SHEET_ID, "2.1 DATA KH BÊN NGOÀI", "A:N", None),
    ("evaluation", EVALUATION_SHEET_ID, "1. VẤN ĐỀ", "A:AC", 507583362),
)

SOURCE_AUTHORITATIVE_TYPES = {"final", "endline_cap"}
DONE_MARKERS = ("hoan thanh", "da dong", "closed", "complete", "done")


def normalize_text(value: Any) -> str:
    text = str(value or "").strip().lower()
    text = "".join(ch for ch in unicodedata.normalize("NFKD", text) if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", text.replace("đ", "d"))


def clean_header(value: Any) -> str:
    return re.sub(r"\s+", " ", normalize_text(value).replace("/", " ").replace("-", " ").replace("_", " ")).strip()


def row_dicts(values: Sequence[Sequence[Any]]) -> List[Dict[str, Any]]:
    if not values:
        return []
    headers = [clean_header(value) or f"column_{idx + 1}" for idx, value in enumerate(values[0])]
    rows: List[Dict[str, Any]] = []
    for row in values[1:]:
        if not any(str(value or "").strip() for value in row):
            continue
        padded = list(row) + [None] * max(0, len(headers) - len(row))
        rows.append({headers[idx]: padded[idx] for idx in range(len(headers))})
    return rows


def pick(row: Dict[str, Any], *names: str, default: Any = None) -> Any:
    for name in names:
        key = clean_header(name)
        if key in row and row[key] not in (None, ""):
            return row[key]
    return default


def parse_date(value: Any) -> Optional[date]:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, (int, float)):
        try:
            return date(1899, 12, 30) + timedelta(days=int(value))
        except (OverflowError, ValueError):
            return None
    text = str(value).strip().split(" ")[0]
    for fmt in ("%d/%m/%Y", "%d/%m/%y", "%Y-%m-%d", "%m/%d/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            pass
    return None


def parse_decimal(value: Any, *, percent: bool = False) -> Optional[Decimal]:
    if value in (None, ""):
        return None
    if isinstance(value, Decimal):
        result = value
    elif isinstance(value, (int, float)):
        result = Decimal(str(value))
    else:
        text = str(value).strip().replace(" ", "")
        is_percent = text.endswith("%")
        text = text.rstrip("%").replace(",", ".")
        try:
            result = Decimal(text)
        except InvalidOperation:
            match = re.search(r"-?\d+(?:[.,]\d+)?", text)
            if not match:
                return None
            result = Decimal(match.group(0).replace(",", "."))
        if is_percent:
            return result
    if percent and abs(result) <= 1:
        result *= 100
    return result


def is_done(status: Any) -> bool:
    normalized = normalize_text(status)
    return bool(normalized and any(marker in normalized for marker in DONE_MARKERS))


def previous_report_period(as_of: Optional[date] = None) -> Tuple[date, date]:
    current = as_of or date.today()
    current_monday = current - timedelta(days=current.weekday())
    start = current_monday - timedelta(days=7)
    return start, start + timedelta(days=5)


def kpi_report_period(report_week_start: date, report_week_end: date) -> Tuple[date, date]:
    """Return the cumulative period used by KPI 1-2-3 for a bulletin.

    A bulletin prepared in the first Monday week of a month uses the complete
    previous month. Later bulletins accumulate from the first day of the
    current month through the report Saturday.
    """
    if report_week_start.day <= 7:
        previous_month_end = report_week_start.replace(day=1) - timedelta(days=1)
        return previous_month_end.replace(day=1), previous_month_end
    return report_week_start.replace(day=1), report_week_end


def spreadsheet_url(spreadsheet_id: str, gid: Optional[int] = None) -> str:
    suffix = f"/edit?gid={gid}#gid={gid}" if gid is not None else "/edit"
    return f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}{suffix}"


def _credential_path() -> str:
    configured = os.getenv("BULLETIN_GOOGLE_SERVICE_ACCOUNT_FILE", "").strip()
    if configured:
        return configured
    gemba = os.getenv("GEMBA_CP_GOOGLE_SERVICE_ACCOUNT_FILE", "").strip()
    if gemba:
        return gemba
    return str(Path(__file__).resolve().parent / "gemba_cp" / "templates" / "credentials_m29.json")


def build_sheets_service():
    credentials = service_account.Credentials.from_service_account_file(
        _credential_path(), scopes=SHEETS_SCOPE
    )
    return build("sheets", "v4", credentials=credentials, cache_discovery=False)


def fetch_sheet_values(service: Any, spreadsheet_id: str, sheet_name: str, cell_range: str) -> List[List[Any]]:
    safe_name = sheet_name.replace("'", "''")
    result = (
        service.spreadsheets()
        .values()
        .get(
            spreadsheetId=spreadsheet_id,
            range=f"'{safe_name}'!{cell_range}",
            valueRenderOption="FORMATTED_VALUE",
        )
        .execute()
    )
    return result.get("values", [])


def _jsonable(row: Dict[str, Any]) -> Dict[str, Any]:
    return {str(key): value if value is None or isinstance(value, (str, int, float, bool)) else str(value) for key, value in row.items()}


def _source_record(source_type: str, row: Dict[str, Any], index: int, *, gid: Optional[int], spreadsheet_id: str) -> Dict[str, Any]:
    source_id = str(pick(row, "ID", "ID Inline", default="") or "").strip()
    source_no = str(pick(row, "No", "STT", default="") or "").strip()
    if not source_id:
        source_id = source_no or f"row-{index + 2}"
    source_date = parse_date(pick(row, "Thời gian", "Ngày", "Ngày đánh giá", "Time"))
    base: Dict[str, Any] = {
        "source_type": source_type,
        "source_id": source_id,
        "source_no": source_no or source_id,
        "source_date": source_date,
        "unit_name": "",
        "product_type": "",
        "topic": "",
        "description": "",
        "source_status": "",
        "source_deadline": None,
        "source_owner": "",
        "source_url": spreadsheet_url(spreadsheet_id, gid),
        "inspected_count": None,
        "failed_count": None,
        "rate": None,
        "target": None,
        "payload": _jsonable(row),
    }
    if source_type == "final":
        base.update(
            unit_name=str(pick(row, "Xí nghiệp", default="") or ""),
            product_type=str(pick(row, "Loại hàng", default="") or ""),
            topic="Final",
            description=str(pick(row, "Ghi chú", "Ghi chú cam kết CL", "Loại lỗi", default="Kết quả Final vượt mục tiêu") or "Kết quả Final vượt mục tiêu"),
            source_status=str(pick(row, "CAP status", default="") or ""),
            inspected_count=parse_decimal(pick(row, "Tổng PO KIỂM")),
            failed_count=parse_decimal(pick(row, "Tổng PO FAIL")),
            rate=parse_decimal(pick(row, "Tỉ lê Final", "Tỉ lệ Final"), percent=True),
            target=parse_decimal(pick(row, "Target"), percent=True),
        )
        cap_url = pick(row, "Hành động khắc phục")
        if cap_url and str(cap_url).startswith("http"):
            base["source_url"] = str(cap_url)
    elif source_type == "endline":
        base.update(
            unit_name=str(pick(row, "Xí nghiệp sản xuất", default="") or ""),
            product_type=str(pick(row, "Loại hàng", default="") or ""),
            topic="Endline",
            description=str(pick(row, "Các lỗi chính cần lưu ý", default="Kết quả Endline") or "Kết quả Endline"),
            inspected_count=parse_decimal(pick(row, "Tổng số sản phẩm đã kiểm")),
            failed_count=parse_decimal(pick(row, "Tổng số sản phẩm bị lỗi")),
            rate=parse_decimal(pick(row, "Tỉ lệ"), percent=True),
            target=parse_decimal(pick(row, "Tỉ lệ mục tiêu"), percent=True),
        )
    elif source_type == "endline_cap":
        year = pick(row, "Năm")
        month = pick(row, "Tháng")
        if not source_date and year and month:
            try:
                source_date = date(int(float(str(year))), int(float(str(month))), 1)
            except (ValueError, TypeError):
                pass
        base.update(
            source_date=source_date,
            unit_name=str(pick(row, "Xí nghiệp", default="") or ""),
            product_type=str(pick(row, "Loại hàng", default="") or ""),
            topic="Endline CAP tháng",
            description=str(pick(row, "Lý do mở CAP", "Top 3 lỗi", default="Endline tháng vượt mục tiêu") or "Endline tháng vượt mục tiêu"),
            source_status=str(pick(row, "Tình trạng", default="") or ""),
            inspected_count=parse_decimal(pick(row, "Tổng số sản phẩm đã kiểm")),
            failed_count=parse_decimal(pick(row, "Tổng số sản phẩm bị lỗi")),
            rate=parse_decimal(pick(row, "Tỉ lệ chất lượng"), percent=True),
            target=parse_decimal(pick(row, "Mục tiêu"), percent=True),
        )
        cap_url = pick(row, "CAP")
        if cap_url and str(cap_url).startswith("http"):
            base["source_url"] = str(cap_url)
    elif source_type == "complaint":
        base.update(
            unit_name=str(pick(row, "Đơn vị", "Đơn vị giải quyết", default="") or ""),
            product_type=str(pick(row, "Mã hàng", default="") or ""),
            topic="Khiếu nại",
            description=str(pick(row, "Mô tả lỗi", "Phân loại lỗi", default="Khiếu nại khách hàng") or "Khiếu nại khách hàng"),
            source_status="Hoàn thành" if pick(row, "Thời gian đóng HĐKP") else "Chưa tiếp nhận",
            source_deadline=parse_date(pick(row, "Ngày yêu cầu làm HĐKP")),
            source_owner=str(pick(row, "Đơn vị giải quyết", default="") or ""),
        )
        action_url = pick(row, "Biểu mẫu hành động khắc phục")
        if action_url and str(action_url).startswith("http"):
            base["source_url"] = str(action_url)
    elif source_type in {"survey_internal", "survey_external"}:
        base.update(
            unit_name=str(pick(row, "Đơn vị", default="") or ""),
            topic="Khảo sát nội bộ" if source_type.endswith("internal") else "Khảo sát bên ngoài",
            description=str(pick(row, "Lĩnh vực cần cải thiện", "Lý do điểm thấp", default="CAP khảo sát") or "CAP khảo sát"),
            source_status=str(pick(row, "Tình trạng", default="") or ""),
            source_owner=str(pick(row, "Người thực hiện", "Người tạo CAP", default="") or ""),
        )
    elif source_type == "evaluation":
        base.update(
            unit_name=str(pick(row, "Đơn vị phát sinh lỗi", "Đơn vị đánh giá", default="") or ""),
            topic="Hệ thống đánh giá",
            description=str(pick(row, "Lỗi", "Tiêu chuẩn", default="Vấn đề đánh giá") or "Vấn đề đánh giá"),
            source_status=str(pick(row, "Tình trạng", default="") or ""),
            source_owner=str(pick(row, "Đơn vị chủ trì giải quyết", default="") or ""),
        )
    elif source_type in {"production_meeting", "problem_solving"}:
        base.update(
            unit_name=str(pick(row, "Đơn vị phát sinh", "Department solve", default="") or ""),
            topic="Họp sản xuất" if source_type == "production_meeting" else "Giải quyết vấn đề",
            description=str(pick(row, "What", "Chủ đề", "Request", default="Vấn đề sản xuất") or "Vấn đề sản xuất"),
            source_status=str(pick(row, "Problem status", default="") or ""),
            source_owner=str(pick(row, "Department solve", "Who", default="") or ""),
        )
    return base


def parse_source_rows(source_type: str, values: Sequence[Sequence[Any]], spreadsheet_id: str, gid: Optional[int], actions: Optional[Dict[str, Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
    result: List[Dict[str, Any]] = []
    for index, row in enumerate(row_dicts(values)):
        effective_type = source_type
        if source_type == "problem_raw":
            code = str(pick(row, "No", "ID", default="") or "").strip().upper()
            effective_type = "production_meeting" if code.startswith("HSX") else "problem_solving"
        record = _source_record(effective_type, row, index, gid=gid, spreadsheet_id=spreadsheet_id)
        action = (actions or {}).get(record["source_id"])
        if action:
            record["source_status"] = str(pick(action, "Action status", default=record["source_status"]) or record["source_status"])
            record["source_deadline"] = parse_date(pick(action, "Action when")) or record["source_deadline"]
            record["source_owner"] = str(pick(action, "Action department", "Action team", default=record["source_owner"]) or record["source_owner"])
            record["payload"]["linked_action"] = _jsonable(action)
        result.append(record)
    return result


def _upsert_source_records(conn: Any, source_type: str, records: List[Dict[str, Any]]) -> int:
    with conn.cursor() as cur:
        cur.execute("UPDATE public.bulletin_source_records SET is_active = FALSE WHERE source_type = %s", (source_type,))
        for record in records:
            cur.execute(
                """
                INSERT INTO public.bulletin_source_records (
                    source_type, source_id, source_no, source_date, unit_name, product_type,
                    topic, description, source_status, source_deadline, source_owner, source_url,
                    inspected_count, failed_count, rate, target, payload, is_active, last_seen_at, synced_at
                ) VALUES (
                    %(source_type)s, %(source_id)s, %(source_no)s, %(source_date)s, %(unit_name)s,
                    %(product_type)s, %(topic)s, %(description)s, %(source_status)s,
                    %(source_deadline)s, %(source_owner)s, %(source_url)s, %(inspected_count)s,
                    %(failed_count)s, %(rate)s, %(target)s, %(payload)s::jsonb, TRUE, NOW(), NOW()
                )
                ON CONFLICT (source_type, source_id) DO UPDATE SET
                    source_no = EXCLUDED.source_no, source_date = EXCLUDED.source_date,
                    unit_name = EXCLUDED.unit_name, product_type = EXCLUDED.product_type,
                    topic = EXCLUDED.topic, description = EXCLUDED.description,
                    source_status = EXCLUDED.source_status, source_deadline = EXCLUDED.source_deadline,
                    source_owner = EXCLUDED.source_owner, source_url = EXCLUDED.source_url,
                    inspected_count = EXCLUDED.inspected_count, failed_count = EXCLUDED.failed_count,
                    rate = EXCLUDED.rate, target = EXCLUDED.target, payload = EXCLUDED.payload,
                    is_active = TRUE, last_seen_at = NOW(), synced_at = NOW()
                """,
                {**record, "payload": json.dumps(record["payload"], ensure_ascii=False)},
            )
    return len(records)


def sync_bulletin_sources(connection_factory: Callable[[], Any], *, triggered_by: str = "system", trigger_type: str = "manual", service: Any = None) -> Dict[str, int]:
    with connection_factory() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO public.quality_bulletin_sync_runs (trigger_type, triggered_by) VALUES (%s, %s) RETURNING id",
                (trigger_type, triggered_by),
            )
            run_id = cur.fetchone()[0]
        conn.commit()
    counts: Dict[str, int] = {}
    try:
        sheets = service or build_sheets_service()
        fetched: Dict[str, List[List[Any]]] = {}
        for key, spreadsheet_id, sheet_name, cell_range, _gid in SHEET_SOURCES:
            fetched[key] = fetch_sheet_values(sheets, spreadsheet_id, sheet_name, cell_range)
        actions_by_problem: Dict[str, Dict[str, Any]] = {}
        for action in row_dicts(fetched["problem_action"]):
            problem_id = str(pick(action, "Problem ID", default="") or "").strip()
            if problem_id:
                current = actions_by_problem.get(problem_id)
                if current is None or (is_done(pick(current, "Action status")) and not is_done(pick(action, "Action status"))):
                    actions_by_problem[problem_id] = action

        with connection_factory() as conn:
            for key, spreadsheet_id, _sheet_name, _range, gid in SHEET_SOURCES:
                if key == "problem_action":
                    continue
                records = parse_source_rows(
                    key,
                    fetched[key],
                    spreadsheet_id,
                    gid,
                    actions=actions_by_problem if key == "problem_raw" else None,
                )
                grouped: Dict[str, List[Dict[str, Any]]] = {}
                for record in records:
                    grouped.setdefault(record["source_type"], []).append(record)
                for effective_type, group in grouped.items():
                    counts[effective_type] = _upsert_source_records(conn, effective_type, group)
            conn.commit()
        with connection_factory() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE public.quality_bulletin_sync_runs SET status='success', finished_at=NOW(), source_counts=%s::jsonb WHERE id=%s",
                    (json.dumps(counts), run_id),
                )
            conn.commit()
        return counts
    except Exception as exc:
        with connection_factory() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE public.quality_bulletin_sync_runs SET status='failed', finished_at=NOW(), error_message=%s WHERE id=%s",
                    (str(exc)[:4000], run_id),
                )
            conn.commit()
        raise


def _initial_status(source_status: Any) -> str:
    if is_done(source_status):
        return "Hoàn thành"
    return str(source_status or "Chưa tiếp nhận").strip() or "Chưa tiếp nhận"


def ensure_weekly_draft(connection_factory: Callable[[], Any], *, as_of: Optional[date] = None, created_by: str = "system") -> Dict[str, Any]:
    week_start, week_end = previous_report_period(as_of)
    iso_year, iso_week, _ = week_start.isocalendar()
    with connection_factory() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                INSERT INTO public.quality_bulletins (week_start, week_end, iso_year, iso_week, created_by, updated_by)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (week_start) DO UPDATE SET updated_at = NOW()
                RETURNING *
                """,
                (week_start, week_end, iso_year, iso_week, created_by, created_by),
            )
            bulletin = dict(cur.fetchone())
            bulletin_id = bulletin["id"]
            if bulletin["status"] == "verified":
                conn.commit()
                return bulletin

            cur.execute(
                """
                SELECT * FROM public.bulletin_source_records
                WHERE is_active
                  AND (
                    (source_type = 'complaint' AND source_date BETWEEN %s AND %s)
                    OR (source_type IN ('evaluation','production_meeting','problem_solving')
                        AND source_date BETWEEN %s AND %s
                        AND (
                            UPPER(COALESCE(unit_name,'')) LIKE '%%QLCL%%'
                            OR UPPER(COALESCE(source_owner,'')) LIKE '%%QLCL%%'
                            OR UPPER(payload::text) LIKE '%%QLCL%%'
                        )
                        AND NOT (
                            source_type='evaluation' AND (
                                LOWER(COALESCE(source_status,'')) LIKE '%%không có vấn đề%%'
                                OR LOWER(COALESCE(source_status,'')) LIKE '%%khong co van de%%'
                            )
                        ))
                    OR (source_type = 'final' AND source_date BETWEEN %s AND %s
                        AND rate IS NOT NULL AND target IS NOT NULL AND rate > target)
                    OR (source_type IN ('survey_internal','survey_external')
                        AND (
                            UPPER(COALESCE(unit_name,'')) LIKE '%%QLCL%%'
                            OR UPPER(COALESCE(source_owner,'')) LIKE '%%QLCL%%'
                            OR UPPER(payload::text) LIKE '%%QLCL%%'
                        ) AND NOT (
                        LOWER(COALESCE(source_status,'')) LIKE '%%hoàn thành%%'
                        OR LOWER(COALESCE(source_status,'')) LIKE '%%hoan thanh%%'))
                    OR (source_type = 'endline_cap' AND rate IS NOT NULL AND target IS NOT NULL
                        AND rate > target AND source_date >= date_trunc('month', %s::date - interval '1 month')::date)
                  )
                ORDER BY source_date NULLS LAST, id
                """,
                (week_start, week_end, week_start, week_end, week_start, week_end, week_start),
            )
            records = [dict(row) for row in cur.fetchall()]
            for record in records:
                origin = "source" if record["source_type"] in SOURCE_AUTHORITATIVE_TYPES else "manual"
                status = _initial_status(record.get("source_status"))
                cur.execute(
                    """
                    INSERT INTO public.quality_bulletin_items (
                        bulletin_id, source_record_id, source_type, source_id, source_no, topic,
                        unit_name, description, source_status, status, status_origin, deadline,
                        owner_name, source_url, payload
                    ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (bulletin_id, source_type, source_id) DO UPDATE SET
                        source_record_id=EXCLUDED.source_record_id, source_no=EXCLUDED.source_no,
                        topic=EXCLUDED.topic, unit_name=EXCLUDED.unit_name,
                        description=EXCLUDED.description, source_status=EXCLUDED.source_status,
                        status=CASE WHEN quality_bulletin_items.status_origin='source' THEN EXCLUDED.status ELSE quality_bulletin_items.status END,
                        deadline=COALESCE(quality_bulletin_items.deadline, EXCLUDED.deadline),
                        owner_name=COALESCE(NULLIF(quality_bulletin_items.owner_name,''), EXCLUDED.owner_name),
                        source_url=EXCLUDED.source_url, payload=EXCLUDED.payload, updated_at=NOW()
                    """,
                    (
                        bulletin_id, record["id"], record["source_type"], record["source_id"],
                        record.get("source_no"), record.get("topic"), record.get("unit_name"),
                        record.get("description"), record.get("source_status"), status, origin,
                        record.get("source_deadline"), record.get("source_owner"), record.get("source_url"),
                        psycopg2.extras.Json(record.get("payload") or {}),
                    ),
                )

            cur.execute(
                """
                SELECT i.*,
                       sr.source_status AS latest_source_status,
                       sr.source_deadline AS latest_source_deadline,
                       sr.source_url AS latest_source_url
                FROM public.quality_bulletin_items i
                JOIN public.quality_bulletins b ON b.id=i.bulletin_id
                LEFT JOIN public.bulletin_source_records sr ON sr.id=i.source_record_id
                WHERE b.week_start < %s
                  AND NOT (LOWER(i.status) LIKE '%%hoàn thành%%' OR LOWER(i.status) LIKE '%%hoan thanh%%')
                  AND NOT (
                      i.status_origin='source' AND (
                          LOWER(COALESCE(sr.source_status,'')) LIKE '%%hoàn thành%%'
                          OR LOWER(COALESCE(sr.source_status,'')) LIKE '%%hoan thanh%%'
                          OR LOWER(COALESCE(sr.source_status,'')) LIKE '%%closed%%'
                      )
                  )
                ORDER BY b.week_start DESC, i.id DESC
                """,
                (week_start,),
            )
            seen: set[Tuple[str, str]] = set()
            for old in cur.fetchall():
                key = (old["source_type"], old["source_id"])
                if key in seen:
                    continue
                seen.add(key)
                cur.execute(
                    """
                    INSERT INTO public.quality_bulletin_items (
                        bulletin_id, source_record_id, source_type, source_id, source_no, topic,
                        unit_name, description, source_status, status, status_origin, deadline,
                        owner_ma_nv, owner_name, source_url, carried_from_item_id, payload
                    ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (bulletin_id, source_type, source_id) DO NOTHING
                    """,
                    (
                        bulletin_id, old["source_record_id"], old["source_type"], old["source_id"],
                        old["source_no"], old["topic"], old["unit_name"], old["description"],
                        old["latest_source_status"] or old["source_status"],
                        _initial_status(old["latest_source_status"]) if old["status_origin"] == "source" else old["status"],
                        old["status_origin"], old["latest_source_deadline"] or old["deadline"],
                        old["owner_ma_nv"], old["owner_name"], old["latest_source_url"] or old["source_url"], old["id"],
                        psycopg2.extras.Json(old["payload"] or {}),
                    ),
                )
            _refresh_metrics(cur, bulletin_id, week_start, week_end)
            _refresh_kpis(cur, bulletin_id, week_start, week_end)
        conn.commit()
    return bulletin


def _refresh_metrics(cur: Any, bulletin_id: int, week_start: date, week_end: date) -> None:
    cur.execute("DELETE FROM public.quality_bulletin_metrics WHERE bulletin_id=%s", (bulletin_id,))
    periods: List[Tuple[str, date, date]] = [
        ("weekly", week_start, week_end),
        ("monthly", *kpi_report_period(week_start, week_end)),
    ]
    for period_type, start, end in periods:
        for source_type in ("final", "endline"):
            cur.execute(
                """
                SELECT COALESCE(unit_name,'') AS unit_name,
                       COALESCE(product_type,'') AS product_type,
                       SUM(inspected_count) AS inspected_count,
                       SUM(failed_count) AS failed_count,
                       CASE WHEN SUM(inspected_count) > 0 THEN SUM(failed_count) * 100.0 / SUM(inspected_count)
                            ELSE AVG(rate) END AS calculated_rate,
                       MAX(target) AS target
                FROM public.bulletin_source_records
                WHERE is_active AND source_type=%s AND source_date BETWEEN %s AND %s
                GROUP BY COALESCE(unit_name,''), COALESCE(product_type,'')
                """,
                (source_type, start, end),
            )
            for metric_row in cur.fetchall():
                if isinstance(metric_row, dict):
                    unit_name = metric_row["unit_name"]
                    product_type = metric_row["product_type"]
                    inspected = metric_row["inspected_count"]
                    failed = metric_row["failed_count"]
                    rate = metric_row["calculated_rate"]
                    target = metric_row["target"]
                else:
                    unit_name, product_type, inspected, failed, rate, target = metric_row
                passed = None if rate is None or target is None else rate <= target
                cur.execute(
                    """
                    INSERT INTO public.quality_bulletin_metrics (
                        bulletin_id, period_type, source_type, period_start, period_end,
                        unit_name, product_type, inspected_count, failed_count, rate, target, passed
                    ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    """,
                    (bulletin_id, period_type, source_type, start, end, unit_name, product_type, inspected, failed, rate, target, passed),
                )


def _refresh_kpis(cur: Any, bulletin_id: int, week_start: date, week_end: date) -> None:
    cur.execute("DELETE FROM public.quality_bulletin_kpis WHERE bulletin_id=%s", (bulletin_id,))
    kpi_start, kpi_end = kpi_report_period(week_start, week_end)
    cur.execute(
        """
        SELECT
            SUM(inspected_count) AS inspected_count,
            SUM(failed_count) AS failed_count,
            CASE WHEN SUM(inspected_count) > 0
                 THEN SUM(failed_count) * 100.0 / SUM(inspected_count)
                 ELSE AVG(rate) END AS blocking_rate,
            MAX(target) AS target
        FROM public.bulletin_source_records
        WHERE is_active
          AND source_type='final'
          AND source_date BETWEEN %s AND %s
          AND LOWER(COALESCE(product_type, '')) LIKE '%%thường%%'
        """,
        (kpi_start, kpi_end),
    )
    blocking_row = cur.fetchone() or {}
    if isinstance(blocking_row, dict):
        blocking_rate = blocking_row.get("blocking_rate")
        blocking_target = blocking_row.get("target")
    else:
        _, _, blocking_rate, blocking_target = blocking_row
    blocking_status = (
        "good" if blocking_rate is not None and blocking_target is not None and blocking_rate <= blocking_target
        else "danger" if blocking_rate is not None and blocking_target is not None
        else "neutral"
    )
    cur.execute(
        """
        INSERT INTO public.quality_bulletin_kpis
            (bulletin_id, kpi_key, category, label, value_numeric, target_numeric, unit, status, source_url)
        VALUES (%s, 'blocking_rate', 'Hàng thường', 'Blocking rate', %s, %s, '%%', %s, %s)
        """,
        (
            bulletin_id,
            blocking_rate,
            blocking_target,
            blocking_status,
            spreadsheet_url(ENDLINE_FINAL_SHEET_ID, 280210348),
        ),
    )
    cur.execute(
        """
        SELECT COUNT(*) AS commitment_count
        FROM public.bulletin_source_records
        WHERE is_active
          AND source_type='final'
          AND source_date BETWEEN %s AND %s
          AND NULLIF(BTRIM(COALESCE(payload->>'ghi chu cam ket cl', '')), '') IS NOT NULL
        """,
        (kpi_start, kpi_end),
    )
    commitment_row = cur.fetchone() or {}
    commitment_count = commitment_row.get("commitment_count", 0) if isinstance(commitment_row, dict) else commitment_row[0]
    cur.execute(
        """
        INSERT INTO public.quality_bulletin_kpis
            (bulletin_id, kpi_key, category, label, value_numeric, target_numeric, unit, status, source_url)
        VALUES (%s, 'po_commitments', 'Hàng Veston', 'Cam kết về chất lượng trước khi xuất hàng', %s, NULL, 'lần', %s, %s)
        """,
        (
            bulletin_id,
            commitment_count,
            "good" if commitment_count == 0 else "neutral",
            spreadsheet_url(ENDLINE_FINAL_SHEET_ID, 280210348),
        ),
    )
    cur.execute(
        "SELECT COUNT(*) FROM public.bulletin_source_records WHERE source_type='complaint' AND source_date BETWEEN %s AND %s",
        (kpi_start, kpi_end),
    )
    complaint_row = cur.fetchone()
    complaint_count = complaint_row["count"] if isinstance(complaint_row, dict) else complaint_row[0]
    cur.execute(
        """
        INSERT INTO public.quality_bulletin_kpis
            (bulletin_id, kpi_key, category, label, value_numeric, target_numeric, unit, status, source_url)
        VALUES (%s, 'complaints', 'Khách hàng', 'Khiếu nại khách hàng', %s, 0, 'vụ', %s, %s)
        """,
        (bulletin_id, complaint_count, "good" if complaint_count == 0 else "danger", spreadsheet_url(PROBLEM_SHEET_ID, 1257874888)),
    )
    cur.execute(
        """
        SELECT
            COUNT(*) FILTER (WHERE LOWER(search_text) LIKE '%%gemba%%') AS gemba,
            COUNT(*) FILTER (WHERE LOWER(search_text) LIKE '%%doanh thu%%') AS revenue,
            COUNT(*) FILTER (WHERE LOWER(search_text) LIKE '%%lỗi e%%'
                              OR LOWER(search_text) LIKE '%%loi e%%') AS audit_e
        FROM (
            SELECT CONCAT_WS(' ', phan_loai_loi, mo_ta, task_name, ghi_chu) AS search_text
            FROM public.input_error
            WHERE ngay_ghi_nhan BETWEEN %s AND %s
              AND (
                  LOWER(COALESCE(phan_loai_loi,'')) LIKE '%%ảnh hưởng%%kpi%%'
                  OR LOWER(COALESCE(phan_loai_loi,'')) LIKE '%%anh huong%%kpi%%'
                  OR LOWER(CONCAT_WS(' ', mo_ta, task_name, ghi_chu)) LIKE '%%gemba%%'
                  OR LOWER(CONCAT_WS(' ', mo_ta, task_name, ghi_chu)) LIKE '%%doanh thu%%'
                  OR LOWER(CONCAT_WS(' ', mo_ta, task_name, ghi_chu)) LIKE '%%lỗi e%%'
                  OR LOWER(CONCAT_WS(' ', mo_ta, task_name, ghi_chu)) LIKE '%%loi e%%'
              )
        ) scoped_errors
        """,
        (kpi_start, kpi_end),
    )
    impact_row = cur.fetchone() or {}
    for key, label in (
        ("gemba", "KPI Gemba Control Plan"),
        ("revenue", "KPI doanh thu"),
        ("audit_e", "Lỗi E trong các cuộc đánh giá"),
    ):
        value = int((impact_row.get(key) if isinstance(impact_row, dict) else 0) or 0)
        cur.execute(
            """
            INSERT INTO public.quality_bulletin_kpis
                (bulletin_id, kpi_key, category, label, value_numeric, target_numeric, unit, status, source_url)
            VALUES (%s,%s,'Ảnh hưởng mục tiêu',%s,%s,0,'vấn đề',%s,%s)
            """,
            (bulletin_id, key, label, value, "good" if value == 0 else "warning", "/view-kpi#pane-errors"),
        )


def _date_text(value: Any) -> Optional[str]:
    if not value:
        return None
    return value.strftime("%d/%m/%Y") if hasattr(value, "strftime") else str(value)


def get_bulletin_payload(connection_factory: Callable[[], Any], bulletin_id: int) -> Dict[str, Any]:
    with connection_factory() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT * FROM public.quality_bulletins WHERE id=%s", (bulletin_id,))
            bulletin = cur.fetchone()
            if not bulletin:
                raise KeyError("Bulletin not found")
            cur.execute("SELECT * FROM public.quality_bulletin_items WHERE bulletin_id=%s ORDER BY deadline NULLS LAST, id", (bulletin_id,))
            items = cur.fetchall()
            cur.execute("SELECT * FROM public.quality_bulletin_entries WHERE bulletin_id=%s ORDER BY entry_type, sort_order, id", (bulletin_id,))
            entries = cur.fetchall()
            cur.execute("SELECT * FROM public.quality_bulletin_metrics WHERE bulletin_id=%s ORDER BY period_type, source_type, unit_name, product_type", (bulletin_id,))
            metrics = cur.fetchall()
            cur.execute("SELECT * FROM public.quality_bulletin_kpis WHERE bulletin_id=%s", (bulletin_id,))
            kpis = {row["kpi_key"]: dict(row) for row in cur.fetchall()}
    report = {
        "id": bulletin["id"], "week": bulletin["iso_week"], "year": bulletin["iso_year"],
        "from_date": _date_text(bulletin["week_start"]), "to_date": _date_text(bulletin["week_end"]),
        "updated_at": bulletin["updated_at"].strftime("%d/%m/%Y %H:%M"),
        "updated_by": bulletin["verified_by"] or bulletin.get("updated_by") or bulletin["created_by"] or "Hệ thống",
        "version": str(bulletin["version"]), "status": bulletin["status"],
    }
    complaint = kpis.get("complaints", {})
    qa_impacts = []
    for key in ("gemba", "revenue", "audit_e"):
        row = kpis.get(key, {})
        qa_impacts.append({"key": key, "label": row.get("label") or key, "value": float(row.get("value_numeric") or 0), "source_url": row.get("source_url")})
    payload_items = []
    for item in items:
        payload_items.append({
            "row_id": item["id"], "id": item["source_no"] or item["source_id"], "topic": item["topic"],
            "unit": item["unit_name"], "description": item["description"], "status": item["status"],
            "due_date": _date_text(item["deadline"]), "owner": item["owner_name"], "source_url": item["source_url"],
            "source_type": item["source_type"], "source_authoritative": item["status_origin"] == "source",
        })
    reminders = [{"id": row["id"], "task": row["title"], "content": row["content"], "due_date": _date_text(row["due_date"]), "assignee": row["assignee"], "status": row["status"]} for row in entries if row["entry_type"] == "reminder"]
    alerts = [{"id": row["id"], "title": row["title"], "content": row["content"], "level": row["level"]} for row in entries if row["entry_type"] == "quality_alert"]
    metric_payload = [{**dict(row), "rate": float(row["rate"]) if row["rate"] is not None else None, "target": float(row["target"]) if row["target"] is not None else None,
                       "inspected_count": float(row["inspected_count"]) if row["inspected_count"] is not None else None,
                       "failed_count": float(row["failed_count"]) if row["failed_count"] is not None else None,
                       "period_start": _date_text(row["period_start"]), "period_end": _date_text(row["period_end"]),
                       "created_at": None, "updated_at": None} for row in metrics]
    return {
        "report": report,
        "kpi": {
            "blocking_rate": {
                **dict(kpis.get("blocking_rate", {})),
                "label": "Blocking rate",
                "category": "Hàng thường",
                "value": float(kpis["blocking_rate"]["value_numeric"]) if kpis.get("blocking_rate", {}).get("value_numeric") is not None else None,
                "target": float(kpis["blocking_rate"]["target_numeric"]) if kpis.get("blocking_rate", {}).get("target_numeric") is not None else None,
                "target_operator": "<=",
                "unit": "%",
                "source_url": kpis.get("blocking_rate", {}).get("source_url"),
            },
            "po_commitments": {
                **dict(kpis.get("po_commitments", {})),
                "label": "Cam kết về chất lượng trước khi xuất hàng",
                "category": "Hàng Veston",
                "value": float(kpis["po_commitments"]["value_numeric"]) if kpis.get("po_commitments", {}).get("value_numeric") is not None else 0,
                "target": None,
                "target_operator": "",
                "unit": "lần",
                "source_url": kpis.get("po_commitments", {}).get("source_url"),
            },
            # Kept for older clients that still read the previous key.
            "veston_quality": {
                "label": "Cam kết về chất lượng trước khi xuất hàng",
                "category": "Hàng Veston",
                "value": float(kpis["po_commitments"]["value_numeric"]) if kpis.get("po_commitments", {}).get("value_numeric") is not None else 0,
                "unit": "lần",
                "source_url": kpis.get("po_commitments", {}).get("source_url"),
            },
            "complaints": {"label": "Khiếu nại khách hàng", "value": float(complaint.get("value_numeric") or 0), "causes": [], "source_url": complaint.get("source_url")},
            "qa_impacts": qa_impacts,
        },
        "issues": payload_items, "reminders": reminders, "quality_alerts": alerts,
        "metrics": metric_payload,
    }
