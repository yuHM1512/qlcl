from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = Field(default="Gemba CP Dashboard", alias="GEMBA_CP_APP_NAME")
    database_url: str = Field(
        default="postgresql+psycopg://postgres:postgres@localhost:5432/gemba_cp",
        alias="GEMBA_CP_DATABASE_URL",
    )
    google_sheets_spreadsheet_id: str = Field(
        default="1mqnn7_xXdo0rY7zEjZm2T9KHQpsRfeCxsS6fitkQlns",
        alias="GEMBA_CP_GOOGLE_SHEETS_SPREADSHEET_ID",
    )
    google_sheets_worksheet: str = Field(default="GEMBACP", alias="GEMBA_CP_GOOGLE_SHEETS_WORKSHEET")
    google_service_account_file: str = Field(
        default="gemba_cp/templates/credentials_m29.json",
        alias="GEMBA_CP_GOOGLE_SERVICE_ACCOUNT_FILE",
    )
    google_sheets_range: str | None = Field(default=None, alias="GEMBA_CP_GOOGLE_SHEETS_RANGE")
    google_plan_worksheet: str = Field(default="0.1 KẾ HOẠCH GEMBA", alias="GEMBA_CP_GOOGLE_PLAN_WORKSHEET")
    google_plan_range: str | None = Field(default=None, alias="GEMBA_CP_GOOGLE_PLAN_RANGE")

    @property
    def credentials_path(self) -> Path:
        path = Path(self.google_service_account_file)
        if path.is_absolute():
            return path
        return BASE_DIR / path

    @property
    def sheet_range(self) -> str:
        return self.build_sheet_range(self.google_sheets_worksheet, self.google_sheets_range)

    @property
    def plan_sheet_range(self) -> str:
        return self.build_sheet_range(self.google_plan_worksheet, self.google_plan_range)

    @staticmethod
    def build_sheet_range(worksheet: str, explicit_range: str | None) -> str:
        if explicit_range:
            return explicit_range
        safe_worksheet = worksheet.replace("'", "''")
        return f"'{safe_worksheet}'!A:AZ"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
