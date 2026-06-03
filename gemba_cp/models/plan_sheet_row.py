from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from gemba_cp.models.sheet_row import clean_value, parse_date, parse_datetime


def parse_bool(value: Any) -> bool:
    value = clean_value(value)
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    return str(value).strip().upper() == "TRUE"


def parse_plan_timestamp(value: Any) -> datetime | None:
    dt_value = parse_datetime(value)
    if dt_value is not None:
        return dt_value
    date_value = parse_date(value)
    if date_value is not None:
        return datetime.combine(date_value, datetime.min.time())
    return None


class GembaPlanRecordInput(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    record_id: str = Field(alias="ID")
    plan_no: str | None = Field(default=None, alias="no")
    plan_name: str | None = Field(default=None, alias="Kế hoạch")
    unit_name: str | None = Field(default=None, alias="Đơn vị")
    gemba_date: date | None = Field(default=None, alias="Ngày gemba")
    submitted_at: datetime | None = Field(default=None, alias="timestamp")
    is_recreated_plan: bool = Field(default=False, alias="Kế hoạch tạo lại")

    @field_validator("record_id", "plan_no", "plan_name", "unit_name", mode="before")
    @classmethod
    def normalize_text(cls, value: Any) -> Any:
        return clean_value(value)

    @field_validator("gemba_date", mode="before")
    @classmethod
    def normalize_gemba_date(cls, value: Any) -> date | None:
        return parse_date(value)

    @field_validator("submitted_at", mode="before")
    @classmethod
    def normalize_submitted_at(cls, value: Any) -> datetime | None:
        return parse_plan_timestamp(value)

    @field_validator("is_recreated_plan", mode="before")
    @classmethod
    def normalize_recreated_flag(cls, value: Any) -> bool:
        return parse_bool(value)

    @property
    def submitted_date(self) -> date | None:
        return self.submitted_at.date() if self.submitted_at else None

    @property
    def submitted_month(self) -> date | None:
        submitted_date = self.submitted_date
        if submitted_date is None:
            return None
        return submitted_date.replace(day=1)

    @property
    def is_created_on_time(self) -> bool:
        submitted_date = self.submitted_date
        if submitted_date is None or self.is_recreated_plan:
            return False
        return 1 < submitted_date.day <= 5
