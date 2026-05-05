from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


NO_ISSUE_TEXT = "Không có vấn đề cần giải quyết, trong đợt Gemba Walk control plan này"
DONE_STATUS_VALUES = {"Hoàn thành", "Đóng CAP"}
DOING_STATUS_VALUES = {"Đang thực hiện"}
TODO_STATUS_VALUES = {"Chưa thực hiện"}
ON_TIME_VALUE = "Đúng hạn"

DATE_FORMATS = ("%d/%m/%Y", "%m/%d/%Y")
KPI_MONTH_FORMATS = ("%m/%d/%Y", "%d/%m/%Y")
DATETIME_FORMATS = (
    "%d/%m/%Y %H:%M:%S",
    "%d/%m/%Y %H:%M",
    "%m/%d/%Y %H:%M:%S",
    "%m/%d/%Y %H:%M",
)


def clean_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, str):
        normalized = " ".join(value.replace("\r", "\n").split())
        return normalized or None
    return value


def clean_multiline_value(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).replace("\r\n", "\n").replace("\r", "\n").strip()
    return text or None


def parse_date(value: Any) -> date | None:
    value = clean_value(value)
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(str(value), fmt).date()
        except ValueError:
            continue
    return None


def parse_kpi_month_date(value: Any) -> date | None:
    value = clean_value(value)
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    for fmt in KPI_MONTH_FORMATS:
        try:
            return datetime.strptime(str(value), fmt).date()
        except ValueError:
            continue
    return None


def parse_datetime(value: Any) -> datetime | None:
    value = clean_value(value)
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    for fmt in DATETIME_FORMATS:
        try:
            return datetime.strptime(str(value), fmt)
        except ValueError:
            continue
    return None


def parse_int(value: Any) -> int | None:
    value = clean_value(value)
    if value is None:
        return None
    try:
        return int(float(str(value).replace(",", "").strip()))
    except ValueError:
        return None


def parse_auditors(value: Any) -> list[str]:
    value = clean_multiline_value(value)
    if value is None:
        return []
    return [part.strip() for part in value.split(",") if part.strip()]


def normalize_issue_status(status: str | None) -> str | None:
    if not status:
        return None
    if status in DONE_STATUS_VALUES:
        return "done"
    if status in DOING_STATUS_VALUES:
        return "doing"
    if status in TODO_STATUS_VALUES:
        return "todo"
    return "other"


def derive_dashboard_unit(area_split: str | None, issue_department: str | None, audit_location: str | None, audit_unit: str | None) -> str | None:
    for value in (area_split, issue_department, audit_location, audit_unit):
        value = clean_value(value)
        if value:
            return str(value)
    return None


class GembaCPRecordInput(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    record_id: str = Field(alias="id")
    audit_no: str | None = Field(default=None, alias="no")
    submitted_at: datetime | None = Field(default=None, alias="time")
    submitted_by: str | None = Field(default=None, alias="Họ và tên người nhập")
    evaluation_date: date | None = Field(default=None, alias="Ngày đánh giá")
    auditors: list[str] = Field(default_factory=list, alias="Tên đánh giá viên")
    audit_unit: str | None = Field(default=None, alias="Đơn vị đánh giá")
    audit_location: str | None = Field(default=None, alias="Địa điểm đánh giá")
    issue_department: str | None = Field(default=None, alias="Đơn vị phát sinh lỗi")
    audit_type: str | None = Field(default=None, alias="Loại đánh giá")
    principle_axis: str | None = Field(default=None, alias="Trục/ Chương/ Nguyên tắc")
    point_name: str | None = Field(default=None, alias="Điểm")
    standard_text: str | None = Field(default=None, alias="Tiêu chuẩn")
    result_level: str | None = Field(default=None, alias="Level")
    issue_text: str | None = Field(default=None, alias="Lỗi")
    owner_department: str | None = Field(default=None, alias="Đơn vị chủ trì giải quyết")
    issue_status: str | None = Field(default=None, alias="Tình trạng")
    auditor_confirmation: str | None = Field(default=None, alias="Đánh giá viên xác nhận")
    batch_year: str | None = Field(default=None, alias="Đợt")
    kpi_month: date | None = Field(default=None, alias="kpi_month")
    period: str | None = Field(default=None, alias="period")
    score_value: int | None = Field(default=None, alias="Số điểm đánh giá")
    plan_name: str | None = Field(default=None, alias="Kế hoạch")
    product_code: str | None = Field(default=None, alias="Mã hàng")
    gb_time: str | None = Field(default=None, alias="Thời gian GB")
    week_label: str | None = Field(default=None, alias="Tuần")
    week_code: str | None = Field(default=None, alias="Tuần STT")
    area_split: str | None = Field(default=None, alias="Tách khu vực")

    @field_validator(
        "record_id",
        "audit_no",
        "submitted_by",
        "audit_unit",
        "audit_location",
        "issue_department",
        "audit_type",
        "principle_axis",
        "batch_year",
        "period",
        "plan_name",
        "product_code",
        "gb_time",
        "week_label",
        "week_code",
        "area_split",
        "result_level",
        "issue_status",
        "auditor_confirmation",
        mode="before",
    )
    @classmethod
    def normalize_text(cls, value: Any) -> Any:
        return clean_value(value)

    @field_validator("point_name", "standard_text", "issue_text", mode="before")
    @classmethod
    def normalize_multiline_text(cls, value: Any) -> str | None:
        return clean_multiline_value(value)

    @field_validator("submitted_at", mode="before")
    @classmethod
    def normalize_submitted_at(cls, value: Any) -> datetime | None:
        return parse_datetime(value)

    @field_validator("evaluation_date", mode="before")
    @classmethod
    def normalize_date_fields(cls, value: Any) -> date | None:
        return parse_date(value)

    @field_validator("kpi_month", mode="before")
    @classmethod
    def normalize_kpi_month(cls, value: Any) -> date | None:
        return parse_kpi_month_date(value)

    @field_validator("score_value", mode="before")
    @classmethod
    def normalize_score(cls, value: Any) -> int | None:
        return parse_int(value)

    @field_validator("auditors", mode="before")
    @classmethod
    def normalize_auditors(cls, value: Any) -> list[str]:
        return parse_auditors(value)

    @property
    def has_issue(self) -> bool:
        issue_text = clean_value(self.issue_text)
        return bool(issue_text and issue_text != NO_ISSUE_TEXT)

    @property
    def is_on_time(self) -> bool:
        return self.gb_time == ON_TIME_VALUE

    @property
    def issue_status_group(self) -> str | None:
        return normalize_issue_status(self.issue_status)

    @property
    def dashboard_unit(self) -> str | None:
        return derive_dashboard_unit(
            area_split=self.area_split,
            issue_department=self.issue_department,
            audit_location=self.audit_location,
            audit_unit=self.audit_unit,
        )
