"""Bản tin chất lượng (quality bulletin) — xem, đồng bộ, nhập/sửa mục, xác nhận.

Tách từ main.py. Hàm/biến dùng chung (DB, đăng nhập, phân quyền, template, cấu hình...) vẫn ở main.py
và được gọi qua `core.<tên>` lúc chạy, nên test patch `main.<tên>` vẫn có hiệu lực.
"""
import psycopg2
import psycopg2.extras
import psycopg2.pool
from bulletin_sync import ensure_weekly_draft, get_bulletin_payload, parse_date as parse_bulletin_date
from datetime import date, timedelta
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from typing import Any, Dict, Optional

from app_core import core

router = APIRouter()


@router.get("/quality-bulletin")
def quality_bulletin(request: Request):
    user_data = core.get_authenticated_user(request)
    if not user_data:
        return RedirectResponse(url="/login?next=/quality-bulletin", status_code=303)
    return core.templates.TemplateResponse(
        "quality_bulletin.html",
        {"request": request, "user": user_data},
    )


def _bulletin_user_label(user: Dict[str, Any]) -> str:
    return (user.get("name") or user.get("ma_nv") or "Người dùng").strip()


def _require_draft_bulletin(cur: Any, bulletin_id: int) -> Dict[str, Any]:
    cur.execute("SELECT * FROM public.quality_bulletins WHERE id=%s FOR UPDATE", (bulletin_id,))
    row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Không tìm thấy bản tin")
    bulletin = dict(row) if isinstance(row, dict) else {"id": row[0], "status": row[5]}
    if bulletin.get("status") != "draft":
        raise HTTPException(status_code=409, detail="Bản tin đã verify và được khóa")
    return bulletin


@router.get("/api/bulletin/current")
def bulletin_current(request: Request, as_of: Optional[str] = Query(default=None)):
    user = core.require_authenticated_api_user(request)
    as_of_date = parse_bulletin_date(as_of) if as_of else date.today()
    if as_of and not as_of_date:
        raise HTTPException(status_code=422, detail="as_of phải có dạng YYYY-MM-DD")
    bulletin = ensure_weekly_draft(
        core.get_db_connection,
        as_of=as_of_date,
        created_by=user.get("ma_nv") or "system",
    )
    return get_bulletin_payload(core.get_db_connection, bulletin["id"])


@router.get("/api/bulletin/by-period")
def bulletin_by_period(request: Request, year: int = Query(..., ge=2000, le=2200), week: int = Query(..., ge=1, le=53)):
    user = core.require_authenticated_api_user(request)
    try:
        week_start = date.fromisocalendar(year, week, 1)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Năm/tuần ISO không hợp lệ") from exc
    bulletin = ensure_weekly_draft(
        core.get_db_connection,
        as_of=week_start + timedelta(days=7),
        created_by=user.get("ma_nv") or "system",
    )
    return get_bulletin_payload(core.get_db_connection, bulletin["id"])


@router.get("/api/bulletin/by-id/{bulletin_id}")
def bulletin_by_id(bulletin_id: int, request: Request):
    core.require_authenticated_api_user(request)
    try:
        return get_bulletin_payload(core.get_db_connection, bulletin_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Không tìm thấy bản tin") from exc


@router.get("/api/bulletin/history")
def bulletin_history(request: Request, limit: int = Query(default=12, ge=1, le=52)):
    core.require_authenticated_api_user(request)
    with core.get_db_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT id, week_start, week_end, iso_year, iso_week, status, version,
                       created_by, verified_by, verified_at, saved_at, updated_at
                FROM public.quality_bulletins
                WHERE saved_at IS NOT NULL OR status = 'verified'
                ORDER BY week_start DESC LIMIT %s
                """,
                (limit,),
            )
            rows = cur.fetchall()
    return [
        {
            **dict(row),
            "week_start": row["week_start"].isoformat(),
            "week_end": row["week_end"].isoformat(),
            "verified_at": row["verified_at"].isoformat() if row["verified_at"] else None,
            "saved_at": row["saved_at"].isoformat() if row["saved_at"] else None,
            "updated_at": row["updated_at"].isoformat(),
        }
        for row in rows
    ]


@router.post("/api/bulletin/sync")
def bulletin_sync_now(request: Request):
    user = core.require_authenticated_api_user(request)
    try:
        result = core.run_bulletin_sync(
            triggered_by=user.get("ma_nv") or "manual",
            trigger_type="manual",
        )
        return {"status": "success", **result}
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Đồng bộ bản tin thất bại: {exc}") from exc


@router.get("/api/bulletin/sync/status")
def bulletin_sync_status(request: Request):
    core.require_authenticated_api_user(request)
    return dict(core._bulletin_sync_state)


@router.patch("/api/bulletin/items/{item_id}")
async def bulletin_update_item(item_id: int, request: Request):
    user = core.require_authenticated_api_user(request)
    payload = await request.json()
    allowed_statuses = {"Chưa tiếp nhận", "Đang thực hiện", "Chờ xác nhận", "Hoàn thành"}
    requested_status = str(payload.get("status") or "").strip() or None
    if requested_status and requested_status not in allowed_statuses:
        raise HTTPException(status_code=422, detail="Trạng thái không hợp lệ")
    deadline_provided = "deadline" in payload
    deadline = None
    if payload.get("deadline"):
        deadline = parse_bulletin_date(payload["deadline"])
        if not deadline:
            raise HTTPException(status_code=422, detail="Thời hạn không hợp lệ")
    with core.get_db_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT * FROM public.quality_bulletin_items WHERE id=%s FOR UPDATE", (item_id,))
            item = cur.fetchone()
            if not item:
                raise HTTPException(status_code=404, detail="Không tìm thấy vấn đề")
            _require_draft_bulletin(cur, item["bulletin_id"])
            if item["status_origin"] == "source" and requested_status:
                raise HTTPException(
                    status_code=409,
                    detail="Trạng thái được đồng bộ từ Google Sheets; chỉ cập nhật thời hạn hoặc người theo dõi tại đây",
                )
            cur.execute(
                """
                UPDATE public.quality_bulletin_items
                SET status=COALESCE(%s,status),
                    deadline=CASE WHEN %s THEN %s ELSE deadline END,
                    owner_ma_nv=%s, owner_name=%s, updated_at=NOW()
                WHERE id=%s
                RETURNING id
                """,
                (
                    requested_status,
                    deadline_provided,
                    deadline,
                    user.get("ma_nv"),
                    _bulletin_user_label(user),
                    item_id,
                ),
            )
            cur.execute(
                "UPDATE public.quality_bulletins SET updated_at=NOW(), updated_by=%s WHERE id=%s",
                (_bulletin_user_label(user), item["bulletin_id"]),
            )
        conn.commit()
    return {"status": "updated", "item_id": item_id}


@router.post("/api/bulletin/entries")
async def bulletin_create_entry(request: Request):
    user = core.require_authenticated_api_user(request)
    payload = await request.json()
    bulletin_id = int(payload.get("bulletin_id") or 0)
    entry_type = str(payload.get("entry_type") or "").strip()
    title = str(payload.get("title") or "").strip()
    if entry_type not in {"reminder", "quality_alert"} or not title:
        raise HTTPException(status_code=422, detail="Thiếu loại hoặc tiêu đề nội dung")
    due_date = parse_bulletin_date(payload.get("due_date")) if payload.get("due_date") else None
    level = str(payload.get("level") or "warning")
    if level not in {"info", "warning", "critical"}:
        raise HTTPException(status_code=422, detail="Mức cảnh báo không hợp lệ")
    with core.get_db_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            _require_draft_bulletin(cur, bulletin_id)
            cur.execute(
                """
                INSERT INTO public.quality_bulletin_entries
                    (bulletin_id, entry_type, title, content, due_date, assignee, level, status, created_by)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id
                """,
                (
                    bulletin_id, entry_type, title, str(payload.get("content") or "").strip() or None,
                    due_date, str(payload.get("assignee") or "").strip() or None, level,
                    str(payload.get("status") or "").strip() or None, user.get("ma_nv"),
                ),
            )
            entry_id = cur.fetchone()["id"]
            cur.execute(
                "UPDATE public.quality_bulletins SET updated_at=NOW(), updated_by=%s WHERE id=%s",
                (_bulletin_user_label(user), bulletin_id),
            )
        conn.commit()
    return {"status": "created", "entry_id": entry_id}


@router.patch("/api/bulletin/entries/{entry_id}")
async def bulletin_update_entry(entry_id: int, request: Request):
    user = core.require_authenticated_api_user(request)
    payload = await request.json()
    with core.get_db_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT * FROM public.quality_bulletin_entries WHERE id=%s FOR UPDATE", (entry_id,))
            entry = cur.fetchone()
            if not entry:
                raise HTTPException(status_code=404, detail="Không tìm thấy nội dung")
            _require_draft_bulletin(cur, entry["bulletin_id"])
            due_date = entry["due_date"]
            if "due_date" in payload:
                due_date = parse_bulletin_date(payload.get("due_date")) if payload.get("due_date") else None
            level = str(payload.get("level", entry["level"]))
            if level not in {"info", "warning", "critical"}:
                raise HTTPException(status_code=422, detail="Mức cảnh báo không hợp lệ")
            cur.execute(
                """
                UPDATE public.quality_bulletin_entries SET
                    title=%s, content=%s, due_date=%s, assignee=%s,
                    level=%s, status=%s, updated_at=NOW()
                WHERE id=%s
                """,
                (
                    str(payload.get("title", entry["title"]) or "").strip(),
                    str(payload.get("content", entry["content"] or "") or "").strip() or None,
                    due_date,
                    str(payload.get("assignee", entry["assignee"] or "") or "").strip() or None,
                    level,
                    str(payload.get("status", entry["status"] or "") or "").strip() or None,
                    entry_id,
                ),
            )
            cur.execute(
                "UPDATE public.quality_bulletins SET updated_at=NOW(), updated_by=%s WHERE id=%s",
                (_bulletin_user_label(user), entry["bulletin_id"]),
            )
        conn.commit()
    return {"status": "updated", "entry_id": entry_id}


@router.delete("/api/bulletin/entries/{entry_id}")
def bulletin_delete_entry(entry_id: int, request: Request):
    user = core.require_authenticated_api_user(request)
    with core.get_db_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT bulletin_id FROM public.quality_bulletin_entries WHERE id=%s FOR UPDATE", (entry_id,))
            entry = cur.fetchone()
            if not entry:
                raise HTTPException(status_code=404, detail="Không tìm thấy nội dung")
            _require_draft_bulletin(cur, entry["bulletin_id"])
            cur.execute("DELETE FROM public.quality_bulletin_entries WHERE id=%s", (entry_id,))
            cur.execute(
                "UPDATE public.quality_bulletins SET updated_at=NOW(), updated_by=%s WHERE id=%s",
                (_bulletin_user_label(user), entry["bulletin_id"]),
            )
        conn.commit()
    return {"status": "deleted"}


@router.post("/api/bulletin/{bulletin_id}/verify")
def bulletin_verify(bulletin_id: int, request: Request):
    user = core.require_authenticated_api_user(request)
    with core.get_db_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            _require_draft_bulletin(cur, bulletin_id)
            cur.execute(
                """
                UPDATE public.quality_bulletins
                SET status='verified', verified_by=%s, verified_at=NOW(), saved_at=COALESCE(saved_at, NOW()), updated_at=NOW(), updated_by=%s
                WHERE id=%s
                """,
                (_bulletin_user_label(user), _bulletin_user_label(user), bulletin_id),
            )
        conn.commit()
    return {"status": "verified", "bulletin_id": bulletin_id}


@router.post("/api/bulletin/{bulletin_id}/save")
def bulletin_save(bulletin_id: int, request: Request):
    user = core.require_authenticated_api_user(request)
    with core.get_db_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            _require_draft_bulletin(cur, bulletin_id)
            cur.execute(
                """
                UPDATE public.quality_bulletins
                SET saved_at=COALESCE(saved_at, NOW()), updated_at=NOW(), updated_by=%s
                WHERE id=%s
                RETURNING id, saved_at
                """,
                (_bulletin_user_label(user), bulletin_id),
            )
            saved = cur.fetchone()
        conn.commit()
    return {"status": "saved", "bulletin_id": bulletin_id, "saved_at": saved["saved_at"].isoformat() if saved else None}
