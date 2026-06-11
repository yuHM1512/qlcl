from __future__ import annotations

from collections.abc import Iterable
from datetime import date, timedelta

from sqlalchemy import Select, extract, func, select
from sqlalchemy.orm import Session

from gemba_cp.models.database import GembaCPRecordORM, GembaPlanRecordORM
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


def build_plan_query(
    year: int | None = None,
    month: int | None = None,
    unit: str | None = None,
) -> Select[tuple[GembaPlanRecordORM]]:
    stmt = select(GembaPlanRecordORM)
    if year:
        stmt = stmt.where(extract("year", GembaPlanRecordORM.submitted_month) == year)
    if month:
        stmt = stmt.where(extract("month", GembaPlanRecordORM.submitted_month) == month)
    if unit:
        stmt = stmt.where(GembaPlanRecordORM.unit_name == unit)
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


def build_on_time_tooltip(records: Iterable[GembaCPRecordORM]) -> str | None:
    late_rows = [row for row in records if (row.gb_time or "").strip() and not row.is_on_time]
    if not late_rows:
        return None

    unit_counts: dict[str, int] = {}
    for row in late_rows:
        unit = (row.issue_department or row.dashboard_unit or "").strip() or "Chưa xác định"
        unit_counts[unit] = unit_counts.get(unit, 0) + 1

    sorted_units = sorted(unit_counts.items(), key=lambda item: (-item[1], item[0]))
    details = "\n".join(f"- {unit} ({count})" for unit, count in sorted_units)
    return f"Chưa đạt 100% do các đơn vị:\n{details}"


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


def compute_plan_submission_on_time_ratio(records: Iterable[GembaPlanRecordORM]) -> float:
    eligible_rows = [row for row in records if not row.is_recreated_plan and row.submitted_date is not None]
    if not eligible_rows:
        return 0.0
    on_time = sum(1 for row in eligible_rows if row.is_created_on_time)
    return on_time / len(eligible_rows)


def has_cap_completion_data(records: Iterable[GembaCPRecordORM]) -> bool:
    for row in records:
        if row.has_issue and row.issue_status_group in {"done", "doing", "todo"}:
            return True
    return False


def build_unit_metric(unit: str, actual: float, target: float, count_records: int) -> UnitMetric:
    return UnitMetric(
        unit=unit,
        actual=actual,
        actual_label=format_percent(actual),
        target=target,
        target_label=format_percent(target),
        count_records=count_records,
    )


def filter_recent_records(records: Iterable[GembaCPRecordORM]) -> list[GembaCPRecordORM]:
    since_date = date.today() - timedelta(days=28)
    return [row for row in records if row.evaluation_date is not None and row.evaluation_date >= since_date]


def get_meta(db: Session) -> MetaResponse:
    month_expr = func.to_char(GembaCPRecordORM.kpi_month, "MM").label("month_key")
    year_expr = extract("year", GembaCPRecordORM.kpi_month).label("year_key")
    plan_month_expr = func.to_char(GembaPlanRecordORM.submitted_month, "MM").label("plan_month_key")
    plan_year_expr = extract("year", GembaPlanRecordORM.submitted_month).label("plan_year_key")

    month_rows = list(
        db.execute(
            select(month_expr)
            .where(func.upper(func.coalesce(GembaCPRecordORM.audit_type, "")) == GEMBA_CONTROL_PLAN_AUDIT_TYPE)
            .where(GembaCPRecordORM.kpi_month.is_not(None))
            .distinct()
            .order_by(month_expr.desc())
        ).scalars()
    )
    plan_month_rows = list(
        db.execute(
            select(plan_month_expr)
            .where(GembaPlanRecordORM.submitted_month.is_not(None))
            .distinct()
            .order_by(plan_month_expr.desc())
        ).scalars()
    )
    year_rows = list(
        db.execute(
            select(year_expr)
            .where(func.upper(func.coalesce(GembaCPRecordORM.audit_type, "")) == GEMBA_CONTROL_PLAN_AUDIT_TYPE)
            .where(GembaCPRecordORM.kpi_month.is_not(None))
            .distinct()
            .order_by(year_expr.desc())
        ).scalars()
    )
    plan_year_rows = list(
        db.execute(
            select(plan_year_expr)
            .where(GembaPlanRecordORM.submitted_month.is_not(None))
            .distinct()
            .order_by(plan_year_expr.desc())
        ).scalars()
    )
    unit_rows = list(
        db.execute(
            select(GembaCPRecordORM.issue_department)
            .where(func.upper(func.coalesce(GembaCPRecordORM.audit_type, "")) == GEMBA_CONTROL_PLAN_AUDIT_TYPE)
            .where(GembaCPRecordORM.issue_department.is_not(None))
            .distinct()
            .order_by(GembaCPRecordORM.issue_department.asc())
        ).scalars()
    )
    plan_unit_rows = list(
        db.execute(
            select(GembaPlanRecordORM.unit_name)
            .where(GembaPlanRecordORM.unit_name.is_not(None))
            .distinct()
            .order_by(GembaPlanRecordORM.unit_name.asc())
        ).scalars()
    )
    gemba_last_synced_at = db.execute(select(func.max(GembaCPRecordORM.synced_at))).scalar_one_or_none()
    plan_last_synced_at = db.execute(select(func.max(GembaPlanRecordORM.synced_at))).scalar_one_or_none()
    last_synced_at = max(
        [value for value in (gemba_last_synced_at, plan_last_synced_at) if value is not None],
        default=None,
    )
    total_records = db.execute(select(func.count()).select_from(build_base_query().subquery())).scalar_one()

    month_values = sorted({int(value) for value in month_rows + plan_month_rows if value}, reverse=True)
    year_values = sorted({int(value) for value in year_rows + plan_year_rows if value}, reverse=True)
    unit_values = sorted({value for value in unit_rows + plan_unit_rows if value})

    months = [FilterOption(value=str(value), label=f"Tháng {value}") for value in month_values]
    years = [FilterOption(value=str(value), label=str(value)) for value in year_values]
    units = [FilterOption(value=value, label=value) for value in unit_values]
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


def group_plan_records(
    records: list[GembaPlanRecordORM],
    dimension: str,
) -> list[tuple[str, list[GembaPlanRecordORM]]]:
    grouped: dict[str, list[GembaPlanRecordORM]] = {}
    for row in records:
        if dimension == "month":
            if row.submitted_month is None:
                continue
            key = row.submitted_month.strftime("%Y-%m")
        else:
            key = (row.unit_name or "").strip()
            if not key:
                continue
        grouped.setdefault(key, []).append(row)
    return sorted(grouped.items(), key=lambda item: item[0])


def get_overview(
    db: Session,
    dimension: str = "unit",
    scope: str = "recent",
    year: int | None = None,
    month: int | None = None,
    unit: str | None = None,
) -> OverviewResponse:
    all_records = db.execute(
        build_base_query(year=year, month=month, unit=unit).order_by(GembaCPRecordORM.evaluation_date.asc())
    ).scalars().all()
    plan_records = db.execute(
        build_plan_query(year=year, month=month, unit=unit).order_by(GembaPlanRecordORM.submitted_date.asc())
    ).scalars().all()

    records = filter_recent_records(all_records) if scope == "recent" else all_records
    ncr_ratio = compute_ncr_ratio(records)
    on_time_ratio = compute_on_time_ratio(records)
    on_time_tooltip = build_on_time_tooltip(records) if on_time_ratio < 1.0 else None
    cap_completion_ratio = compute_cap_completion_ratio(records)
    label_suffix = "(4 tuần gần nhất)" if scope == "recent" else "(Tất cả)"
    cards = [
        KpiCard(
            key="ncr_ratio",
            label=f"Tỷ lệ Gemba Plan không đạt (NCR) {label_suffix}",
            value=ncr_ratio,
            formatted_value=format_percent(ncr_ratio, 2),
            target=0.05,
            target_label="5%",
            tone="green",
        ),
        KpiCard(
            key="on_time_ratio",
            label=f"Tỷ lệ thực hiện Gemba đúng kế hoạch {label_suffix}",
            value=on_time_ratio,
            formatted_value=format_percent(on_time_ratio),
            target=1.0,
            target_label="100%",
            tone="red",
            tooltip=on_time_tooltip,
        ),
        KpiCard(
            key="cap_completion_ratio",
            label=f"Tỷ lệ hoàn thành HĐKP {label_suffix}",
            value=cap_completion_ratio,
            formatted_value=format_percent(cap_completion_ratio),
            target=1.0,
            target_label="100%",
            tone="green",
        ),
    ]

    grouped = group_records(all_records, dimension=dimension)
    grouped_plan = group_plan_records(plan_records, dimension=dimension)
    ncr_by_unit = [build_unit_metric(group_name, compute_ncr_ratio(rows), 0.05, len(rows)) for group_name, rows in grouped]
    on_time_by_unit = [build_unit_metric(group_name, compute_on_time_ratio(rows), 1.0, len(rows)) for group_name, rows in grouped]
    cap_by_unit = [
        build_unit_metric(group_name, compute_cap_completion_ratio(rows), 1.0, len(rows))
        for group_name, rows in grouped
        if has_cap_completion_data(rows)
    ]
    plan_submission_on_time_by_unit = [
        build_unit_metric(
            group_name,
            compute_plan_submission_on_time_ratio(rows),
            1.0,
            sum(1 for row in rows if not row.is_recreated_plan and row.submitted_date is not None),
        )
        for group_name, rows in grouped_plan
        if any(not row.is_recreated_plan and row.submitted_date is not None for row in rows)
    ]

    return OverviewResponse(
        cards=cards,
        ncr_by_unit=ncr_by_unit,
        on_time_by_unit=on_time_by_unit,
        cap_completion_by_unit=cap_by_unit,
        plan_submission_on_time_by_unit=plan_submission_on_time_by_unit,
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
