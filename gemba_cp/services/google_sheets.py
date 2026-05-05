from __future__ import annotations

from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

from gemba_cp.config import get_settings


SCOPES = ("https://www.googleapis.com/auth/spreadsheets.readonly",)


def build_sheets_service():
    settings = get_settings()
    credentials = Credentials.from_service_account_file(
        str(settings.credentials_path),
        scopes=SCOPES,
    )
    return build("sheets", "v4", credentials=credentials, cache_discovery=False)


def fetch_sheet_values() -> list[list[str]]:
    settings = get_settings()
    service = build_sheets_service()
    response = (
        service.spreadsheets()
        .values()
        .get(
            spreadsheetId=settings.google_sheets_spreadsheet_id,
            range=settings.sheet_range,
        )
        .execute()
    )
    return response.get("values", [])
