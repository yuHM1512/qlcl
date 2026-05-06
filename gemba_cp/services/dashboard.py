from __future__ import annotations

from collections.abc import Iterable
from datetime import date, datetime, timedelta

from sqlalchemy import Select, extract, func, select
from sqlalchemy.orm import Session

from gemba_cp.models.database import GembaCPRecordORM
from gemba_cp.schemas.dashboard import (
    FilterOption,
    KpiCard,
    MetaResponse,
    OverviewResponse,
    RecordRow,
    RecordsResponse,
    UnitMetric,
)

GEMBA_CONTROL_PLAN_AUDIT_TYPE = "GEMBA CONTROL PLAN"


def format_percent(value: float, decimals: int = 1) -> str:
    return f"{value * 100:.{decimals}f}%"


def build_base_query(
    year: int | None = None,
    month: int | None = None,
    unit: str | None = None,
) -> Select[tuple[GembaCPRecordORM]]:
    stmt = select(GembaCPRecordORM).where(
        func.upper(func.coalesce(GembaCPRecordORM.audit_type, "")) == GEMBA_CONTROL_PLAN_AUDIT_TYPE
    )
    if year:
        stmt = stmt.where(extract("year", GembaCPRecordORM.kpi_month) == year)
    if month:
        stmt = stmt.where(extract("month", GembaCPRecordORM.kpi_month) == month)
    if unit:
        stmt = stmt.where(GembaCPRecordORM.issue_department == unit)
    return stmt


def compute_ncr_ratio(records: Iterable[GembaCPRecordORM]) -> float:
    rows = list(records)
    numerator = sum(1 for row in rows if row.has_issue)
    denominator = sum(row.score_value or 0 for row in rows)
    if denominator <= 0:
        return 0.0
    return numerator / denominator


def compute_on_time_ratio(records: Iterable[GembaCPRecordORM]) -> float:
    rows = [row for row in records if (row.gb_time or "").strip()]
    if not rows:
        return 0.0
    on_time = sum(1 for row in rows if row.is_on_time)
    return on_time / len(rows)


def compute_cap_completion_ratio(records: Iterable[GembaCPRecordORM]) -> float:
    done = 0
    open_items = 0
    for row in records:
        if row.issue_status_group == "done":
            done += 1
        elif row.issue_status_group in {"doing", "todo"}:
            open_items += 1
    denominator = done + open_items
    if denominator == 0:
        return 1.0
    return done / denominator


def build_unit_metric(unit: str, actual: float, target: float, count_records: int) -> UnitMetric:
    return UnitMetric(
        unit=unit,
        actual=actual,
        actual_label=format_percent(actual),
        target=target,
        target_label=format_percent(target),
        count_records=count_records,
    )


def get_recent_ncr_ratio(db: Session, unit: str | None = None) -> float:
    since_date = date.today() - timedelta(days=28)
    recent_records = db.execute(
        build_base_query(unit=unit)
        .where(GembaCPRecordORM.evaluation_date.is_not(None))
        .where(GembaCPRecordORM.evaluation_date >= since_date)
        .order_by(GembaCPRecordORM.evaluation_date.asc())
    ).scalars().all()
    return compute_ncr_ratio(recent_records)


def get_meta(db: Session) -> MetaResponse:
    month_expr = func.to_char(GembaCPRecordORM.kpi_month, "MM").label("month_key")
    year_expr = extract("year", GembaCPRecordORM.kpi_month).label("year_key")

    month_rows = db.execute(
        select(month_expr)
        .where(func.upper(func.coalesce(GembaCPRecordORM.audit_type, "")) == GEMBA_CONTROL_PLAN_AUDIT_TYPE)
        .where(GembaCPRecordORM.kpi_month.is_not(None))
        .distinct()
        .order_by(month_expr.desc())
    ).scalars()
    year_rows = db.execute(
        select(year_expr)
        .where(func.upper(func.coalesce(GembaCPRecordORM.audit_type, "")) == GEMBA_CONTROL_PLAN_AUDIT_TYPE)
        .where(GembaCPRecordORM.kpi_month.is_not(None))
        .distinct()
        .order_by(year_expr.desc())
    ).scalars()
    unit_rows = db.execute(
        select(GembaCPRecordORM.issue_department)
        .where(func.upper(func.coalesce(GembaCPRecordORM.audit_type, "")) == GEMBA_CONTROL_PLAN_AUDIT_TYPE)
        .where(GembaCPRecordORM.issue_department.is_not(None))
        .distinct()
        .order_by(GembaCPRecordORM.issue_department.asc())
    ).scalars()
    last_synced_at = db.execute(
        select(func.max(GembaCPRecordORM.synced_at)).where(
            func.upper(func.coalesce(GembaCPRecordORM.audit_type, "")) == GEMBA_CONTROL_PLAN_AUDIT_TYPE
        )
    ).scalar_one_or_none()
    total_records = db.execute(select(func.count()).select_from(build_base_query().subquery())).scalar_one()

    months = [FilterOption(value=str(int(value)), label=f"Tháng {int(value)}") for value in month_rows if value]
    years = [FilterOption(value=str(int(value)), label=str(int(value))) for value in year_rows if value]
    units = [FilterOption(value=value, label=value) for value in unit_rows if value]
    return MetaResponse(
        months=months,
        years=years,
        units=units,
        last_synced_at=last_synced_at,
        total_records=total_records,
    )


def group_records(
    records: list[GembaCPRecordORM],
    dimension: str,
) -> list[tuple[str, list[GembaCPRecordORM]]]:
    grouped: dict[str, list[GembaCPRecordORM]] = {}
    for row in records:
        if dimension == "month":
            if row.kpi_month is None:
                continue
            key = row.kpi_month.strftime("%Y-%m")
        else:
            key = (row.issue_department or "").strip()
            if not key:
                continue
        grouped.setdefault(key, []).append(row)
    return sorted(grouped.items(), key=lambda item: item[0])


def get_overview(
    db: Session,
    dimension: str = "unit",
    year: int | None = None,
    month: int | None = None,
    unit: str | None = None,
) -> OverviewResponse:
    records = db.execute(
        build_base_query(year=year, month=month, unit=unit).order_by(GembaCPRecordORM.evaluation_date.asc())
    ).scalars().all()

    ncr_ratio = compute_ncr_ratio(records)
    recent_ncr_ratio = get_recent_ncr_ratio(db, unit=unit)
    on_time_ratio = compute_on_time_ratio(records)
    cap_completion_ratio = compute_cap_completion_ratio(records)
    cards = [
        KpiCard(
            key="ncr_ratio_4w",
            label="Tỉ lệ NCR - YTD (4 tuần gần nhất)",
            value=recent_ncr_ratio,
            formatted_value=format_percent(recent_ncr_ratio, 2),
            target=0.05,
            target_label="5%",
            tone="green",
        ),
        KpiCard(
            key="ncr_ratio",
            label="Tỉ lệ Gemba Plan không đạt (NCR)",
            value=ncr_ratio,
            formatted_value=format_percent(ncr_ratio, 2),
            target=0.05,
            target_label="5%",
            tone="green",
        ),
        KpiCard(
            key="on_time_ratio",
            label="Tỉ lệ thực hiện Gemba đúng kế hoạch",
            value=on_time_ratio,
            formatted_value=format_percent(on_time_ratio),
            target=1.0,
            target_label="100%",
            tone="red",
        ),
        KpiCard(
            key="cap_completion_ratio",
            label="Tỉ lệ hoàn thành HĐKP",
            value=cap_completion_ratio,
            formatted_value=format_percent(cap_completion_ratio),
            target=1.0,
            target_label="100%",
            tone="green",
        ),
    ]

    grouped = group_records(records, dimension=dimension)
    ncr_by_unit = [build_unit_metric(group_name, compute_ncr_ratio(rows), 0.05, len(rows)) for group_name, rows in grouped]
    on_time_by_unit = [build_unit_metric(group_name, compute_on_time_ratio(rows), 1.0, len(rows)) for group_name, rows in grouped]
    cap_by_unit = [build_unit_metric(group_name, compute_cap_completion_ratio(rows), 1.0, len(rows)) for group_name, rows in grouped]

    return OverviewResponse(
        cards=cards,
        ncr_by_unit=ncr_by_unit,
        on_time_by_unit=on_time_by_unit,
        cap_completion_by_unit=cap_by_unit,
    )


def get_records(
    db: Session,
    year: int | None = None,
    month: int | None = None,
    unit: str | None = None,
    limit: int = 20,
) -> RecordsResponse:
    limit = max(1, min(limit, 100))
    stmt = build_base_query(year=year, month=month, unit=unit).order_by(
        GembaCPRecordORM.evaluation_date.desc().nullslast(),
        GembaCPRecordORM.audit_no.desc().nullslast(),
    )
    rows = db.execute(stmt.limit(limit)).scalars().all()
    total = db.execute(
        select(func.count()).select_from(build_base_query(year=year, month=month, unit=unit).subquery())
    ).scalar_one()

    return RecordsResponse(
        rows=[
            RecordRow(
                record_id=row.record_id,
                audit_no=row.audit_no,
                evaluation_date=row.evaluation_date.isoformat() if row.evaluation_date else None,
                dashboard_unit=row.dashboard_unit,
                principle_axis=row.principle_axis,
                issue_text=row.issue_text,
                score_value=row.score_value,
                gb_time=row.gb_time,
                issue_status_raw=row.issue_status_raw,
            )
            for row in rows
        ],
        total=total,
    )
