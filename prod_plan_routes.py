"""Kế hoạch sản xuất — CRUD, đồng bộ QTCN/XNDT/chuyền bệt/chuyền treo, output chuyền treo.

Tách từ main.py. Hàm/biến dùng chung (DB, đăng nhập, phân quyền, template, cấu hình...) vẫn ở main.py
và được gọi qua `core.<tên>` lúc chạy, nên test patch `main.<tên>` vẫn có hiệu lực.
"""
import json
import psycopg2
import psycopg2.extras
import psycopg2.pool
import re
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from typing import Any, List, Optional

from app_core import core

router = APIRouter()


def normalize_prod_plan_bo_phan_list(raw: Any) -> List[str]:
    if raw is None:
        return []
    if isinstance(raw, list):
        parts = [str(x) for x in raw]
    else:
        parts = re.split(r"[;,]|\s+và\s+|\s+&\s+|\s+\+\s+", str(raw), flags=re.IGNORECASE)

    seen = set()
    out: List[str] = []
    for item in parts:
        s = (item or "").strip()
        if not s:
            continue
        num_match = re.search(r"(\d+)", s)
        if s.isdigit():
            s = f"Tổ {int(s)}"
        elif s.lower().startswith(("tổ", "to")) and num_match:
            s = f"Tổ {int(num_match.group(1))}"
        s = re.sub(r"\s+", " ", s)
        if s not in seen:
            seen.add(s)
            out.append(s)
    return out


@router.get("/api/prod-plan")
def api_prod_plan_list(
    request: Request,
    don_vi: Optional[str] = Query(None),
    bo_phan: Optional[str] = Query(None),
    only_active: bool = Query(False),
):
    """List production plans within the account scope."""
    don_vi, user = core.resolve_qc_don_vi_scope(request, don_vi)

    with core.get_db_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            use_jsonb_bo_phan = core._detect_bo_phan_jsonb()

            clauses = []
            params = []
            if only_active or core.get_qc_role(user) == "QC":
                clauses.append("COALESCE(is_active, TRUE) = TRUE")
                clauses.append("is_finished = FALSE")
            if don_vi:
                clauses.append("don_vi = %s")
                params.append(don_vi)
            if bo_phan:
                if use_jsonb_bo_phan:
                    items = normalize_prod_plan_bo_phan_list(bo_phan)
                    if items:
                        or_clauses = []
                        for item in items:
                            or_clauses.append("bo_phan @> %s::jsonb")
                            params.append(json.dumps([item]))
                            # b_line's direct publisher may still send UDT - L1.
                            # Match the entire code within XNDT only (L1 != L10).
                            if re.fullmatch(r"Tổ \d+", item):
                                or_clauses.append("""(don_vi = 'XNDT' AND EXISTS (
                                    SELECT 1 FROM jsonb_array_elements_text(bo_phan) AS team(value)
                                    WHERE team.value ~* %s))""")
                                params.append(r"^\s*UDT\s*-\s*L0*" + item[3:] + r"\s*$")
                        clauses.append("(" + " OR ".join(or_clauses) + ")")
                else:
                    clauses.append("bo_phan = %s")
                    params.append(bo_phan)
            where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
            cur.execute(
                f"""
                SELECT id, ke_hoach, don_vi,
                       {
                           "COALESCE(NULLIF((SELECT string_agg(value, ', ') FROM jsonb_array_elements_text(COALESCE(bo_phan, '[]'::jsonb)) AS t(value)), ''), '')"
                           if use_jsonb_bo_phan
                           else "COALESCE(bo_phan, '')"
                       } AS bo_phan,
                       khach_hang, ma_hang,
                       loai_hang, ngay_rc, san_luong, mau, size, po_info, mono,
                       source_system, source_record_id, source_status, COALESCE(is_active, TRUE) AS is_active, is_finished, last_synced_at,
                       created_at, updated_at
                FROM public.prod_plan
                {where}
                ORDER BY ngay_rc DESC NULLS LAST, id DESC
                """,
                params
            )
            rows = cur.fetchall()
            # Serialize dates
            for r in rows:
                if r.get('don_vi') == 'XNDT':
                    from xndt_sync import normalize_teams
                    r['bo_phan'] = ', '.join(normalize_teams(r['bo_phan']))
                for k in ('ngay_rc', 'created_at', 'updated_at', 'last_synced_at'):
                    if r.get(k):
                        r[k] = str(r[k])
    return {"rows": rows}


@router.post("/api/prod-plan")
async def api_prod_plan_create(request: Request):
    """Create a new prod_plan entry."""
    user = core.require_plan_admin(request)
    body = await request.json()
    ke_hoach = (body.get("ke_hoach") or "").strip()
    don_vi = (body.get("don_vi") or "").strip()
    core.check_factory_access(user, don_vi)
    bo_phan_raw = (body.get("bo_phan") or "").strip()
    khach_hang = (body.get("khach_hang") or "").strip()
    ma_hang = (body.get("ma_hang") or "").strip()
    loai_hang = (body.get("loai_hang") or "").strip()
    ngay_rc = body.get("ngay_rc") or None
    san_luong = body.get("san_luong")
    mau = (body.get("mau") or "").strip()
    size = (body.get("size") or "").strip()
    po_info = core.normalize_po_info(body.get("po_info"))

    if not don_vi:
        raise HTTPException(status_code=400, detail="Đơn vị không được để trống")
    if don_vi not in core.DON_VI_OPTIONS:
        raise HTTPException(status_code=400, detail=f"Đơn vị không hợp lệ: {don_vi}")

    if not bo_phan_raw:
        raise HTTPException(status_code=400, detail="Bộ phận không được để trống")
    bo_phan_list = normalize_prod_plan_bo_phan_list(bo_phan_raw)
    if not bo_phan_list:
        raise HTTPException(status_code=400, detail="Bộ phận không hợp lệ")

    if san_luong is not None:
        try:
            san_luong = int(san_luong)
        except (ValueError, TypeError):
            raise HTTPException(status_code=400, detail="Sản lượng phải là số")

    with core.get_db_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                INSERT INTO public.prod_plan
                    (ke_hoach, don_vi, bo_phan, khach_hang, ma_hang, loai_hang,
                     ngay_rc, san_luong, mau, size, po_info)
                VALUES (%s, %s, %s::jsonb, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                RETURNING id
                """,
                (ke_hoach, don_vi, json.dumps(bo_phan_list), khach_hang, ma_hang, loai_hang,
                 ngay_rc, san_luong, mau, size, json.dumps(po_info))
            )
            new_id = cur.fetchone()["id"]
            conn.commit()
    return {"status": "ok", "id": new_id}


@router.patch("/api/prod-plan/{plan_id}")
async def api_prod_plan_update(plan_id: int, request: Request):
    """Update an existing prod_plan entry."""
    user = core.require_plan_admin(request)
    core.check_plan_access(user, plan_id)
    body = await request.json()
    if "don_vi" in body:
        if body["don_vi"] not in core.DON_VI_OPTIONS:
            raise HTTPException(status_code=400, detail="Xí nghiệp không hợp lệ")
        core.check_factory_access(user, body["don_vi"])

    # Build dynamic SET clause
    allowed_fields = ["ke_hoach", "don_vi", "khach_hang", "ma_hang",
                      "loai_hang", "ngay_rc", "san_luong", "mau", "size"]
    sets = ["updated_at = NOW()"]
    params = []

    if "is_finished" in body:
        if type(body["is_finished"]) is not bool:
            raise HTTPException(status_code=400, detail="Kết thúc phải là true hoặc false")
        sets.append("is_finished = %s")
        params.append(body["is_finished"])

    for field in allowed_fields:
        if field in body:
            val = body[field]
            if field == "don_vi" and val and val not in core.DON_VI_OPTIONS:
                raise HTTPException(status_code=400, detail=f"Đơn vị không hợp lệ: {val}")
            if field == "san_luong" and val is not None:
                try:
                    val = int(val)
                except (ValueError, TypeError):
                    raise HTTPException(status_code=400, detail="Sản lượng phải là số")
            if field == "ngay_rc" and val == "":
                val = None
            sets.append(f"{field} = %s")
            params.append(val)

    # Handle bo_phan separately (parse list)
    if "bo_phan" in body:
        bo_phan_raw = (body["bo_phan"] or "").strip()
        if bo_phan_raw:
            out = normalize_prod_plan_bo_phan_list(bo_phan_raw)
            if not out:
                raise HTTPException(status_code=400, detail="Bộ phận không hợp lệ")
            sets.append("bo_phan = %s::jsonb")
            params.append(json.dumps(out))

    if "po_info" in body:
        sets.append("po_info = %s::jsonb")
        params.append(json.dumps(core.normalize_po_info(body.get("po_info"))))

    params.append(plan_id)
    scope_clause = ""
    if core.is_qc_don_vi_scoped_role(user):
        scope_clause = " AND don_vi = %s"
        params.append(user['don_vi'])

    with core.get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"UPDATE public.prod_plan SET {', '.join(sets)} WHERE id = %s{scope_clause}",
                params
            )
            if cur.rowcount == 0:
                raise HTTPException(status_code=404, detail="Không tìm thấy kế hoạch")
            conn.commit()
    return {"status": "ok"}


@router.post("/api/prod-plan/sync-qtcn")
def api_prod_plan_sync_qtcn(request: Request):
    """Sync active XNV2 plans from prod_factory.qtcn_input into qlcl.prod_plan."""
    user = core.require_plan_admin(request)
    core.check_factory_access(user, "XNV2")
    return core.sync_qtcn_prod_plan()


@router.post("/api/prod-plan/sync-xndt")
def api_prod_plan_sync_xndt(request: Request):
    user = core.require_plan_admin(request)
    core.check_factory_access(user, "XNDT")
    from xndt_sync import sync
    try:
        return sync(core.get_db_connection, core.DATABASE_URL)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except HTTPException:
        raise
    except Exception:
        core.logger.exception("XNDT PostgreSQL sync failed")
        raise HTTPException(status_code=502, detail="Không đồng bộ được b_line. Kiểm tra kết nối PostgreSQL và nhật ký máy chủ.")


@router.post("/api/prod-plan/sync-flat-line")
def api_prod_plan_sync_flat_line(
    request: Request,
    don_vi: Optional[str] = Query(None),
    all_factories: bool = Query(False),
):
    """Sync plans marked `Chuyền bệt` from the configured factory Google Sheet."""
    user = core.require_plan_admin(request)
    if all_factories:
        if core.get_qc_role(user) != "QA_ADMIN":
            raise HTTPException(status_code=403, detail="Chỉ QA_ADMIN được đồng bộ tất cả Xí nghiệp")
        return core.sync_all_flat_line_prod_plans()
    requested_don_vi = core.normalize_flat_line_don_vi(don_vi or user.get("don_vi"))
    if not requested_don_vi:
        raise HTTPException(status_code=422, detail="Thiếu đơn vị cần đồng bộ")
    core.check_factory_access(user, requested_don_vi)
    try:
        return core.sync_flat_line_prod_plan(requested_don_vi)
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        core.logger.exception("Flat-line Sheet sync failed for %s", requested_don_vi)
        raise HTTPException(status_code=502, detail=f"Không đọc được Google Sheet Chuyền bệt: {exc}")


@router.post("/api/prod-plan/sync-hanging-line")
def api_prod_plan_sync_hanging_line(request: Request):
    """Sync plans from hanging-line SQL Server (tPlanMaster) into qlcl.prod_plan.
    Dùng khi QLCL và hanging line chạy cùng máy (local dev).
    """
    user = core.require_plan_admin(request)
    core.check_factory_access(user, core.HANGING_LINE_DON_VI)
    result = core.sync_hanging_line_prod_plan()
    if result.get("status") == "error":
        raise HTTPException(status_code=500, detail=result.get("detail", "Lỗi đồng bộ"))
    return result


@router.post("/api/prod-plan/push-from-hl")
def api_push_from_hanging_line(request: Request, payload: dict):
    """Nhận danh sách kế hoạch JSON từ hanging line app và upsert vào prod_plan.

    Dùng khi QLCL chạy trên server trung tâm (không thể kết nối trực tiếp SQL Server XN).
    Auth: header X-API-Key phải khớp QLCL_API_KEY (bỏ qua nếu QLCL_API_KEY chưa set).

    Body: {"don_vi": "XN3", "plans": [{guid, mono, ke_hoach, line_no, style_no,
                                        customer, loai_hang, first_hang, san_luong}, ...]}
    """
    # Kiểm tra API key nếu đã cấu hình
    if not core._PUSH_API_KEY or request.headers.get("X-API-Key") != core._PUSH_API_KEY:
        raise HTTPException(status_code=403, detail="API key không hợp lệ")

    don_vi = str(payload.get("don_vi") or "").strip()
    plans = payload.get("plans") or []
    if not don_vi:
        raise HTTPException(status_code=422, detail="Thiếu don_vi")

    inserted = updated = skipped = 0
    warnings: list[str] = []

    with core.get_db_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            for row in plans:
                mono = str(row.get("mono") or "").strip()
                if not mono:
                    skipped += 1
                    warnings.append("Bỏ qua 1 plan vì thiếu mono")
                    continue

                guid_str       = str(row.get("guid") or mono)
                ke_hoach       = str(row.get("ke_hoach") or f"HL-{mono}")
                line_no        = row.get("line_no") or 0
                bo_phan_list   = [f"Tổ {line_no}"] if line_no else []
                style_no       = str(row.get("style_no") or "").strip()
                customer       = str(row.get("customer") or "").strip()
                loai_hang      = str(row.get("loai_hang") or "").strip() or None
                first_hang     = row.get("first_hang")  # YYYY-MM-DD string hoặc None
                san_luong      = row.get("san_luong") or 0

                # UPDATE by (source_system, source_record_id)
                cur.execute(
                    """
                    UPDATE public.prod_plan
                    SET ke_hoach = %s, don_vi = %s, bo_phan = %s::jsonb,
                        khach_hang = %s, ma_hang = %s,
                        loai_hang = COALESCE(%s, loai_hang),
                        ngay_rc = %s, san_luong = %s, mono = %s,
                        source_status = 'active', is_active = TRUE,
                        last_synced_at = NOW(), updated_at = NOW()
                    WHERE source_system = %s AND source_record_id = %s
                    """,
                    (ke_hoach, don_vi, json.dumps(bo_phan_list),
                     customer, style_no, loai_hang, first_hang, san_luong, mono,
                     core.HL_SOURCE_SYSTEM, guid_str),
                )
                if cur.rowcount:
                    updated += 1
                    continue

                # UPDATE by mono (fallback — plan đã nhập tay chưa có source tracking)
                cur.execute(
                    """
                    UPDATE public.prod_plan
                    SET source_system = %s, source_record_id = %s,
                        ke_hoach = %s, don_vi = %s, bo_phan = %s::jsonb,
                        khach_hang = %s, ma_hang = %s,
                        loai_hang = COALESCE(%s, loai_hang),
                        ngay_rc = %s, san_luong = %s,
                        source_status = 'active', is_active = TRUE,
                        last_synced_at = NOW(), updated_at = NOW()
                    WHERE mono = %s
                    """,
                    (core.HL_SOURCE_SYSTEM, guid_str, ke_hoach, don_vi,
                     json.dumps(bo_phan_list), customer, style_no, loai_hang,
                     first_hang, san_luong, mono),
                )
                if cur.rowcount:
                    updated += 1
                    continue

                # INSERT mới
                cur.execute(
                    """
                    INSERT INTO public.prod_plan
                        (ke_hoach, don_vi, bo_phan, khach_hang, ma_hang, loai_hang,
                         ngay_rc, san_luong, mau, size, mono,
                         source_system, source_record_id, source_status, is_active, last_synced_at)
                    VALUES (%s, %s, %s::jsonb, %s, %s, %s, %s, %s, '', '', %s, %s, %s, 'active', TRUE, NOW())
                    """,
                    (ke_hoach, don_vi, json.dumps(bo_phan_list),
                     customer, style_no, loai_hang, first_hang, san_luong,
                     mono, core.HL_SOURCE_SYSTEM, guid_str),
                )
                inserted += 1

        conn.commit()

    return {
        "status": "ok",
        "don_vi": don_vi,
        "inserted": inserted,
        "updated": updated,
        "skipped": skipped,
        "warnings": warnings[:20],
    }


@router.get("/api/qc/hanging-output", dependencies=[Depends(core.require_plan_reader)])
def api_qc_hanging_output(
    plan_id: int = Query(...),
    date_str: str = Query(..., alias="date"),
):
    """Sản lượng ra chuyền từ MES (đã được push từ hanging_app)."""
    with core.get_db_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT id, mono, source_system, source_record_id, don_vi FROM public.prod_plan WHERE id = %s",
                (plan_id,),
            )
            plan = cur.fetchone()
            if plan and plan.get('source_system') == core.FLAT_LINE_SOURCE_SYSTEM:
                from flat_output import get_output
                return get_output(cur, plan, date_str)
            if not plan or plan.get("source_system") != core.HL_SOURCE_SYSTEM:
                return {"qty": 0, "available": False}

            mono = (plan.get("mono") or "").strip()
            if not mono:
                return {"qty": 0, "available": False}

            cur.execute(
                """
                SELECT qty FROM public.qc_hanging_output
                WHERE mono = %s AND report_date = %s AND don_vi = %s
                ORDER BY synced_at DESC LIMIT 1
                """,
                (mono, date_str, plan['don_vi']),
            )
            row = cur.fetchone()
            return {"qty": int(row["qty"]) if row else 0, "available": True}


@router.post("/api/qc/hanging-output/push")
def api_qc_hanging_output_push(request: Request, payload: dict):
    """Nhận batch output từ hanging_app. Auth: X-API-Key.

    Body: {"don_vi": "XN2", "date": "2026-08-19",
           "outputs": [{"mono": "...", "qty": 123}, ...]}
    """
    if not core._PUSH_API_KEY or request.headers.get("X-API-Key") != core._PUSH_API_KEY:
        raise HTTPException(status_code=403, detail="API key không hợp lệ")

    don_vi = str(payload.get("don_vi") or "").strip()
    date_str = str(payload.get("date") or "").strip()
    outputs = payload.get("outputs") or []
    if not don_vi or not date_str:
        raise HTTPException(status_code=422, detail="Thiếu don_vi hoặc date")

    upserted = 0
    with core.get_db_connection() as conn:
        with conn.cursor() as cur:
            for item in outputs:
                mono = str(item.get("mono") or "").strip()
                qty = int(item.get("qty") or 0)
                if not mono:
                    continue
                cur.execute(
                    """
                    INSERT INTO public.qc_hanging_output (don_vi, mono, report_date, qty, synced_at)
                    VALUES (%s, %s, %s, %s, NOW())
                    ON CONFLICT (don_vi, mono, report_date)
                    DO UPDATE SET qty = EXCLUDED.qty, synced_at = NOW()
                    """,
                    (don_vi, mono, date_str, qty),
                )
                upserted += 1
        conn.commit()

    return {"status": "ok", "upserted": upserted}


@router.delete("/api/prod-plan/{plan_id}")
def api_prod_plan_delete(plan_id: int, request: Request):
    """Delete a prod_plan entry."""
    user = core.require_plan_admin(request)
    core.check_plan_access(user, plan_id)
    with core.get_db_connection() as conn:
        with conn.cursor() as cur:
            if core.is_qc_don_vi_scoped_role(user):
                cur.execute("DELETE FROM public.prod_plan WHERE id = %s AND don_vi = %s", (plan_id, user['don_vi']))
            else:
                cur.execute("DELETE FROM public.prod_plan WHERE id = %s", (plan_id,))
            if cur.rowcount == 0:
                raise HTTPException(status_code=404, detail="Không tìm thấy kế hoạch")
            conn.commit()
    return {"status": "ok"}
