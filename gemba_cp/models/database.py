from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from gemba_cp.db import Base


class GembaCPRecordORM(Base):
    __tablename__ = "gemba_cp_records"

    record_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    audit_no: Mapped[str | None] = mapped_column(String(64), index=True)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), index=True)
    submitted_by: Mapped[str | None] = mapped_column(String(255))
    evaluation_date: Mapped[date | None] = mapped_column(Date, index=True)
    auditors_csv: Mapped[str | None] = mapped_column(Text)
    audit_unit: Mapped[str | None] = mapped_column(String(255))
    audit_location: Mapped[str | None] = mapped_column(String(255))
    issue_department: Mapped[str | None] = mapped_column(String(255), index=True)
    audit_type: Mapped[str | None] = mapped_column(String(255))
    principle_axis: Mapped[str | None] = mapped_column(String(255))
    point_name: Mapped[str | None] = mapped_column(Text)
    standard_text: Mapped[str | None] = mapped_column(Text)
    result_level: Mapped[str | None] = mapped_column(String(255))
    issue_text: Mapped[str | None] = mapped_column(Text)
    owner_department: Mapped[str | None] = mapped_column(String(255))
    issue_status_raw: Mapped[str | None] = mapped_column(String(255))
    issue_status_group: Mapped[str | None] = mapped_column(String(32), index=True)
    auditor_confirmation: Mapped[str | None] = mapped_column(String(255))
    batch_year: Mapped[str | None] = mapped_column(String(64))
    kpi_month: Mapped[date | None] = mapped_column(Date, index=True)
    period: Mapped[str | None] = mapped_column(String(255))
    score_value: Mapped[int | None] = mapped_column(Integer)
    plan_name: Mapped[str | None] = mapped_column(String(255))
    product_code: Mapped[str | None] = mapped_column(String(255))
    gb_time: Mapped[str | None] = mapped_column(String(255), index=True)
    week_label: Mapped[str | None] = mapped_column(String(64))
    week_code: Mapped[str | None] = mapped_column(String(64), index=True)
    area_split: Mapped[str | None] = mapped_column(String(255), index=True)
    dashboard_unit: Mapped[str | None] = mapped_column(String(255), index=True)
    has_issue: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    is_on_time: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    source_sheet: Mapped[str] = mapped_column(String(128), default="GEMBACP", nullable=False)
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False, index=True)


class GembaPlanRecordORM(Base):
    __tablename__ = "gemba_plan_records"

    record_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    plan_no: Mapped[str | None] = mapped_column(String(64), index=True)
    plan_name: Mapped[str | None] = mapped_column(String(255))
    unit_name: Mapped[str | None] = mapped_column(String(255), index=True)
    gemba_date: Mapped[date | None] = mapped_column(Date, index=True)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), index=True)
    submitted_date: Mapped[date | None] = mapped_column(Date, index=True)
    submitted_month: Mapped[date | None] = mapped_column(Date, index=True)
    is_recreated_plan: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    is_created_on_time: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    source_sheet: Mapped[str] = mapped_column(String(128), default="0.1 KẾ HOẠCH GEMBA", nullable=False)
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False, index=True)
