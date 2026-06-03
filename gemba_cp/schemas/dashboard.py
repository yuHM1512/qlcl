from datetime import datetime

from pydantic import BaseModel


class FilterOption(BaseModel):
    value: str
    label: str


class MetaResponse(BaseModel):
    months: list[FilterOption]
    years: list[FilterOption]
    units: list[FilterOption]
    last_synced_at: datetime | None
    total_records: int


class KpiCard(BaseModel):
    key: str
    label: str
    value: float
    formatted_value: str
    target: float
    target_label: str
    tone: str


class UnitMetric(BaseModel):
    unit: str
    actual: float
    actual_label: str
    target: float
    target_label: str
    count_records: int


class RecordRow(BaseModel):
    record_id: str
    audit_no: str | None
    evaluation_date: str | None
    dashboard_unit: str | None
    principle_axis: str | None
    issue_text: str | None
    score_value: int | None
    gb_time: str | None
    issue_status_raw: str | None


class OverviewResponse(BaseModel):
    cards: list[KpiCard]
    ncr_by_unit: list[UnitMetric]
    on_time_by_unit: list[UnitMetric]
    cap_completion_by_unit: list[UnitMetric]
    plan_submission_on_time_by_unit: list[UnitMetric]


class RecordsResponse(BaseModel):
    rows: list[RecordRow]
    total: int
