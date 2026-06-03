from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import delete
from sqlalchemy.orm import Session

from gemba_cp.config import get_settings
from gemba_cp.models.database import GembaCPRecordORM, GembaPlanRecordORM
from gemba_cp.models.plan_sheet_row import GembaPlanRecordInput
from gemba_cp.models.sheet_row import GembaCPRecordInput
from gemba_cp.services.google_sheets import fetch_sheet_values


@dataclass
class SyncResult:
    inserted_gemba_cp: int
    inserted_plan: int
    synced_at: datetime


def sanitize_headers(headers: list[str]) -> list[str]:
    seen: dict[str, int] = {}
    sanitized: list[str] = []
    for index, header in enumerate(headers):
        raw = (header or "").strip()
        base = raw if raw else f"unnamed_{index}"
        count = seen.get(base, 0)
        seen[base] = count + 1
        sanitized.append(base if count == 0 else f"{base}_{count + 1}")
    return sanitized


def values_to_dicts(values: list[list[str]]) -> list[dict[str, str]]:
    if not values:
        return []
    headers = sanitize_headers(values[0])
    rows: list[dict[str, str]] = []
    for raw_row in values[1:]:
        row = {header: (raw_row[idx] if idx < len(raw_row) else "") for idx, header in enumerate(headers)}
        rows.append(row)
    return rows


def map_row_to_orm(record: GembaCPRecordInput, synced_at: datetime) -> GembaCPRecordORM:
    settings = get_settings()
    return GembaCPRecordORM(
        record_id=record.record_id,
        audit_no=record.audit_no,
        submitted_at=record.submitted_at,
        submitted_by=record.submitted_by,
        evaluation_date=record.evaluation_date,
        auditors_csv=", ".join(record.auditors) if record.auditors else None,
        audit_unit=record.audit_unit,
        audit_location=record.audit_location,
        issue_department=record.issue_department,
        audit_type=record.audit_type,
        principle_axis=record.principle_axis,
        point_name=record.point_name,
        standard_text=record.standard_text,
        result_level=record.result_level,
        issue_text=record.issue_text,
        owner_department=record.owner_department,
        issue_status_raw=record.issue_status,
        issue_status_group=record.issue_status_group,
        auditor_confirmation=record.auditor_confirmation,
        batch_year=record.batch_year,
        kpi_month=record.kpi_month,
        period=record.period,
        score_value=record.score_value,
        plan_name=record.plan_name,
        product_code=record.product_code,
        gb_time=record.gb_time,
        week_label=record.week_label,
        week_code=record.week_code,
        area_split=record.area_split,
        dashboard_unit=record.dashboard_unit,
        has_issue=record.has_issue,
        is_on_time=record.is_on_time,
        source_sheet=settings.google_sheets_worksheet,
        synced_at=synced_at,
    )


def map_plan_row_to_orm(record: GembaPlanRecordInput, synced_at: datetime) -> GembaPlanRecordORM:
    settings = get_settings()
    return GembaPlanRecordORM(
        record_id=record.record_id,
        plan_no=record.plan_no,
        plan_name=record.plan_name,
        unit_name=record.unit_name,
        gemba_date=record.gemba_date,
        submitted_at=record.submitted_at,
        submitted_date=record.submitted_date,
        submitted_month=record.submitted_month,
        is_recreated_plan=record.is_recreated_plan,
        is_created_on_time=record.is_created_on_time,
        source_sheet=settings.google_plan_worksheet,
        synced_at=synced_at,
    )


def sync_sheet_to_database(db: Session) -> SyncResult:
    synced_at = datetime.utcnow().replace(microsecond=0)
    settings = get_settings()

    gemba_cp_rows = values_to_dicts(fetch_sheet_values(settings.google_sheets_worksheet, settings.sheet_range))
    parsed_gemba_cp: list[GembaCPRecordORM] = []
    for row in gemba_cp_rows:
        record_id = (row.get("id") or "").strip()
        if not record_id:
            continue
        parsed_record = GembaCPRecordInput.model_validate(row)
        parsed_gemba_cp.append(map_row_to_orm(parsed_record, synced_at))

    plan_rows = values_to_dicts(fetch_sheet_values(settings.google_plan_worksheet, settings.plan_sheet_range))
    parsed_plan: list[GembaPlanRecordORM] = []
    for row in plan_rows:
        record_id = (row.get("ID") or "").strip()
        if not record_id:
            continue
        parsed_record = GembaPlanRecordInput.model_validate(row)
        parsed_plan.append(map_plan_row_to_orm(parsed_record, synced_at))

    db.execute(delete(GembaCPRecordORM))
    db.execute(delete(GembaPlanRecordORM))
    if parsed_gemba_cp:
        db.add_all(parsed_gemba_cp)
    if parsed_plan:
        db.add_all(parsed_plan)
    db.commit()
    return SyncResult(
        inserted_gemba_cp=len(parsed_gemba_cp),
        inserted_plan=len(parsed_plan),
        synced_at=synced_at,
    )
