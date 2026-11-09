"""Routes for the Quality Index dashboard and RPM detail pages."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from quality_index_sync import fetch_quality_index, fetch_rpm_detail

logger = logging.getLogger(__name__)


def register(
    app,
    get_authenticated_user: Callable,
    redirect_to_login: Callable,
    templates: Jinja2Templates,
    credentials_path_fn: Callable[[], Path],
):
    router = APIRouter()

    # ── Page routes ──

    @router.get("/quality-index")
    def quality_index_page(request: Request):
        user = get_authenticated_user(request)
        if not user:
            return redirect_to_login(request)
        return templates.TemplateResponse(
            "quality_index.html",
            {"request": request, "user": user},
        )

    @router.get("/quality-index/rpm-detail")
    def rpm_detail_page(request: Request):
        user = get_authenticated_user(request)
        if not user:
            return redirect_to_login(request)
        return templates.TemplateResponse(
            "rpm_detail.html",
            {"request": request, "user": user},
        )

    # ── API routes ──

    @router.get("/api/quality-index")
    def api_quality_index(
        request: Request,
        year: Optional[int] = Query(None),
    ):
        cred_path = credentials_path_fn()
        if not cred_path.is_file():
            raise HTTPException(500, "Chưa cấu hình Google service account")
        try:
            data = fetch_quality_index(cred_path, year=year)
            return data
        except Exception as e:
            logger.error("fetch_quality_index error: %s", e, exc_info=True)
            raise HTTPException(500, f"Lỗi lấy dữ liệu Quality Index: {e}")

    @router.get("/api/quality-index/rpm-detail")
    def api_rpm_detail(
        request: Request,
        year: Optional[int] = Query(None),
        month: Optional[int] = Query(None),
        ma_hang: Optional[str] = Query(None),
    ):
        cred_path = credentials_path_fn()
        if not cred_path.is_file():
            raise HTTPException(500, "Chưa cấu hình Google service account")
        try:
            data = fetch_rpm_detail(cred_path, year=year, month=month, ma_hang=ma_hang)
            return data
        except Exception as e:
            logger.error("fetch_rpm_detail error: %s", e, exc_info=True)
            raise HTTPException(500, f"Lỗi lấy dữ liệu RPM: {e}")

    app.include_router(router)
