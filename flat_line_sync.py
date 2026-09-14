"""Google Sheets reader and parser for flat-line production plans."""
from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime
from pathlib import Path
from typing import Any

from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build


SHEETS_READONLY_SCOPE = "https://www.googleapis.com/auth/spreadsheets.readonly"


def text_key(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or "").strip())
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.replace("Đ", "D").replace("đ", "d").casefold()
    return re.sub(r"[^a-z0-9]+", "", text)


def parse_integer(value: Any) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return int(value)
    cleaned = re.sub(r"[^0-9.-]", "", str(value))
    try:
        return int(float(cleaned))
    except (TypeError, ValueError):
        return None


def parse_sheet_date(value: Any) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    for pattern in ("%d/%m/%Y", "%d/%m/%y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, pattern).date()
        except ValueError:
            continue
    return None


def parse_unit_and_teams(value: Any) -> tuple[int | None, list[str]]:
    text = str(value or "").strip()
    unit_match = re.search(r"\b(?:U|XN)\s*(\d+)\b", text, flags=re.IGNORECASE)
    unit_number = int(unit_match.group(1)) if unit_match else None
    line_match = re.search(r"\bL\s*(.*)$", text, flags=re.IGNORECASE)
    line_numbers = re.findall(r"\d+", line_match.group(1)) if line_match else []
    teams: list[str] = []
    for raw in line_numbers:
        team = f"Tổ {int(raw)}"
        if team not in teams:
            teams.append(team)
    return unit_number, teams


def fetch_sheet_values(
    credentials_file: Path,
    spreadsheet_id: str,
    worksheet: str,
    cell_range: str,
) -> list[list[Any]]:
    credentials = Credentials.from_service_account_file(
        str(credentials_file), scopes=[SHEETS_READONLY_SCOPE]
    )
    service = build("sheets", "v4", credentials=credentials, cache_discovery=False)
    safe_worksheet = worksheet.replace("'", "''")
    response = (
        service.spreadsheets()
        .values()
        .get(
            spreadsheetId=spreadsheet_id,
            range=f"'{safe_worksheet}'!{cell_range}",
            valueRenderOption="FORMATTED_VALUE",
            dateTimeRenderOption="FORMATTED_STRING",
        )
        .execute()
    )
    return response.get("values", [])


def parse_flat_line_plans(
    values: list[list[Any]],
    don_vi: str,
    expected_unit_number: int,
) -> tuple[list[dict[str, Any]], list[str], int]:
    """Parse rows whose `Loại chuyền` is `Chuyền bệt`.

    Returns valid plans, warnings, and the number of matching source rows.
    """
    if not values:
        raise ValueError("Sheet không có dữ liệu")
    headers = {text_key(value): index for index, value in enumerate(values[0])}
    required = {
        "mahang", "nhucaubatdau", "sanluongkh", "to", "loaihang",
        "loaichuyen", "ngayraichuyen", "khachhang",
    }
    missing = sorted(required - set(headers))
    if missing:
        raise ValueError(f"Sheet thiếu cột bắt buộc: {', '.join(missing)}")

    plans: list[dict[str, Any]] = []
    warnings: list[str] = []
    matched = 0
    seen_ids: set[str] = set()
    for sheet_row, raw_row in enumerate(values[1:], start=3):
        row = list(raw_row) + [""] * max(0, len(headers) - len(raw_row))

        def get(header: str) -> Any:
            index = headers[header]
            return row[index] if index < len(row) else ""

        if text_key(get("loaichuyen")) != "chuyenbet":
            continue
        matched += 1
        demand = str(get("nhucaubatdau") or "").strip()
        ma_hang = str(get("mahang") or "").strip()
        loai_hang = str(get("loaihang") or "").strip()
        customer = str(get("khachhang") or "").strip()
        production_date = parse_sheet_date(get("ngayraichuyen"))
        quantity = parse_integer(get("sanluongkh"))
        unit_number, teams = parse_unit_and_teams(get("to"))
        source_record_id = f"{don_vi}:{demand}" if demand else ""

        errors: list[str] = []
        if not demand:
            errors.append("thiếu Nhu cầu bắt đầu")
        if not ma_hang:
            errors.append("thiếu Mã hàng")
        if not loai_hang:
            errors.append("thiếu Loại hàng")
        if not production_date:
            errors.append("Ngày rải chuyền không hợp lệ")
        if quantity is None:
            errors.append("Sản lượng KH không hợp lệ")
        if unit_number != expected_unit_number:
            errors.append(f"Tổ không thuộc U{expected_unit_number}")
        if not teams:
            errors.append("không tách được tổ/line")
        if source_record_id in seen_ids:
            errors.append("trùng Nhu cầu bắt đầu")
        if errors:
            warnings.append(f"Dòng {sheet_row}: {', '.join(errors)}")
            continue

        seen_ids.add(source_record_id)
        plans.append({
            "source_record_id": source_record_id,
            "ke_hoach": demand,
            "don_vi": don_vi,
            "bo_phan": teams,
            "khach_hang": customer,
            "ma_hang": ma_hang,
            "loai_hang": loai_hang,
            "ngay_rc": production_date,
            "san_luong": quantity,
            "sheet_row": sheet_row,
        })
    return plans, warnings, matched
