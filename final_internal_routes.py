"""Final nội bộ — danh sách kiểm Final, HĐKP Final, đồng bộ từ API Final.

Tách từ main.py. Hàm/biến dùng chung (DB, đăng nhập, phân quyền, template, cấu hình...) vẫn ở main.py
và được gọi qua `core.<tên>` lúc chạy, nên test patch `main.<tên>` vẫn có hiệu lực.
"""
import psycopg2
import psycopg2.extras
import psycopg2.pool
import threading
from datetime import date
from fastapi import APIRouter, HTTPException, Path, Query, Request
from fastapi.responses import RedirectResponse
from typing import Any, List, Optional, Tuple

from app_core import core

router = APIRouter()


@router.get("/final-noi-bo")
def final_internal_page(request: Request):
    user = core.get_authenticated_user(request)
    if not user:
        return core.redirect_to_login_for_current_path(request)
    return core.templates.TemplateResponse(
        "final_internal.html",
        {
            "request": request,
            "user": user,
            "can_sync": core.can_manage_final_sync(user),
            "api_configured": core.final_qa_sync_is_configured(),
            "source_base_url": core.FINAL_QA_API_BASE_URL,
            "factory_scope": core.get_final_factory_scope(user),
        },
    )


def _final_internal_where(
    date_from: Optional[str],
    date_to: Optional[str],
    factory: Optional[str],
    result: Optional[str],
    cap_status: Optional[str],
    search: Optional[str],
    factory_scope: Optional[str] = None,
) -> Tuple[str, List[Any]]:
    clauses = ["1=1"]
    params: List[Any] = []
    if date_from:
        clauses.append("fi.qa_check_date >= %s::date")
        params.append(date_from)
    if date_to:
        clauses.append("fi.qa_check_date <= %s::date")
        params.append(date_to)
    if factory_scope:
        clauses.append("fi.factory = %s")
        params.append(factory_scope)
    elif factory:
        clauses.append("fi.factory = %s")
        params.append(factory)
    if result:
        clauses.append("fi.final_status_code = %s")
        params.append(result)
    if cap_status == "not_required":
        clauses.append("fi.cap_required = FALSE")
    elif cap_status == "missing":
        clauses.append("fi.cap_required = TRUE AND fh.id IS NULL")
    elif cap_status == "draft":
        clauses.append("fi.cap_required = TRUE AND fh.id IS NOT NULL AND fh.completed_at IS NULL")
    elif cap_status == "completed":
        clauses.append("fi.cap_required = TRUE AND fh.completed_at IS NOT NULL")
    if search:
        clauses.append(
            "(fi.po_code ILIKE %s OR fi.product_id ILIKE %s OR fi.inspector_name ILIKE %s)"
        )
        term = f"%{search.strip()}%"
        params.extend([term, term, term])
    return " AND ".join(clauses), params


@router.get("/api/final-internal")
def api_final_internal_list(
    request: Request,
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    factory: Optional[str] = Query(None),
    result: Optional[str] = Query(None, pattern="^(0|1|2|3)?$"),
    cap_status: Optional[str] = Query(None, pattern="^(not_required|missing|draft|completed)?$"),
    search: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    user = core.require_authenticated_api_user(request)
    factory_scope = core.get_final_factory_scope(user)
    where_sql, params = _final_internal_where(
        date_from, date_to, factory, result, cap_status, search, factory_scope
    )
    offset = (page - 1) * page_size
    with core.get_db_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                f"""
                SELECT COUNT(*) AS total,
                       COUNT(*) FILTER (WHERE fi.final_status_code = '1') AS pass_count,
                       COUNT(*) FILTER (WHERE fi.final_status_code = '2') AS pass2_count,
                       COUNT(*) FILTER (WHERE fi.final_status_code = '0') AS fail_count,
                       COUNT(*) FILTER (
                           WHERE fi.cap_required = TRUE
                             AND fh.completed_at IS NULL
                       ) AS cap_pending_count
                FROM public.qa_final_inspection fi
                LEFT JOIN public.qa_final_hdkp fh ON fh.inspection_id = fi.id
                WHERE {where_sql}
                """,
                tuple(params),
            )
            summary = dict(cur.fetchone() or {})
            cur.execute(
                f"""
                SELECT fi.*,
                       fh.pdf_url AS cap_form,
                       CASE
                           WHEN fi.cap_required = FALSE THEN 'not_required'
                           WHEN fh.id IS NULL THEN 'missing'
                           WHEN fh.completed_at IS NOT NULL THEN 'completed'
                           WHEN EXISTS (
                               SELECT 1 FROM public.qa_final_hdkp_mota cm WHERE cm.hdkp_id = fh.id
                           ) THEN 'draft'
                           ELSE 'missing'
                       END AS cap_status,
                       COALESCE((
                           SELECT jsonb_agg(
                               jsonb_build_object(
                                   'id', fd.id,
                                   'error_code', fd.error_code,
                                   'error_name', fd.error_name,
                                   'amount', fd.amount,
                                   'description', fd.description,
                                   'level', fd.level
                               ) ORDER BY fd.id
                           )
                           FROM public.qa_final_defect fd
                           WHERE fd.inspection_id = fi.id
                       ), '[]'::jsonb) AS defects
                FROM public.qa_final_inspection fi
                LEFT JOIN public.qa_final_hdkp fh ON fh.inspection_id = fi.id
                WHERE {where_sql}
                ORDER BY fi.qa_check_date DESC NULLS LAST,
                         fi.source_created_at DESC NULLS LAST,
                         fi.id DESC
                LIMIT %s OFFSET %s
                """,
                tuple(params + [page_size, offset]),
            )
            rows = [dict(row) for row in cur.fetchall()]
            cur.execute(
                """
                SELECT id, started_at, finished_at, status, plans_scanned,
                       delegates_scanned, inspections_upserted, error_message
                FROM public.qa_final_sync_run
                ORDER BY id DESC LIMIT 1
                """
            )
            last_sync = cur.fetchone()
    total = int(summary.get("total") or 0)
    return {
        "rows": rows,
        "summary": summary,
        "paging": {
            "page": page,
            "page_size": page_size,
            "total": total,
            "total_pages": max(1, (total + page_size - 1) // page_size),
        },
        "last_sync": dict(last_sync) if last_sync else None,
        "sync_state": dict(core._final_sync_state),
    }


@router.get("/api/final-internal/hdkp/{inspection_id}")
def api_get_final_internal_hdkp(inspection_id: int = Path(...), request: Request = None):
    """Read the dedicated HĐKP record for an internal Final inspection."""
    user = core.require_authenticated_api_user(request)
    with core.get_db_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT factory FROM public.qa_final_inspection WHERE id = %s", (inspection_id,))
            inspection = cur.fetchone()
            if not inspection:
                raise HTTPException(status_code=404, detail="Không tìm thấy lần kiểm Final")
            core.require_final_cap_access(user, factory=inspection.get("factory"))
            cur.execute("SELECT id FROM public.qa_final_hdkp WHERE inspection_id = %s", (inspection_id,))
            hdkp = cur.fetchone()
            if not hdkp:
                return {"mota": None, "kehoach": [], "chitiet": []}
            hdkp_id = hdkp["id"]
            cur.execute("SELECT * FROM public.qa_final_hdkp_mota WHERE hdkp_id = %s", (hdkp_id,))
            mota = cur.fetchone()
            cur.execute("SELECT * FROM public.qa_final_hdkp_kehoach WHERE hdkp_id = %s ORDER BY section, thu_tu", (hdkp_id,))
            kehoach = cur.fetchall()
            cur.execute("SELECT * FROM public.qa_final_hdkp_chitiet WHERE hdkp_id = %s ORDER BY thu_tu", (hdkp_id,))
            chitiet = cur.fetchall()
    return {"mota": dict(mota) if mota else None, "kehoach": [dict(r) for r in kehoach], "chitiet": [dict(r) for r in chitiet]}


@router.get("/final-internal/hdkp-form/{inspection_id}")
def final_internal_hdkp_form_page(inspection_id: int = Path(...), request: Request = None):
    user = core.get_authenticated_user(request) if request else None
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    with core.get_db_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT * FROM public.qa_final_inspection WHERE id = %s", (inspection_id,))
            inspection = cur.fetchone()
            if not inspection:
                raise HTTPException(status_code=404, detail="Không tìm thấy lần kiểm Final")
            core.require_final_cap_access(user, factory=inspection.get("factory"))
            if str(inspection.get("final_status_code") or "") != "0":
                raise HTTPException(status_code=400, detail="Chỉ kết quả FAIL mới cần HĐKP 10.1")
            cur.execute(
                """
                INSERT INTO public.qa_final_hdkp (inspection_id, created_by)
                VALUES (%s, %s)
                ON CONFLICT (inspection_id) DO NOTHING
                """,
                (inspection_id, user["ma_nv"]),
            )
            conn.commit()
    error_row = {
        "id": inspection_id,
        "ma_nv": user.get("ma_nv"),
        "ngay_ghi_nhan": inspection.get("qa_check_date"),
        "task_name": "Kiểm pre-final/ Final nội bộ",
        "phan_loai_loi": inspection.get("final_status_display"),
        "mo_ta": f"Final nội bộ FAIL - PO {inspection.get('po_code')}, Iman {inspection.get('product_id')}",
        "huong_giai_quyet": "Làm HĐKP 10.1",
    }
    return core.templates.TemplateResponse("hdkp_form.html", {
        "request": request, "error": error_row, "error_id": inspection_id,
        "return_url": "/final-noi-bo",
        "api_base": f"/api/final-internal/hdkp/{inspection_id}",
        "form_title": "HĐKP Final nội bộ",
    })


@router.post("/api/final-internal/hdkp/{inspection_id}")
async def api_save_final_internal_hdkp(inspection_id: int = Path(...), request: Request = None):
    user = core.require_authenticated_api_user(request)
    payload = await request.json()
    with core.get_db_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT * FROM public.qa_final_inspection WHERE id = %s FOR UPDATE", (inspection_id,))
            inspection = cur.fetchone()
            if not inspection:
                raise HTTPException(status_code=404, detail="Không tìm thấy lần kiểm Final")
            core.require_final_cap_access(user, factory=inspection.get("factory"))
            if str(inspection.get("final_status_code") or "") != "0":
                raise HTTPException(status_code=400, detail="Chỉ kết quả FAIL mới cần HĐKP 10.1")
            cur.execute("""INSERT INTO public.qa_final_hdkp (inspection_id, created_by)
                           VALUES (%s, %s) ON CONFLICT (inspection_id) DO UPDATE SET updated_at = NOW()
                           RETURNING id""", (inspection_id, user["ma_nv"]))
            hdkp_id = int(cur.fetchone()["id"])
            mota = payload.get("mota", {})
            cur.execute("""INSERT INTO public.qa_final_hdkp_mota
                (hdkp_id, vd_what, vd_when, vd_who, vd_where, vd_how, vd_before, vd_importance, vd_image)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (hdkp_id) DO UPDATE SET vd_what=EXCLUDED.vd_what, vd_when=EXCLUDED.vd_when,
                vd_who=EXCLUDED.vd_who, vd_where=EXCLUDED.vd_where, vd_how=EXCLUDED.vd_how,
                vd_before=EXCLUDED.vd_before, vd_importance=EXCLUDED.vd_importance, vd_image=EXCLUDED.vd_image,
                updated_at=NOW()""", (hdkp_id, mota.get("vd_what"), mota.get("vd_when"), mota.get("vd_who"), mota.get("vd_where"), mota.get("vd_how"), mota.get("vd_before"), mota.get("vd_importance"), mota.get("vd_image")))
            cur.execute("DELETE FROM public.qa_final_hdkp_kehoach WHERE hdkp_id = %s", (hdkp_id,))
            for idx, item in enumerate(payload.get("kehoach", []), 1):
                cur.execute("""INSERT INTO public.qa_final_hdkp_kehoach
                    (hdkp_id, section, root_cause, hdkp_tuc_thoi, hd_phong_ngua, tg_theo_doi, trach_nhiem, tg_thuc_hien, thu_tu)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""", (hdkp_id, item.get("section"), item.get("root_cause"), item.get("hdkp_tuc_thoi"), item.get("hd_phong_ngua"), item.get("tg_theo_doi"), item.get("trach_nhiem"), item.get("tg_thuc_hien"), idx))
            cur.execute("DELETE FROM public.qa_final_hdkp_chitiet WHERE hdkp_id = %s", (hdkp_id,))
            for idx, item in enumerate(payload.get("chitiet", []), 1):
                start = date.fromisoformat(item["ngay_bat_dau"]) if item.get("ngay_bat_dau") else None
                end = date.fromisoformat(item["ngay_hoan_thanh"]) if item.get("ngay_hoan_thanh") else None
                cur.execute("""INSERT INTO public.qa_final_hdkp_chitiet
                    (hdkp_id, cong_viec, trach_nhiem, ngay_bat_dau, ngay_hoan_thanh, giam_sat, ket_qua, ket_luan, thu_tu)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""", (hdkp_id, item.get("cong_viec"), item.get("trach_nhiem"), start, end, item.get("giam_sat"), item.get("ket_qua"), item.get("ket_luan"), idx))
            conn.commit()
            pdf_url = None
            try:
                row = dict(inspection)
                row["ma_nv"] = user.get("ma_nv")
                row["ngay_ghi_nhan"] = inspection.get("qa_check_date")
                hdkp_data = core.prepare_hdkp_data_for_pdf(hdkp_id, row, ("qa_final_hdkp_mota", "qa_final_hdkp_kehoach", "qa_final_hdkp_chitiet"), "hdkp_id")
                pdf_url = core.create_hdkp_pdf(inspection_id, hdkp_data)
                cur.execute("UPDATE public.qa_final_hdkp SET pdf_url = %s WHERE id = %s", (pdf_url, hdkp_id))
                conn.commit()
            except Exception:
                core.logger.exception("Không thể tạo PDF HĐKP Final nội bộ inspection_id=%s", inspection_id)
    return {"status": "ok", "id": inspection_id, "pdf_url": pdf_url}


@router.post("/api/final-internal/hdkp/{inspection_id}/complete")
async def api_complete_final_internal_hdkp(inspection_id: int = Path(...), request: Request = None):
    user = core.require_authenticated_api_user(request)
    with core.get_db_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT * FROM public.qa_final_inspection WHERE id = %s FOR UPDATE", (inspection_id,))
            inspection = cur.fetchone()
            if not inspection:
                raise HTTPException(status_code=404, detail="Không tìm thấy lần kiểm Final")
            core.require_final_cap_access(user, factory=inspection.get("factory"))
            cur.execute("SELECT id, completed_at, pdf_url FROM public.qa_final_hdkp WHERE inspection_id = %s", (inspection_id,))
            hdkp = cur.fetchone()
            if not hdkp:
                raise HTTPException(status_code=400, detail="Chưa có HĐKP để hoàn thành")
            hdkp_id = hdkp["id"]
            if hdkp["completed_at"]:
                if not hdkp["pdf_url"]:
                    try:
                        row = dict(inspection)
                        row["ma_nv"] = user.get("ma_nv")
                        row["ngay_ghi_nhan"] = inspection.get("qa_check_date")
                        hdkp_data = core.prepare_hdkp_data_for_pdf(hdkp_id, row, ("qa_final_hdkp_mota", "qa_final_hdkp_kehoach", "qa_final_hdkp_chitiet"), "hdkp_id")
                        retry_pdf = core.create_hdkp_pdf(inspection_id, hdkp_data)
                        cur.execute("UPDATE public.qa_final_hdkp SET pdf_url = %s WHERE id = %s", (retry_pdf, hdkp_id))
                        conn.commit()
                        return {"status": "ok", "pdf_url": retry_pdf}
                    except Exception:
                        core.logger.exception("Retry PDF thất bại cho inspection_id=%s", inspection_id)
                return {"status": "already_completed", "pdf_url": hdkp.get("pdf_url")}
            cur.execute("SELECT 1 FROM public.qa_final_hdkp_mota WHERE hdkp_id = %s", (hdkp_id,))
            has_mota = cur.fetchone()
            if not has_mota:
                raise HTTPException(status_code=400, detail="Cần điền nội dung HĐKP trước khi hoàn thành")
            pdf_url = hdkp["pdf_url"]
            if not pdf_url:
                try:
                    row = dict(inspection)
                    row["ma_nv"] = user.get("ma_nv")
                    row["ngay_ghi_nhan"] = inspection.get("qa_check_date")
                    hdkp_data = core.prepare_hdkp_data_for_pdf(hdkp_id, row, ("qa_final_hdkp_mota", "qa_final_hdkp_kehoach", "qa_final_hdkp_chitiet"), "hdkp_id")
                    pdf_url = core.create_hdkp_pdf(inspection_id, hdkp_data)
                except Exception:
                    core.logger.exception("Không thể tạo PDF HĐKP Final nội bộ inspection_id=%s", inspection_id)
            cur.execute(
                "UPDATE public.qa_final_hdkp SET completed_at = NOW(), completed_by = %s, pdf_url = COALESCE(%s, pdf_url) WHERE id = %s",
                (user["ma_nv"], pdf_url, hdkp_id),
            )
            conn.commit()
    return {"status": "ok", "pdf_url": pdf_url}


@router.get("/api/final-internal/filters")
def api_final_internal_filters(request: Request):
    user = core.require_authenticated_api_user(request)
    factory_scope = core.get_final_factory_scope(user)
    with core.get_db_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT ARRAY_REMOVE(ARRAY_AGG(DISTINCT factory ORDER BY factory), NULL) AS factories,
                       ARRAY_REMOVE(ARRAY_AGG(DISTINCT inspector_name ORDER BY inspector_name), NULL) AS inspectors,
                       MIN(qa_check_date) AS min_date,
                       MAX(qa_check_date) AS max_date
                FROM public.qa_final_inspection
                WHERE (%s IS NULL OR factory = %s)
                """,
                (factory_scope, factory_scope),
            )
            row = cur.fetchone() or {}
    return dict(row)


@router.get("/api/final-internal/sync-status")
def api_final_internal_sync_status(request: Request):
    core.require_authenticated_api_user(request)
    return {"configured": core.final_qa_sync_is_configured(), **dict(core._final_sync_state)}


@router.post("/api/final-internal/sync", status_code=202)
def api_final_internal_sync(request: Request):
    user = core.require_authenticated_api_user(request)
    if not core.can_manage_final_sync(user):
        raise HTTPException(status_code=403, detail="Bạn không có quyền đồng bộ dữ liệu Final")
    if not core.final_qa_sync_is_configured():
        raise HTTPException(status_code=503, detail="Chưa cấu hình tài khoản API Final")
    if core._final_sync_state.get("running"):
        return {"status": "running", "message": "Đồng bộ Final đang chạy"}

    def worker() -> None:
        try:
            core.run_final_qa_sync(triggered_by=user.get("ma_nv") or "manual")
        except Exception:
            pass

    threading.Thread(target=worker, daemon=True, name="final-qa-manual-sync").start()
    return {"status": "started", "message": "Đã bắt đầu đồng bộ dữ liệu Final"}


@router.post("/api/final-internal/{inspection_id}/cap")
def api_final_internal_create_cap(inspection_id: int, request: Request):
    user = core.require_authenticated_api_user(request)
    with core.get_db_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT * FROM public.qa_final_inspection WHERE id = %s FOR UPDATE",
                (inspection_id,),
            )
            inspection = cur.fetchone()
            if not inspection:
                raise HTTPException(status_code=404, detail="Không tìm thấy lần kiểm Final")
            core.require_final_cap_access(user, factory=inspection.get("factory"))
            if str(inspection.get("final_status_code") or "") != "0":
                raise HTTPException(
                    status_code=400,
                    detail="Chỉ kết quả FAIL mới cần HĐKP 10.1",
                )
            cur.execute(
                "SELECT id FROM public.qa_final_hdkp WHERE inspection_id = %s",
                (inspection_id,),
            )
            existing_hdkp = cur.fetchone()
            if existing_hdkp:
                return {
                    "status": "exists",
                    "hdkp_id": existing_hdkp["id"],
                    "url": f"/final-internal/hdkp-form/{inspection_id}",
                }

            cur.execute(
                """
                INSERT INTO public.qa_final_hdkp (inspection_id, created_by)
                VALUES (%s, %s)
                RETURNING id
                """,
                (
                    inspection_id,
                    user["ma_nv"],
                ),
            )
            hdkp_id = int(cur.fetchone()["id"])
            conn.commit()
    return {
        "status": "created",
        "hdkp_id": hdkp_id,
        "url": f"/final-internal/hdkp-form/{inspection_id}",
    }
