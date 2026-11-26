"""QC Input — trang và API nhập liệu QC theo sản phẩm (inline/endline, rework).

Tách từ main.py. Các hàm dùng chung (DB, đăng nhập, phân quyền, template) vẫn nằm ở main.py
và được gọi qua `core.<tên>` lúc chạy, nên test patch `main.get_db_connection` vẫn có hiệu lực.

Đăng ký: main.py `app.include_router(qc_input_routes.router)` (xem cuối main.py).
"""
import json
import os
import random
import re
from datetime import date, datetime, timedelta
from datetime import timezone as _dt_timezone
from typing import Any, Dict, List, Optional, Tuple

import psycopg2
import psycopg2.extras
from fastapi import APIRouter, Body, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import RedirectResponse

from app_core import core

router = APIRouter()


# ---------------------------------------------------------------------------
# Trang nhập liệu
# ---------------------------------------------------------------------------
@router.get("/qc-input")
def qc_input_page(request: Request):
    user_data = core.get_authenticated_user(request, qc_only=True)
    if not user_data:
        # Require login if missing or not QC
        return RedirectResponse(url="/qc-login", status_code=303)
    core.require_qc_input_user(request)

    return core.templates.TemplateResponse(
        "qc_input_sp.html",
        core.build_qc_template_context(request, user_data, don_vi_options=core.DON_VI_OPTIONS, page_subtitle="Nhập liệu QC", active_page="input"),
    )


@router.get("/qc-input-2")
def qc_input_sp_page(request: Request):
    return RedirectResponse(url="/qc-input", status_code=303)


# ---------------------------------------------------------------------------
# QC input write helpers (idempotency, locking, validation)
# ---------------------------------------------------------------------------
_VN_TZ = _dt_timezone(timedelta(hours=7))
QC_SP_MAX_PRODUCTS_PER_SUBMIT = 200
_CLIENT_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9_-]{8,64}$")


def vn_today() -> date:
    """Ngày hiện tại theo giờ Việt Nam (không phụ thuộc timezone của máy chủ)."""
    return datetime.now(_VN_TZ).date()


def parse_qc_input_date(value: Any) -> str:
    """Validate ngày báo cáo từ client; mặc định hôm nay (giờ VN)."""
    if value in (None, ""):
        return vn_today().isoformat()
    try:
        parsed = date.fromisoformat(str(value).strip()[:10])
    except ValueError:
        raise HTTPException(status_code=400, detail="Ngày báo cáo không hợp lệ (định dạng YYYY-MM-DD)")
    if parsed > vn_today() + timedelta(days=1):
        raise HTTPException(status_code=400, detail="Không thể ghi nhận cho ngày trong tương lai")
    return parsed.isoformat()


def normalize_client_request_id(value: Any) -> Optional[str]:
    raw = str(value or "").strip()
    if not raw:
        return None
    if not _CLIENT_REQUEST_ID_RE.match(raw):
        raise HTTPException(status_code=400, detail="client_request_id không hợp lệ")
    return raw


def claim_client_request(cur, request_id: Optional[str], endpoint: str) -> Tuple[bool, Optional[Dict]]:
    """Đăng ký request_id trong transaction hiện tại.

    Trả về (is_new, previous_response). Nếu request_id đã được xử lý trước đó
    (client gửi lại do mất mạng), is_new = False và trả về response đã lưu.
    """
    if not request_id:
        return True, None
    cur.execute(
        """
        INSERT INTO public.qc_client_request (request_id, endpoint)
        VALUES (%s, %s)
        ON CONFLICT (request_id) DO NOTHING
        RETURNING request_id
        """,
        (request_id, endpoint),
    )
    if cur.fetchone():
        return True, None
    cur.execute("SELECT response FROM public.qc_client_request WHERE request_id = %s", (request_id,))
    row = cur.fetchone()
    prev = row[0] if row else None
    return False, (prev if isinstance(prev, dict) else None)


def get_completed_client_request(request_id: Optional[str]) -> Optional[Dict]:
    """Response đã lưu của request_id (nếu lần gửi trước đã commit), tra trước mọi kiểm tra khác
    để client gửi lại sau khi mất response không nhận nhầm lỗi 409/400."""
    if not request_id:
        return None
    with core.get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT response FROM public.qc_client_request WHERE request_id = %s AND response IS NOT NULL",
                (request_id,),
            )
            row = cur.fetchone()
    return row[0] if row and isinstance(row[0], dict) else None


def store_client_request_response(cur, request_id: Optional[str], response: Dict) -> None:
    if not request_id:
        return
    cur.execute(
        "UPDATE public.qc_client_request SET response = %s WHERE request_id = %s",
        (psycopg2.extras.Json(response), request_id),
    )
    # Dọn dần các key cũ (client chỉ retry trong vài giờ/ngày) để bảng không phình mãi.
    if random.random() < 0.02:
        cur.execute(
            "DELETE FROM public.qc_client_request WHERE created_at < NOW() - INTERVAL '14 days'"
        )


def lock_qc_sp_slot(cur, plan_id: int, date_str: str, station: str) -> None:
    """Khoá theo (plan, ngày, cụm) trong transaction để tránh tạo trùng log / trùng sp_index."""
    cur.execute(
        "SELECT pg_advisory_xact_lock(hashtext(%s))",
        (f"qc_sp:{plan_id}:{date_str}:{station or ''}",),
    )


def ensure_qc_plan_writable(user: Dict, plan_id: Any) -> int:
    """Gộp check_plan_access + ensure_prod_plan_is_active vào 1 query (cùng mã lỗi như cũ)."""
    try:
        plan_id_int = int(plan_id)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="plan_id không hợp lệ")
    with core.get_db_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT don_vi, COALESCE(is_active, TRUE) AS is_active, is_finished
                FROM public.prod_plan
                WHERE id = %s
                """,
                (plan_id_int,),
            )
            row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Không tìm thấy kế hoạch")
    core.check_factory_access(user, row.get("don_vi"))
    if row.get("is_finished"):
        raise HTTPException(status_code=409, detail="Kế hoạch đã kết thúc. Vui lòng chọn lại kế hoạch khác.")
    if not row.get("is_active"):
        raise HTTPException(status_code=409, detail="Kế hoạch đã ngừng hiệu lực. Vui lòng chọn lại kế hoạch khác.")
    return plan_id_int


@router.post("/api/qc/error-log-sp")
def api_qc_error_log_sp_create(request: Request, body: Dict[str, Any] = Body(...)):
    """Ghi nhận lỗi QC theo sản phẩm (real-time, không chọn mốc thời gian).

    Chỉ hỗ trợ chế độ append (mỗi lần lưu thêm SP lỗi mới).
    Gửi kèm client_request_id để retry an toàn khi mất mạng.
    """
    user = core.require_qc_input_user(request)
    ma_nv_db = user.get("ma_nv")
    client_request_id = normalize_client_request_id(body.get("client_request_id"))
    already_done = get_completed_client_request(client_request_id)
    if already_done:
        return already_done
    plan_id = ensure_qc_plan_writable(user, body.get("plan_id"))
    date_str = parse_qc_input_date(body.get("date"))
    station = (body.get("station") or "").strip()
    defect_products = body.get("defect_products", []) or []
    if not isinstance(defect_products, list):
        raise HTTPException(status_code=400, detail="defect_products phải là danh sách")
    if len(defect_products) > QC_SP_MAX_PRODUCTS_PER_SUBMIT:
        raise HTTPException(
            status_code=400,
            detail=f"Tối đa {QC_SP_MAX_PRODUCTS_PER_SUBMIT} sản phẩm lỗi mỗi lần lưu",
        )
    if not bool(body.get("append_only")):
        raise HTTPException(status_code=400, detail="Chỉ hỗ trợ ghi nhận bổ sung (append_only)")
    pending_failed_count = body.get("pending_failed_count", 0) or 0
    try:
        pending_failed_count = int(pending_failed_count)
    except (TypeError, ValueError):
        pending_failed_count = 0
    if pending_failed_count < 0:
        pending_failed_count = 0
    if pending_failed_count > 0 and len(defect_products) == 0:
        raise HTTPException(status_code=400, detail="pending_failed_count requires defect_products")
    # Mỗi SP lỗi tương ứng tối đa 1 dòng Failed — không cho phép đếm dư.
    pending_failed_count = min(pending_failed_count, len(defect_products))

    def _defect_key(d: Dict) -> Tuple:
        return (
            d.get("bo_phan_id"),
            d.get("chi_tiet_id"),
            d.get("ma_loi_id"),
            d.get("mo_ta_loi_id"),
            (d.get("muc_do") or "").strip(),
        )

    def _has_defect(prod: Dict, key: Tuple) -> bool:
        for x in (prod.get("defects") or []):
            if _defect_key(x) == key:
                return True
        return False

    # Auto detect lap_lai_3 when 3 consecutive products share same defect combo
    for idx, prod in enumerate(defect_products):
        defects = prod.get("defects", []) or []
        for d in defects:
            d["lap_lai_3"] = False
            if idx >= 2:
                key = _defect_key(d)
                if _has_defect(defect_products[idx - 1], key) and _has_defect(defect_products[idx - 2], key):
                    d["lap_lai_3"] = True

    defect_count = len(defect_products)

    with core.get_db_connection() as conn:
        with conn.cursor() as cur:
            lock_qc_sp_slot(cur, plan_id, date_str, station)
            is_new, prev_response = claim_client_request(cur, client_request_id, "error-log-sp")
            if not is_new:
                conn.commit()
                return prev_response or {"status": "ok", "duplicate": True}

            # Calculate output from real-time log (+1/-1)
            cur.execute(
                """
                SELECT COALESCE(SUM(delta), 0)
                FROM public.qc_output_sp_log
                WHERE plan_id = %s AND date = %s AND COALESCE(station, '') = COALESCE(%s, '')
                """,
                (plan_id, date_str, station)
            )
            output = cur.fetchone()[0] or 0

            cur.execute(
                """
                SELECT id
                FROM public.qc_error_log_sp
                WHERE plan_id = %s AND date = %s AND COALESCE(station, '') = COALESCE(%s, '')
                ORDER BY id DESC
                LIMIT 1
                """,
                (plan_id, date_str, station)
            )
            row = cur.fetchone()
            if row:
                log_id = row[0]
                cur.execute(
                    """
                    SELECT COALESCE(MAX(sp_index), 0)
                    FROM public.qc_defect
                    WHERE error_log_sp_id = %s
                    """,
                    (log_id,)
                )
                base_index = cur.fetchone()[0] or 0
                total_after = base_index + defect_count
                cur.execute(
                    """
                    UPDATE public.qc_error_log_sp
                    SET output = %s,
                        defect_count = %s,
                        ma_nv = COALESCE(ma_nv, %s),
                        updated_at = NOW()
                    WHERE id = %s
                    """,
                    (output, total_after, ma_nv_db, log_id)
                )
                updated = True
            else:
                cur.execute(
                    """
                    INSERT INTO public.qc_error_log_sp (plan_id, date, station, output, defect_count, ma_nv)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (plan_id, date_str, station, output, defect_count, ma_nv_db)
                )
                log_id = cur.fetchone()[0]
                updated = False
                base_index = 0

            for idx, prod in enumerate(defect_products, start=1):
                defects = prod.get("defects", []) or []
                for d in defects:
                    cur.execute(
                        """
                        INSERT INTO public.qc_defect
                        (
                            error_log_sp_id, sp_index, bo_phan_id, chi_tiet_id,
                            ma_loi_id, mo_ta_loi_id, muc_do, lap_lai_3, image_path,
                            defect_catalog_id, ma_loi_code_snapshot, mo_ta_loi_snapshot, nhom_loi_snapshot
                        )
                        VALUES (
                            %s, %s, %s, %s, %s, %s, %s, %s, %s,
                            COALESCE(
                                %s,
                                (
                                    SELECT nl.catalog_id
                                    FROM public.dm_ma_loi ml
                                    JOIN public.dm_nhom_loi nl ON nl.id = ml.nhom_loi_id
                                    WHERE ml.id = %s
                                )
                            ),
                            COALESCE(%s, (SELECT ml.ten_ma FROM public.dm_ma_loi ml WHERE ml.id = %s)),
                            COALESCE(%s, (SELECT mt.ten_mo_ta FROM public.dm_mo_ta_loi mt WHERE mt.id = %s)),
                            COALESCE(
                                %s,
                                (
                                    SELECT nl.ten_nhom
                                    FROM public.dm_ma_loi ml
                                    JOIN public.dm_nhom_loi nl ON nl.id = ml.nhom_loi_id
                                    WHERE ml.id = %s
                                )
                            )
                        )
                        """,
                        (
                            log_id,
                            base_index + idx,
                            d.get("bo_phan_id"),
                            d.get("chi_tiet_id"),
                            d.get("ma_loi_id"),
                            d.get("mo_ta_loi_id"),
                            d.get("muc_do"),
                            d.get("lap_lai_3", False),
                            d.get("image_path"),
                            d.get("catalog_id"),
                            d.get("ma_loi_id"),
                            d.get("ma_loi_code"),
                            d.get("ma_loi_id"),
                            d.get("mo_ta_loi"),
                            d.get("mo_ta_loi_id"),
                            d.get("nhom_loi"),
                            d.get("ma_loi_id"),
                        )
                    )
            failed_times = []
            if pending_failed_count > 0:
                # Insert hàng loạt các dòng Failed; trả về giờ VN để ghi qc_defect_multi.
                cur.execute(
                    """
                    INSERT INTO public.qc_output_sp_log (plan_id, date, station, delta, status, ma_nv)
                    SELECT %s, %s, %s, 1, 'Failed', %s
                    FROM generate_series(1, %s)
                    RETURNING timezone('Asia/Ho_Chi_Minh', created_at)
                    """,
                    (plan_id, date_str, station, ma_nv_db, pending_failed_count)
                )
                failed_times = [r[0] for r in cur.fetchall()]
                cur.execute(
                    """
                    SELECT COALESCE(COUNT(*), 0)
                    FROM public.qc_output_sp_log
                    WHERE plan_id = %s AND date = %s AND COALESCE(station, '') = COALESCE(%s, '')
                    """
                    , (plan_id, date_str, station)
                )
                output = cur.fetchone()[0] or 0
                cur.execute(
                    """
                    UPDATE public.qc_error_log_sp
                    SET output = %s, updated_at = NOW()
                    WHERE id = %s
                    """
                    , (output, log_id)
                )

            # Detect 3 consecutive failed products sharing same (bo_phan, chi_tiet, ma_loi)
            # and log to qc_defect_multi at the 3rd occurrence only.
            if defect_products and pending_failed_count > 0:
                min_sp = max(1, base_index - 2)
                max_sp = base_index + defect_count
                cur.execute(
                    """
                    SELECT sp_index, bo_phan_id, chi_tiet_id, ma_loi_id
                    FROM public.qc_defect
                    WHERE error_log_sp_id = %s
                      AND sp_index BETWEEN %s AND %s
                    """,
                    (log_id, min_sp, max_sp)
                )
                sp_map: Dict[int, set] = {}
                for sp_index, bp_id, ct_id, ml_id in cur.fetchall():
                    sp_map.setdefault(int(sp_index), set()).add((bp_id, ct_id, ml_id))

                def _get_keys(sp_idx: int) -> set:
                    return sp_map.get(sp_idx, set())

                new_sp_indices = [base_index + i for i in range(1, defect_count + 1)]
                time_by_sp = {}
                for i, sp_idx in enumerate(new_sp_indices):
                    t = failed_times[i] if i < len(failed_times) else None
                    time_by_sp[sp_idx] = t

                records = []
                for sp_idx in new_sp_indices:
                    keys_cur = _get_keys(sp_idx)
                    if not keys_cur:
                        continue
                    keys_prev1 = _get_keys(sp_idx - 1)
                    keys_prev2 = _get_keys(sp_idx - 2)
                    keys_prev3 = _get_keys(sp_idx - 3)
                    for key in keys_cur:
                        if key in keys_prev1 and key in keys_prev2 and key not in keys_prev3:
                            records.append((sp_idx, key))

                if records:
                    bp_ids = {k[0] for _, k in records if k[0] is not None}
                    ct_ids = {k[1] for _, k in records if k[1] is not None}
                    ml_ids = {k[2] for _, k in records if k[2] is not None}

                    bp_map = {}
                    ct_map = {}
                    ml_map = {}
                    if bp_ids:
                        cur.execute(
                            "SELECT id, ten_bo_phan FROM public.dm_bo_phan WHERE id = ANY(%s)",
                            (list(bp_ids),)
                        )
                        bp_map = {row[0]: row[1] for row in cur.fetchall()}
                    if ct_ids:
                        cur.execute(
                            "SELECT id, ten_chi_tiet FROM public.dm_chi_tiet WHERE id = ANY(%s)",
                            (list(ct_ids),)
                        )
                        ct_map = {row[0]: row[1] for row in cur.fetchall()}
                    if ml_ids:
                        cur.execute(
                            "SELECT id, ten_ma FROM public.dm_ma_loi WHERE id = ANY(%s)",
                            (list(ml_ids),)
                        )
                        ml_map = {row[0]: row[1] for row in cur.fetchall()}

                    for sp_idx, key in records:
                        bp_id, ct_id, ml_id = key
                        t = time_by_sp.get(sp_idx)
                        time_val = t.time() if hasattr(t, "time") else datetime.now(_VN_TZ).time()
                        cur.execute(
                            """
                            INSERT INTO public.qc_defect_multi
                            (plan_id, date, station, time, bo_phan, chi_tiet, ma_loi, ma_nv)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                            """,
                            (
                                plan_id,
                                date_str,
                                station,
                                time_val,
                                bp_map.get(bp_id) if bp_id is not None else None,
                                ct_map.get(ct_id) if ct_id is not None else None,
                                ml_map.get(ml_id) if ml_id is not None else None,
                                ma_nv_db,
                            )
                        )
            response = {
                "status": "ok",
                "id": log_id,
                "updated": updated,
                "last_sp_index": base_index + defect_count,
            }
            store_client_request_response(cur, client_request_id, response)
            conn.commit()
    return response


@router.post("/api/qc/upload-sp-image", dependencies=[Depends(core.require_qc_input_user)])
async def api_qc_upload_sp_image(file: UploadFile = File(...)):
    """Upload anh chup san pham loi QC (SP mode)."""
    import uuid
    sub_dir = os.path.join(core.IMAGES_STORAGE_DIR, "qc_sp")
    os.makedirs(sub_dir, exist_ok=True)
    max_bytes = 10 * 1024 * 1024
    contents = await file.read(max_bytes + 1)
    if len(contents) > max_bytes:
        raise HTTPException(status_code=413, detail="Ảnh vượt quá 10MB")
    # Xác định loại ảnh theo magic bytes, không tin phần mở rộng client gửi lên.
    if contents.startswith(b"\xff\xd8\xff"):
        ext = ".jpg"
    elif contents.startswith(b"\x89PNG\r\n\x1a\n"):
        ext = ".png"
    elif contents[:4] == b"RIFF" and contents[8:12] == b"WEBP":
        ext = ".webp"
    else:
        raise HTTPException(status_code=400, detail="Chỉ chấp nhận ảnh JPG, PNG hoặc WEBP")
    unique_name = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}{ext}"
    file_path = os.path.join(sub_dir, unique_name)
    with open(file_path, "wb") as f:
        f.write(contents)
    relative_path = f"qc_sp/{unique_name}"
    return {"status": "ok", "image_path": relative_path, "url": f"/api/images/{relative_path}"}



@router.post("/api/qc/output-sp-log")
def api_qc_output_sp_log_create(request: Request, body: Dict[str, Any] = Body(...)):
    """Ghi nhận thao tác +1/-1 cho số sản phẩm đã kiểm (theo sản phẩm).

    -1 chỉ hoàn tác dòng 'Passed' gần nhất của chính QC (không đụng dòng 'Failed'
    vì dòng đó gắn với SP lỗi trong qc_defect).
    """
    user = core.require_qc_input_user(request)
    ma_nv_db = user.get("ma_nv")
    if not ma_nv_db:
        raise HTTPException(status_code=403, detail="Không có quyền (QC only)")
    plan_id = ensure_qc_plan_writable(user, body.get("plan_id"))
    date_str = parse_qc_input_date(body.get("date"))
    station = (body.get("station") or "").strip()
    client_request_id = normalize_client_request_id(body.get("client_request_id"))
    delta = body.get("delta", 1)
    status = (body.get("status") or "Passed").strip()
    try:
        delta = int(delta)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="delta phải là số (+1 hoặc -1)")
    if delta not in (1, -1):
        raise HTTPException(status_code=400, detail="delta chỉ nhận +1 hoặc -1")
    if status not in ("Passed", "Failed"):
        raise HTTPException(status_code=400, detail="status must be Passed or Failed")

    with core.get_db_connection() as conn:
        with conn.cursor() as cur:
            is_new, _prev = claim_client_request(cur, client_request_id, "output-sp-log")
            if is_new:
                if delta == 1:
                    cur.execute(
                        """
                        INSERT INTO public.qc_output_sp_log (plan_id, date, station, delta, status, ma_nv)
                        VALUES (%s, %s, %s, 1, %s, %s)
                        """,
                        (plan_id, date_str, station, status, ma_nv_db)
                    )
                else:
                    # Hoàn tác +1 Đạt gần nhất (same plan/date/station) của QC hiện tại
                    cur.execute(
                        """
                        DELETE FROM public.qc_output_sp_log
                        WHERE id = (
                            SELECT id FROM public.qc_output_sp_log
                            WHERE plan_id = %s
                              AND date = %s
                              AND COALESCE(station, '') = COALESCE(%s, '')
                              AND COALESCE(ma_nv, '') = COALESCE(%s, '')
                              AND status = 'Passed'
                            ORDER BY created_at DESC, id DESC
                            LIMIT 1
                        )
                        """,
                        (plan_id, date_str, station, ma_nv_db)
                    )
            cur.execute(
                """
                SELECT
                    COALESCE(COUNT(*), 0) AS total,
                    COALESCE(SUM(CASE WHEN status = 'Passed' THEN 1 ELSE 0 END), 0) AS passed_count,
                    COALESCE(SUM(CASE WHEN status = 'Failed' THEN 1 ELSE 0 END), 0) AS failed_count
                FROM public.qc_output_sp_log
                WHERE plan_id = %s AND date = %s AND COALESCE(station, '') = COALESCE(%s, '')
                """,
                (plan_id, date_str, station)
            )
            row = cur.fetchone()
        conn.commit()

    return {
        "status": "ok",
        "total": row[0],
        "passed_count": row[1],
        "failed_count": row[2],
    }


@router.get("/api/qc/output-sp", dependencies=[Depends(core.require_plan_reader)])
def api_qc_output_sp_get(
    plan_id: int = Query(...),
    date_str: str = Query(..., alias="date"),
    station: Optional[str] = Query(None),
):
    """Lấy tổng số sản phẩm đã kiểm (tính theo log +1/-1)."""
    with core.get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    COALESCE(COUNT(*), 0) AS total,
                    COALESCE(SUM(CASE WHEN status = 'Passed' THEN 1 ELSE 0 END), 0) AS passed_count,
                    COALESCE(SUM(CASE WHEN status = 'Failed' THEN 1 ELSE 0 END), 0) AS failed_count
                FROM public.qc_output_sp_log
                WHERE plan_id = %s AND date = %s AND COALESCE(station, '') = COALESCE(%s, '')
                """,
                (plan_id, date_str, station)
            )
            row = cur.fetchone()
            # Số sản phẩm lỗi đã sửa xong (dùng để trừ double-count ở tổ sync).
            cur.execute(
                """
                SELECT COUNT(*) FROM (
                    SELECT d.error_log_sp_id, d.sp_index
                    FROM public.qc_defect d
                    JOIN public.qc_error_log_sp sp ON sp.id = d.error_log_sp_id
                    WHERE sp.plan_id = %s AND sp.date = %s
                      AND COALESCE(sp.station, '') = COALESCE(%s, '')
                      AND d.sp_index IS NOT NULL
                    GROUP BY d.error_log_sp_id, d.sp_index
                    HAVING BOOL_AND(COALESCE(d.rework_done, FALSE))
                ) t
                """,
                (plan_id, date_str, station)
            )
            reworked_count = cur.fetchone()[0] or 0
            return {
                "total": row[0],
                "passed_count": row[1],
                "failed_count": row[2],
                "reworked_count": reworked_count,
            }


@router.get("/api/qc/input/pos-summary", dependencies=[Depends(core.require_plan_reader)])
def api_qc_input_pos_summary(
    plan_id: int = Query(...),
    date_str: str = Query(..., alias="date"),
    station: Optional[str] = Query(None),
):
    """Thống kê lỗi theo vị trí trong từng mốc thời gian cho trang /qc-input.

    Các loại lỗi:
    - Lỗi đại trà: theo combo (Vị trí [Bộ phận - Chi tiết] + Mã lỗi) / tổng kiểm trong mốc >= 15%
      (mẫu số: qc_output_sp_log; đếm theo số sản phẩm DISTINCT (error_log_sp_id, sp_index))
    - Lỗi nghiêm trọng: qc_defect.muc_do ILIKE '%nghiêm%'
    - Lỗi nguy cơ hàng loạt: qc_defect_multi
    """

    def _bucket_case(time_expr: str) -> str:
        return f"""
            CASE
                WHEN {time_expr} < '09:30' THEN '7H30 - 9H30'
                WHEN {time_expr} >= '09:30' AND {time_expr} < '11:30' THEN '9H30 - 11H30'
                WHEN {time_expr} >= '11:30' AND {time_expr} < '14:30' THEN '12H30 - 14H30'
                WHEN {time_expr} >= '14:30' AND {time_expr} < '16:30' THEN '14H30 - 16H30'
                ELSE 'Sau 16H30'
            END
        """

    def _vi_tri(bo_phan: str, chi_tiet: str) -> str:
        parts = [p for p in [bo_phan, chi_tiet] if p]
        return " - ".join(parts) if parts else "--"

    bucket_order = ["7H30 - 9H30", "9H30 - 11H30", "12H30 - 14H30", "14H30 - 16H30", "Sau 16H30"]

    with core.get_db_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            output_params: List = [plan_id, date_str]
            output_where = ["o.plan_id = %s", "o.date = %s"]
            if station:
                output_where.append("COALESCE(o.station, '') = COALESCE(%s, '')")
                output_params.append(station)
            cur.execute(
                f"""
                SELECT
                    {_bucket_case("timezone('Asia/Bangkok', o.created_at)::time")} AS time_bucket,
                    SUM(o.delta) AS output_total,
                    SUM(CASE WHEN o.status = 'Failed' THEN o.delta ELSE 0 END) AS defect_total
                FROM public.qc_output_sp_log o
                WHERE {" AND ".join(output_where)}
                GROUP BY time_bucket
                """,
                tuple(output_params),
            )
            output_rows = cur.fetchall()
            output_by_bucket = {r["time_bucket"]: int(r.get("output_total") or 0) for r in output_rows}
            failed_by_bucket = {r["time_bucket"]: int(r.get("defect_total") or 0) for r in output_rows}

            sp_params: List = [plan_id, date_str]
            sp_where = ["sp.plan_id = %s", "sp.date = %s"]
            if station:
                sp_where.append("COALESCE(sp.station, '') = COALESCE(%s, '')")
                sp_params.append(station)
            sp_where_sql = " AND ".join(sp_where)

            # Serious
            cur.execute(
                f"""
                SELECT
                    {_bucket_case("timezone('Asia/Bangkok', d.created_at)::time")} AS time_bucket,
                    COALESCE(ml.ten_ma, d.ma_loi_id::text) AS ma_loi,
                    COALESCE(bp.ten_bo_phan, '') AS bo_phan,
                    COALESCE(ct.ten_chi_tiet, '') AS chi_tiet,
                    COUNT(*) AS qty
                FROM public.qc_defect d
                JOIN public.qc_error_log_sp sp ON sp.id = d.error_log_sp_id
                LEFT JOIN public.dm_ma_loi ml ON ml.id = d.ma_loi_id
                LEFT JOIN public.dm_bo_phan bp ON bp.id = d.bo_phan_id
                LEFT JOIN public.dm_chi_tiet ct ON ct.id = d.chi_tiet_id
                WHERE {sp_where_sql}
                  AND d.muc_do ILIKE '%%nghiêm%%'
                GROUP BY time_bucket, ma_loi, bo_phan, chi_tiet
                """,
                tuple(sp_params),
            )
            serious_rows = cur.fetchall()

            # Multi risk
            multi_params: List = [plan_id, date_str]
            multi_where = ["qdm.plan_id = %s", "qdm.date = %s"]
            if station:
                multi_where.append("COALESCE(qdm.station, '') = COALESCE(%s, '')")
                multi_params.append(station)
            cur.execute(
                f"""
                SELECT
                    {_bucket_case("qdm.time")} AS time_bucket,
                    COALESCE(qdm.ma_loi, '') AS ma_loi,
                    COALESCE(qdm.bo_phan, '') AS bo_phan,
                    COALESCE(qdm.chi_tiet, '') AS chi_tiet,
                    COUNT(*) AS occurrences
                FROM public.qc_defect_multi qdm
                WHERE {" AND ".join(multi_where)}
                GROUP BY time_bucket, ma_loi, bo_phan, chi_tiet
                """,
                tuple(multi_params),
            )
            multi_rows = cur.fetchall()

            # Mass combos
            cur.execute(
                f"""
                SELECT
                    {_bucket_case("timezone('Asia/Bangkok', d.created_at)::time")} AS time_bucket,
                    COALESCE(ml.ten_ma, d.ma_loi_id::text) AS ma_loi,
                    COALESCE(bp.ten_bo_phan, '') AS bo_phan,
                    COALESCE(ct.ten_chi_tiet, '') AS chi_tiet,
                    COUNT(DISTINCT (d.error_log_sp_id, d.sp_index)) AS qty
                FROM public.qc_defect d
                JOIN public.qc_error_log_sp sp ON sp.id = d.error_log_sp_id
                LEFT JOIN public.dm_ma_loi ml ON ml.id = d.ma_loi_id
                LEFT JOIN public.dm_bo_phan bp ON bp.id = d.bo_phan_id
                LEFT JOIN public.dm_chi_tiet ct ON ct.id = d.chi_tiet_id
                WHERE {sp_where_sql}
                  AND d.error_log_sp_id IS NOT NULL
                  AND d.sp_index IS NOT NULL
                GROUP BY time_bucket, ma_loi, bo_phan, chi_tiet
                """,
                tuple(sp_params),
            )
            mass_rows = cur.fetchall()

            # HDKP map (reuse same connection)
            cur.execute(
                """
                SELECT
                    dps.time_bucket,
                    dps.loai_loi,
                    COALESCE(dps.ma_loi, '') AS ma_loi,
                    COALESCE(dps.vi_tri, '') AS vi_tri,
                    CASE WHEN hm.qc_error_dps_id IS NOT NULL THEN TRUE ELSE FALSE END AS has_hdkp
                FROM public.qc_error_dps dps
                LEFT JOIN public.qc_hdkp_mota hm ON hm.qc_error_dps_id = dps.id
                WHERE dps.plan_id = %s
                  AND dps.date = %s
                  AND COALESCE(dps.station, '') = COALESCE(%s, '')
                """,
                (plan_id, date_str, station),
            )
            hdkp_map = {
                (
                    r.get("time_bucket") or "",
                    r.get("loai_loi") or "",
                    r.get("ma_loi") or "",
                    r.get("vi_tri") or "",
                ): bool(r.get("has_hdkp"))
                for r in cur.fetchall()
            }

    bucket_map: Dict[str, List[Dict]] = {b: [] for b in bucket_order}
    loai_order = {"Lỗi đại trà": 0, "Lỗi nghiêm trọng": 1, "Lỗi nguy cơ hàng loạt": 2}

    for r in serious_rows:
        bucket = r.get("time_bucket")
        if bucket not in bucket_map:
            continue
        ma_loi = r.get("ma_loi") or "--"
        vi_tri = _vi_tri(r.get("bo_phan") or "", r.get("chi_tiet") or "")
        bucket_map[bucket].append({
            "loai_loi": "Lỗi nghiêm trọng",
            "ma_loi": ma_loi,
            "bo_phan": r.get("bo_phan") or "",
            "chi_tiet": r.get("chi_tiet") or "",
            "vi_tri": f"{ma_loi} - {vi_tri}",
            "qty": int(r.get("qty") or 0),
        })

    for r in multi_rows:
        bucket = r.get("time_bucket")
        if bucket not in bucket_map:
            continue
        ma_loi = (r.get("ma_loi") or "").strip() or "--"
        vi_tri = _vi_tri(r.get("bo_phan") or "", r.get("chi_tiet") or "")
        bucket_map[bucket].append({
            "loai_loi": "Lỗi nguy cơ hàng loạt",
            "ma_loi": ma_loi,
            "bo_phan": r.get("bo_phan") or "",
            "chi_tiet": r.get("chi_tiet") or "",
            "vi_tri": f"{ma_loi} - {vi_tri}",
            "qty": int(r.get("occurrences") or 0),
        })

    for r in mass_rows:
        bucket = r.get("time_bucket")
        if bucket not in bucket_map:
            continue
        qty = int(r.get("qty") or 0)
        if qty <= 0:
            continue
        output_total = int(output_by_bucket.get(bucket) or 0)
        if output_total <= 0:
            continue
        if (qty / output_total) < 0.15:
            continue
        ma_loi = r.get("ma_loi") or "--"
        vi_tri = _vi_tri(r.get("bo_phan") or "", r.get("chi_tiet") or "")
        bucket_map[bucket].append({
            "loai_loi": "Lỗi đại trà",
            "ma_loi": ma_loi,
            "bo_phan": r.get("bo_phan") or "",
            "chi_tiet": r.get("chi_tiet") or "",
            "vi_tri": f"{ma_loi} - {vi_tri}",
            "qty": qty,
        })

    buckets = []
    for b in bucket_order:
        items = bucket_map.get(b) or []
        items = [x for x in items if int(x.get("qty") or 0) > 0]
        for item in items:
            raw_vi_tri = " - ".join([p for p in [item.get("bo_phan") or "", item.get("chi_tiet") or ""] if p])
            item["has_hdkp"] = hdkp_map.get(
                (
                    b,
                    item.get("loai_loi") or "",
                    item.get("ma_loi") or "",
                    raw_vi_tri,
                ),
                False,
            )
        items.sort(key=lambda x: (loai_order.get(x.get("loai_loi") or "", 99), -int(x.get("qty") or 0), str(x.get("vi_tri") or "")))
        output_total = int(output_by_bucket.get(b) or 0)
        defect_total = int(failed_by_bucket.get(b) or 0)
        defect_rate = round((defect_total / output_total) * 100, 2) if output_total > 0 else 0.0
        buckets.append({
            "time_bucket": b,
            "output_total": output_total,
            "defect_total": defect_total,
            "defect_rate": defect_rate,
            "items": items,
        })

    return {"status": "ok", "plan_id": plan_id, "date": date_str, "station": station or "", "buckets": buckets}


@router.get("/api/qc/input/quick-defect-combos", dependencies=[Depends(core.require_plan_reader)])
def api_qc_input_quick_defect_combos(
    plan_id: int = Query(...),
    station: str = Query(...),
    date_str: Optional[str] = Query(None, alias="date"),
):
    """Top defect combos by history, resolved to the active defect catalog for the input date."""
    station_clean = (station or "").strip()
    if not station_clean:
        return {"status": "ok", "rows": [], "message": "Chưa chọn cụm."}

    with core.get_db_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            catalog_id = core.get_effective_defect_catalog_id(cur, date_str)
            cur.execute(
                """
                SELECT code, effective_from, effective_to
                FROM public.dm_defect_catalog
                WHERE id = %s
                """,
                (catalog_id,),
            )
            catalog_row = cur.fetchone() or {}
            catalog_from = catalog_row.get("effective_from")
            catalog_to = catalog_row.get("effective_to")
            catalog_code = catalog_row.get("code")
            map_legacy_codes = (catalog_code == "qlcl-hdkt-8.9-bm3-rev08")
            try:
                history_ref_date = date.fromisoformat((date_str or "").strip()[:10])
            except ValueError:
                history_ref_date = vn_today()
            cur.execute(
                """
                WITH selected AS (
                    SELECT p.id AS plan_id,
                           p.loai_hang,
                           lh.id AS loai_hang_id,
                           %s::text AS station
                    FROM public.prod_plan p
                    JOIN public.dm_loai_hang lh ON lh.ten_loai = p.loai_hang
                    WHERE p.id = %s
                    LIMIT 1
                ),
                history AS (
                    SELECT
                        d.bo_phan_id,
                        bp.ten_bo_phan,
                        d.chi_tiet_id,
                        ct.ten_chi_tiet,
                        COALESCE(d.ma_loi_code_snapshot, ml_old.ten_ma, '') AS old_ten_ma,
                        COALESCE(old_cat.code, 'legacy-before-2026-07-28') AS old_catalog_code,
                        sp.date
                    FROM selected s
                    JOIN public.prod_plan p
                      ON p.loai_hang = s.loai_hang
                    JOIN public.qc_error_log_sp sp
                      ON sp.plan_id = p.id
                     AND sp.station = s.station
                    JOIN public.qc_defect d
                      ON d.error_log_sp_id = sp.id
                    JOIN public.dm_bo_phan bp
                      ON bp.id = d.bo_phan_id
                     AND bp.loai_hang_id = s.loai_hang_id
                    JOIN public.dm_chi_tiet ct
                      ON ct.id = d.chi_tiet_id
                     AND ct.bo_phan_id = bp.id
                    LEFT JOIN public.dm_ma_loi ml_old
                      ON ml_old.id = d.ma_loi_id
                    LEFT JOIN public.dm_defect_catalog old_cat
                      ON old_cat.id = d.defect_catalog_id
                    WHERE d.bo_phan_id IS NOT NULL
                      AND d.chi_tiet_id IS NOT NULL
                      AND d.ma_loi_id IS NOT NULL
                      AND d.mo_ta_loi_id IS NOT NULL
                      -- Giới hạn lịch sử: tối thiểu 180 ngày gần nhất, luôn bao trùm
                      -- toàn bộ thời gian hiệu lực của catalog hiện tại (giữ nguyên defect_qty).
                      AND sp.date >= LEAST(
                          COALESCE(%s::date, %s::date),
                          %s::date - INTERVAL '180 days'
                      )
                ),
                mapped_history AS (
                    SELECT
                        h.bo_phan_id,
                        h.ten_bo_phan,
                        h.chi_tiet_id,
                        h.ten_chi_tiet,
                        CASE
                            WHEN %s
                                 AND (h.old_catalog_code = 'legacy-before-2026-07-28' OR h.date < DATE '2026-07-28')
                                 AND h.old_ten_ma ~ '^S[0-9]+$'
                                THEN 'E' || substring(h.old_ten_ma from 2)
                            WHEN %s
                                 AND (h.old_catalog_code = 'legacy-before-2026-07-28' OR h.date < DATE '2026-07-28')
                                 AND h.old_ten_ma ~ '^F[0-9]+$'
                                THEN 'O' || substring(h.old_ten_ma from 2)
                            ELSE h.old_ten_ma
                        END AS target_ten_ma,
                        h.old_ten_ma,
                        h.old_catalog_code,
                        h.date
                    FROM history h
                ),
                suggestions AS (
                    SELECT
                        bo_phan_id,
                        ten_bo_phan,
                        chi_tiet_id,
                        ten_chi_tiet,
                        target_ten_ma,
                        COUNT(*)::int AS historical_qty
                    FROM mapped_history
                    GROUP BY bo_phan_id, ten_bo_phan, chi_tiet_id, ten_chi_tiet, target_ten_ma
                ),
                current_counts AS (
                    SELECT
                        bo_phan_id,
                        chi_tiet_id,
                        target_ten_ma,
                        COUNT(*)::int AS current_qty
                    FROM mapped_history
                    WHERE date >= %s::date
                      AND (%s::date IS NULL OR date <= %s::date)
                      AND old_catalog_code = %s
                    GROUP BY bo_phan_id, chi_tiet_id, target_ten_ma
                )
                SELECT
                    s.bo_phan_id,
                    s.ten_bo_phan,
                    s.chi_tiet_id,
                    s.ten_chi_tiet,
                    ml.id AS ma_loi_id,
                    ml.ten_ma,
                    mt.id AS mo_ta_loi_id,
                    mt.ten_mo_ta,
                    dc.id AS catalog_id,
                    dc.code AS catalog_code,
                    nl.ten_nhom,
                    MAX(mt.muc_do::text) AS muc_do_text,
                    COALESCE(MAX(cc.current_qty), 0)::int AS defect_qty,
                    MAX(s.historical_qty)::int AS historical_qty
                FROM suggestions s
                JOIN public.dm_defect_catalog dc
                  ON dc.id = %s
                JOIN public.dm_nhom_loi nl
                  ON nl.catalog_id = dc.id
                JOIN public.dm_ma_loi ml
                  ON ml.nhom_loi_id = nl.id
                 AND ml.ten_ma = s.target_ten_ma
                JOIN public.dm_mo_ta_loi mt
                  ON mt.ma_loi_id = ml.id
                LEFT JOIN current_counts cc
                  ON cc.bo_phan_id = s.bo_phan_id
                 AND cc.chi_tiet_id = s.chi_tiet_id
                 AND cc.target_ten_ma = s.target_ten_ma
                GROUP BY
                    s.bo_phan_id, s.ten_bo_phan,
                    s.chi_tiet_id, s.ten_chi_tiet,
                    ml.id, ml.ten_ma,
                    mt.id, mt.ten_mo_ta,
                    dc.id, dc.code, nl.ten_nhom
                ORDER BY defect_qty DESC, historical_qty DESC, s.ten_bo_phan, s.ten_chi_tiet, ml.ten_ma, mt.ten_mo_ta
                LIMIT 15
                """,
                (
                    station_clean,
                    plan_id,
                    catalog_from,
                    history_ref_date,
                    history_ref_date,
                    map_legacy_codes,
                    map_legacy_codes,
                    catalog_from,
                    catalog_to,
                    catalog_to,
                    catalog_code,
                    catalog_id,
                ),
            )
            rows = cur.fetchall()

    for r in rows:
        muc_do_text = r.pop("muc_do_text", None)
        try:
            r["muc_do"] = json.loads(muc_do_text) if muc_do_text else None
        except (TypeError, ValueError):
            r["muc_do"] = muc_do_text
        r["label"] = (
            f"{r.get('ten_bo_phan') or ''} - "
            f"{r.get('ten_chi_tiet') or ''} - "
            f"{r.get('ten_ma') or ''}. {r.get('ten_mo_ta') or ''}"
        )
    return {"status": "ok", "rows": rows}


@router.get("/api/qc/input/quick-defect-combos-today", dependencies=[Depends(core.require_plan_reader)])
def api_qc_input_quick_defect_combos_today(
    plan_id: int = Query(...),
    station: str = Query(...),
    date_str: Optional[str] = Query(None, alias="date"),
):
    """Defect combos recorded today for this plan/station — covers new patterns not in cumulative history."""
    station_clean = (station or "").strip()
    if not station_clean:
        return {"status": "ok", "rows": []}

    target_date = date_str or str(date.today())

    with core.get_db_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            catalog_id = core.get_effective_defect_catalog_id(cur, date_str)
            cur.execute(
                """
                SELECT
                    d.bo_phan_id,
                    bp.ten_bo_phan,
                    d.chi_tiet_id,
                    ct.ten_chi_tiet,
                    d.ma_loi_id,
                    ml.ten_ma,
                    d.mo_ta_loi_id,
                    mt.ten_mo_ta,
                    d.defect_catalog_id AS catalog_id,
                    dc.code AS catalog_code,
                    nl.ten_nhom,
                    MAX(mt.muc_do::text) AS muc_do_text,
                    COUNT(*)::int AS defect_qty
                FROM public.qc_defect d
                JOIN public.qc_error_log_sp sp ON sp.id = d.error_log_sp_id
                JOIN public.prod_plan p ON p.id = sp.plan_id
                LEFT JOIN public.dm_bo_phan bp ON bp.id = d.bo_phan_id
                LEFT JOIN public.dm_chi_tiet ct ON ct.id = d.chi_tiet_id
                LEFT JOIN public.dm_ma_loi ml ON ml.id = d.ma_loi_id
                LEFT JOIN public.dm_mo_ta_loi mt ON mt.ma_loi_id = ml.id AND mt.id = d.mo_ta_loi_id
                LEFT JOIN public.dm_defect_catalog dc ON dc.id = d.defect_catalog_id
                LEFT JOIN public.dm_nhom_loi nl ON nl.id = ml.nhom_loi_id
                WHERE sp.plan_id = %s
                  AND sp.date = %s
                  AND COALESCE(sp.station, '') = %s
                  AND d.bo_phan_id IS NOT NULL
                  AND d.chi_tiet_id IS NOT NULL
                  AND d.ma_loi_id IS NOT NULL
                  AND d.mo_ta_loi_id IS NOT NULL
                GROUP BY
                    d.bo_phan_id, bp.ten_bo_phan,
                    d.chi_tiet_id, ct.ten_chi_tiet,
                    d.ma_loi_id, ml.ten_ma,
                    d.mo_ta_loi_id, mt.ten_mo_ta,
                    d.defect_catalog_id, dc.code, nl.ten_nhom
                ORDER BY defect_qty DESC, bp.ten_bo_phan, ct.ten_chi_tiet, ml.ten_ma
                """,
                (plan_id, target_date, station_clean),
            )
            rows = cur.fetchall()

    for r in rows:
        muc_do_text = r.pop("muc_do_text", None)
        try:
            r["muc_do"] = json.loads(muc_do_text) if muc_do_text else None
        except (TypeError, ValueError):
            r["muc_do"] = muc_do_text
        r["label"] = (
            f"{r.get('ten_bo_phan') or ''} - "
            f"{r.get('ten_chi_tiet') or ''} - "
            f"{r.get('ten_ma') or ''}. {r.get('ten_mo_ta') or ''}"
        )
    return {"status": "ok", "rows": rows}


@router.get("/api/qc/error-log-sp", dependencies=[Depends(core.require_plan_reader)])
def api_qc_error_log_sp_get(
    plan_id: int = Query(...),
    date_str: str = Query(..., alias="date"),
    station: Optional[str] = Query(None),
):
    """Lấy dữ liệu QC theo sản phẩm để sửa."""
    with core.get_db_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT id, plan_id, date, station, output, defect_count
                FROM public.qc_error_log_sp
                WHERE plan_id = %s AND date = %s AND COALESCE(station, '') = COALESCE(%s, '')
                ORDER BY id DESC
                LIMIT 1
                """,
                (plan_id, date_str, station)
            )
            log = cur.fetchone()
            if not log:
                return {"exists": False}

            cur.execute(
                """
                SELECT sp_index, bo_phan_id, chi_tiet_id, ma_loi_id, mo_ta_loi_id, muc_do, lap_lai_3
                FROM public.qc_defect
                WHERE error_log_sp_id = %s
                ORDER BY sp_index ASC, id ASC
                """,
                (log["id"],)
            )
            rows = cur.fetchall()

            grouped: Dict[int, List[Dict]] = {}
            for r in rows:
                idx = r.get("sp_index") or 0
                grouped.setdefault(idx, []).append({
                    "bo_phan_id": r.get("bo_phan_id"),
                    "chi_tiet_id": r.get("chi_tiet_id"),
                    "ma_loi_id": r.get("ma_loi_id"),
                    "mo_ta_loi_id": r.get("mo_ta_loi_id"),
                    "muc_do": r.get("muc_do"),
                    "lap_lai_3": r.get("lap_lai_3"),
                })

            defect_products = [
                {"product_no": idx, "defects": grouped[idx]}
                for idx in sorted(grouped.keys())
                if idx
            ]

            return {
                "exists": True,
                "data": {
                    "output": log.get("output") or 0,
                    "defect_count": log.get("defect_count") or 0,
                    "date": str(log.get("date")) if log.get("date") else date_str,
                    "defect_products": defect_products,
                }
            }

@router.get("/qc-input/rework")
def qc_rework_page(request: Request):
    try:
        core.require_qc_input_user(request)
    except HTTPException as exc:
        if exc.status_code == 401:
            return RedirectResponse(url="/qc-login", status_code=303)
        raise
    ma_nv_cookie = request.cookies.get("ma_nv")
    if not ma_nv_cookie:
        return RedirectResponse(url="/qc-login", status_code=303)
    user_data = None
    ma_nv = core.decode_ma_nv_cookie(ma_nv_cookie)
    ma_nv_variants = core.generate_ma_nv_variants(ma_nv)
    with core.get_db_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT ma_nv, ho_ten as name, chuc_vu, don_vi, bo_phan
                FROM public.quality_employees
                WHERE ma_nv = ANY(%s)
                ORDER BY CASE WHEN ma_nv = %s THEN 0 ELSE 1 END
                LIMIT 1
                """,
                (ma_nv_variants, ma_nv)
            )
            user_data = cur.fetchone()
    if not user_data:
        return RedirectResponse(url="/qc-login", status_code=303)
        
    return core.templates.TemplateResponse("qc_rework_2.html", {"request": request, "user": user_data})


@router.get("/qc-input-2/rework")
def qc_rework_sp_page(request: Request):
    return RedirectResponse(url="/qc-input/rework", status_code=303)


@router.get("/api/qc/rework-2", dependencies=[Depends(core.require_qc_input_user)])
def api_qc_rework_sp(
    request: Request,
    date_str: str = Query(None),
    plan_id: Optional[int] = Query(None),
    station: Optional[str] = Query(None),
):
    """Danh sách SP lỗi cần tái chế.

    - Có plan_id: mọi SP lỗi của kế hoạch đó (trong XN của QC), lọc thêm theo cụm nếu có.
      Không lọc theo người lưu đầu tiên, để QC đổi ca/hỗ trợ cùng cụm vẫn thấy.
    - Không có plan_id (trang /qc-input/rework): chỉ các log do chính QC tạo.
    """
    user = core.require_qc_input_user(request)
    date_str = parse_qc_input_date(date_str)
    ma_nv_variants = core.generate_ma_nv_variants(user.get("ma_nv") or "")
    with core.get_db_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            params: List[Any] = [date_str, user['don_vi']]
            plan_where = ""
            if plan_id:
                plan_where = " AND e.plan_id = %s"
                params.append(plan_id)
                station_clean = (station or "").strip()
                if station_clean:
                    plan_where += " AND COALESCE(e.station, '') = %s"
                    params.append(station_clean)
            else:
                plan_where = " AND e.ma_nv = ANY(%s)"
                params.append(ma_nv_variants)
            cur.execute("""
                SELECT 
                    e.id as error_log_sp_id,
                    e.plan_id,
                    e.created_at,
                    p.ke_hoach,
                    p.ma_hang,
                    p.loai_hang,
                    d.sp_index,
                    COUNT(*) as defect_items,
                    BOOL_AND(COALESCE(d.rework_done, FALSE)) as rework_done,
                    ARRAY_AGG(DISTINCT CONCAT_WS(' - ', bp.ten_bo_phan, ct.ten_chi_tiet, ml.ten_ma)) as defect_list
                FROM public.qc_defect d
                JOIN public.qc_error_log_sp e ON e.id = d.error_log_sp_id
                JOIN public.prod_plan p ON e.plan_id = p.id
                LEFT JOIN public.dm_bo_phan bp ON d.bo_phan_id = bp.id
                LEFT JOIN public.dm_chi_tiet ct ON d.chi_tiet_id = ct.id
                LEFT JOIN public.dm_ma_loi ml ON d.ma_loi_id = ml.id
                WHERE e.date = %s
                  AND p.don_vi = %s
                  {plan_where}
                GROUP BY e.id, e.plan_id, e.created_at, p.ke_hoach, p.ma_hang, p.loai_hang, d.sp_index
                ORDER BY e.created_at ASC, d.sp_index ASC
            """.format(plan_where=plan_where), tuple(params))
            rows = cur.fetchall()
            for r in rows:
                if r.get('created_at'):
                    r['created_at'] = str(r['created_at'])
            return {"rows": rows}


@router.patch("/api/qc/rework-2/{log_id}/{sp_index}", dependencies=[Depends(core.require_qc_input_user)])
def api_update_rework_sp(log_id: int, sp_index: int, request: Request, body: Dict[str, Any] = Body(...)):
    user = core.require_qc_input_user(request)
    rework_done = bool(body.get("rework_done"))
    with core.get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE public.qc_defect
                SET rework_done = %s
                WHERE error_log_sp_id = %s
                  AND sp_index = %s
                  AND error_log_sp_id IN (
                      SELECT e.id FROM public.qc_error_log_sp e JOIN public.prod_plan p ON p.id = e.plan_id WHERE p.don_vi = %s
                  )
                """,
                (rework_done, log_id, sp_index, user['don_vi'])
            )
            updated_rows = cur.rowcount
        conn.commit()
    if not updated_rows:
        raise HTTPException(status_code=404, detail="Không tìm thấy sản phẩm lỗi để cập nhật")
    return {"status": "ok", "rework_done": rework_done}
