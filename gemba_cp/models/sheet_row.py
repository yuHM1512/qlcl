from __future__ import annotations

import unicodedata
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


NO_ISSUE_TEXT = "KHONG CO VAN DE CAN GIAI QUYET, TRONG DOT GEMBA WALK CONTROL PLAN NAY"
NO_ISSUE_POINT_NAME = "KHONG CO VAN DE"
DONE_STATUS_VALUES = {
    "Ho\u00e0n th\u00e0nh",
    "\u0110\u00f3ng CAP",
    "Ho\u00c3\u00a0n th\u00c3\u00a0nh",
    "\u00c4\u0090\u00c3\u00b3ng CAP",
}
DOING_STATUS_VALUES = {
    "\u0110ang th\u1ef1c hi\u1ec7n",
    "\u0110ang th\u1ef1c hi\u1ec7n".replace("\u0110", "\u00c4\u0090"),
}
TODO_STATUS_VALUES = {
    "Ch\u01b0a th\u1ef1c hi\u1ec7n",
    "Ch\u00c6\u00b0a th\u00e1\u00bb\u00b1c hi\u00e1\u00bb\u2021n",
}
ON_TIME_VALUE = "\u0110\u00fang h\u1ea1n"

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


def normalize_compare_text(value: Any) -> str:
    value = clean_value(value)
    if not value:
        return ""
    normalized = "".join(
        ch for ch in unicodedata.normalize("NFKD", str(value))
        if not unicodedata.combining(ch)
    )
    normalized = normalized.replace("\u0110", "D").replace("\u0111", "d")
    return " ".join(normalized.upper().split())


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


def derive_dashboard_unit(
    area_split: str | None,
    issue_department: str | None,
    audit_location: str | None,
    audit_unit: str | None,
) -> str | None:
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
    submitted_by: str | None = Field(default=None, alias="H\u1ecd v\u00e0 t\u00ean ng\u01b0\u1eddi nh\u1eadp")
    evaluation_date: date | None = Field(default=None, alias="Ng\u00e0y \u0111\u00e1nh gi\u00e1")
    auditors: list[str] = Field(default_factory=list, alias="T\u00ean \u0111\u00e1nh gi\u00e1 vi\u00ean")
    audit_unit: str | None = Field(default=None, alias="\u0110\u01a1n v\u1ecb \u0111\u00e1nh gi\u00e1")
    audit_location: str | None = Field(default=None, alias="\u0110\u1ecba \u0111i\u1ec3m \u0111\u00e1nh gi\u00e1")
    issue_department: str | None = Field(default=None, alias="\u0110\u01a1n v\u1ecb ph\u00e1t sinh l\u1ed7i")
    audit_type: str | None = Field(default=None, alias="Lo\u1ea1i \u0111\u00e1nh gi\u00e1")
    principle_axis: str | None = Field(default=None, alias="Tr\u1ee5c/ Ch\u01b0\u01a1ng/ Nguy\u00ean t\u1eafc")
    point_name: str | None = Field(default=None, alias="\u0110i\u1ec3m")
    standard_text: str | None = Field(default=None, alias="Ti\u00eau chu\u1ea9n")
    result_level: str | None = Field(default=None, alias="Level")
    issue_text: str | None = Field(default=None, alias="L\u1ed7i")
    owner_department: str | None = Field(default=None, alias="\u0110\u01a1n v\u1ecb ch\u1ee7 tr\u00ec gi\u1ea3i quy\u1ebft")
    issue_status: str | None = Field(default=None, alias="T\u00ecnh tr\u1ea1ng")
    auditor_confirmation: str | None = Field(default=None, alias="\u0110\u00e1nh gi\u00e1 vi\u00ean x\u00e1c nh\u1eadn")
    batch_year: str | None = Field(default=None, alias="\u0110\u1ee3t")
    kpi_month: date | None = Field(default=None, alias="kpi_month")
    period: str | None = Field(default=None, alias="period")
    score_value: int | None = Field(default=None, alias="S\u1ed1 \u0111i\u1ec3m \u0111\u00e1nh gi\u00e1")
    plan_name: str | None = Field(default=None, alias="K\u1ebf ho\u1ea1ch")
    product_code: str | None = Field(default=None, alias="M\u00e3 h\u00e0ng")
    gb_time: str | None = Field(default=None, alias="Th\u1eddi gian GB")
    week_label: str | None = Field(default=None, alias="Tu\u1ea7n")
    week_code: str | None = Field(default=None, alias="Tu\u1ea7n STT")
    area_split: str | None = Field(default=None, alias="T\u00e1ch khu v\u1ef1c")

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
        point_name = normalize_compare_text(self.point_name)
        issue_text = normalize_compare_text(self.issue_text)

        if point_name == NO_ISSUE_POINT_NAME:
            return False
        if issue_text == NO_ISSUE_TEXT:
            return False
        return True

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
