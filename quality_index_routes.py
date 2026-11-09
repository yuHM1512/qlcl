"""Routes for the Quality Index dashboard and RPM detail pages."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from quality_index_sync import (
    fetch_quality_index,
    fetch_rpm_detail,
    get_cache_status,
    get_cached_quality_index,
    get_cached_rpm_detail,
    sync_all,
    sync_quality_index,
    sync_rpm_detail,
    start_auto_sync,
)

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

    # ── API routes (serve from cache, fallback to live fetch) ──

    @router.get("/api/quality-index")
    def api_quality_index(
        request: Request,
        year: Optional[int] = Query(None),
    ):
        cached = get_cached_quality_index(year)
        if cached:
            return cached
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
        cached = get_cached_rpm_detail(year, month, ma_hang)
        if cached:
            return cached
        cred_path = credentials_path_fn()
        if not cred_path.is_file():
            raise HTTPException(500, "Chưa cấu hình Google service account")
        try:
            data = fetch_rpm_detail(cred_path, year=year, month=month, ma_hang=ma_hang)
            return data
        except Exception as e:
            logger.error("fetch_rpm_detail error: %s", e, exc_info=True)
            raise HTTPException(500, f"Lỗi lấy dữ liệu RPM: {e}")

    # ── Sync endpoints ──

    @router.post("/api/quality-index/sync")
    def api_sync_all(request: Request):
        user = get_authenticated_user(request)
        if not user:
            raise HTTPException(401, "Unauthorized")
        cred_path = credentials_path_fn()
        if not cred_path.is_file():
            raise HTTPException(500, "Chưa cấu hình Google service account")
        try:
            result = sync_all(cred_path)
            return {"ok": True, **result}
        except Exception as e:
            logger.error("sync_all error: %s", e, exc_info=True)
            raise HTTPException(500, f"Lỗi đồng bộ: {e}")

    @router.get("/api/quality-index/sync-status")
    def api_sync_status(request: Request):
        return get_cache_status()

    app.include_router(router)

    # Start background auto-sync threads
    cred_path = credentials_path_fn()
    if cred_path.is_file():
        start_auto_sync(cred_path)
    else:
        logger.warning("Quality Index auto-sync skipped — credentials file not found")
