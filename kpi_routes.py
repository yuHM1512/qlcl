"""KPI — trang KPI, nhập liệu KPI, tổng hợp tháng/quý, lỗi KPI, HĐKP KPI, upload ảnh.

Tách từ main.py. Hàm/biến dùng chung (DB, đăng nhập, phân quyền, template, cấu hình...) vẫn ở main.py
và được gọi qua `core.<tên>` lúc chạy, nên test patch `main.<tên>` vẫn có hiệu lực.
"""
import os
import psycopg2
import psycopg2.extras
import psycopg2.pool
import shutil
from datetime import date, datetime
from fastapi import APIRouter, File, HTTPException, Path, Query, Request, UploadFile
from fastapi.responses import JSONResponse, RedirectResponse, Response
from pathlib import Path as PathLib
from typing import Any, Dict, List, Optional, Tuple

from app_core import core

router = APIRouter()


@router.get("/kpi")
def kpi_page(request: Request):
    if not core.get_authenticated_user(request):
        return RedirectResponse(url="/login", status_code=303)
    return core.templates.TemplateResponse("kpi.html", {"request": request})


@router.get("/view-kpi")
def view_kpi(request: Request):
    if not core.get_authenticated_user(request):
        return RedirectResponse(url="/login", status_code=303)
    return core.templates.TemplateResponse("view_kpi.html", {"request": request})


QLCL_DASHBOARD_URL = "https://kpi.hachibavn.com"


@router.get("/view-kpi-dashboard")
async def view_kpi_dashboard(request: Request):
    """Render the embedded QLCL dashboard with selected cards hidden.

    The dashboard is hosted on another origin, so the parent page cannot
    manipulate its DOM directly. Serving the HTML through this endpoint lets
    us apply the requested presentation change while keeping the dashboard's
    own JavaScript and data endpoints intact.
    """
    if not core.get_authenticated_user(request):
        return RedirectResponse(url="/login", status_code=303)

    import httpx

    async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
        upstream = await client.get(f"{QLCL_DASHBOARD_URL}/qlcl")
    if upstream.status_code >= 400:
        return Response(
            content="Không thể tải dashboard KPI.",
            status_code=502,
            media_type="text/plain; charset=utf-8",
        )

    hide_cards_script = """
<script>
document.addEventListener("DOMContentLoaded", function () {
    const qlcl153 = document.getElementById("qlcl153-value");
    qlcl153 && qlcl153.closest(".col-md-3")?.remove();

    const qlcl152 = document.getElementById("qlcl152-value");
    const qlcl152Column = qlcl152?.closest(".col-md-3");
    qlcl152Column?.classList.remove("col-md-3");
    qlcl152Column?.classList.add("col-md-6");

    const qlcl158 = document.getElementById("qlcl158-target");
    qlcl158 && qlcl158.closest(".chart-container")?.remove();
});
</script>
"""
    qa_filter_markup = """
                    <div class="d-flex align-items-center gap-2 mt-2 mt-md-0">
                        <label for="qlcl-qa-filter" class="form-label mb-0 fw-semibold">
                            <i class="fas fa-user-check me-2"></i>Lọc theo QA
                        </label>
                        <select class="form-select form-select-sm w-auto" id="qlcl-qa-filter">
                            <option value="">Tất cả</option>
                            <option value="QAPL">QAPL</option>
                            <option value="QANL">QANL</option>
                            <option value="QAQT">QAQT</option>
                        </select>
                    </div>
"""
    html = upstream.text.replace(
        "QLCL150, 151, 152, 153, 154, 158",
        "QLCL150, 151, 152, 153, 154, 155",
    )
    html = html.replace(
        'src="/static/js/qlcl.js"',
        f'src="{QLCL_DASHBOARD_URL}/static/js/qlcl.js"',
    )
    html = html.replace(
        '</div>\n                <p class="text-muted small mb-0 mt-2">',
        f'</div>{qa_filter_markup}\n                <p class="text-muted small mb-0 mt-2">',
        1,
    )
    html = html.replace("</body>", f"{hide_cards_script}</body>")
    return Response(content=html, media_type="text/html; charset=utf-8")


@router.get("/api/qlcl/{endpoint:path}")
async def proxy_qlcl_dashboard_api(endpoint: str, request: Request):
    """Proxy the embedded dashboard's API calls through the local origin."""
    if not core.get_authenticated_user(request):
        return JSONResponse({"detail": "Not authenticated"}, status_code=401)

    import httpx

    query = list(request.query_params.multi_items())
    async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
        upstream = await client.get(
            f"{QLCL_DASHBOARD_URL}/api/qlcl/{endpoint}",
            params=query,
            headers={"Accept": "application/json"},
        )
    content_type = upstream.headers.get("content-type", "application/json")
    return Response(
        content=upstream.content,
        status_code=upstream.status_code,
        media_type=content_type.split(";", 1)[0],
    )


@router.get("/dashboard-summary")
def dashboard_summary(request: Request):
    if not core.get_authenticated_user(request):
        return RedirectResponse(url="/login", status_code=303)
    return core.templates.TemplateResponse("dashboard_summary.html", {"request": request})


@router.get("/kpi-input")
def kpi_input(request: Request):
    ma_nv_cookie = request.cookies.get("ma_nv")
    if not ma_nv_cookie:
        return RedirectResponse(url="/login", status_code=303)
    ma_nv = core.decode_ma_nv_cookie(ma_nv_cookie)
    ma_nv_variants = core.generate_ma_nv_variants(ma_nv)

    with core.get_db_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT ma_nv, ho_ten, chuc_vu
                FROM public.quality_employees
                WHERE ma_nv = ANY(%s)
                ORDER BY CASE WHEN ma_nv = %s THEN 0 ELSE 1 END
                LIMIT 1
                """,
                (ma_nv_variants, ma_nv)
            )
            user_row = cur.fetchone()
            if not user_row:
                response = RedirectResponse(url="/login", status_code=303)
                response.delete_cookie("ma_nv")
                return response

    return core.templates.TemplateResponse("kpi_input.html", {"request": request, "step": "form", "user": dict(user_row)})


@router.get("/api/tasks")
def api_tasks(request: Request):
    ma_nv_cookie = request.cookies.get("ma_nv")
    if not ma_nv_cookie:
        raise HTTPException(status_code=401, detail="Chưa đăng nhập")
    ma_nv = core.decode_ma_nv_cookie(ma_nv_cookie)
    ma_nv_variants = core.generate_ma_nv_variants(ma_nv)
    with core.get_db_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT chuc_vu
                FROM public.quality_employees
                WHERE ma_nv = ANY(%s)
                ORDER BY CASE WHEN ma_nv = %s THEN 0 ELSE 1 END
                LIMIT 1
                """,
                (ma_nv_variants, ma_nv)
            )
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=403, detail="Không tìm thấy nhân viên")
            chuc_vu = row["chuc_vu"]
            cur.execute("SELECT task_name FROM public.tasks_qa WHERE chuc_vu=%s ORDER BY task_name", (chuc_vu,))
            tasks = [r["task_name"] for r in cur.fetchall()]
    return {"chuc_vu": chuc_vu, "tasks": tasks}


@router.post("/api/input")
async def api_input(request: Request):
    ma_nv_cookie = request.cookies.get("ma_nv")
    if not ma_nv_cookie:
        raise HTTPException(status_code=401, detail="Chưa đăng nhập")
    ma_nv = core.decode_ma_nv_cookie(ma_nv_cookie)
    ma_nv_variants = core.generate_ma_nv_variants(ma_nv)
    payload = await request.json()
    try:
        from_date_str = payload.get("from_date")
        to_date_str = payload.get("to_date")
        items = payload.get("items", [])
        if not from_date_str or not to_date_str or not items:
            raise ValueError("Thiếu dữ liệu bắt buộc")

        from_date_val = date.fromisoformat(from_date_str)
        to_date_val = date.fromisoformat(to_date_str)
        if to_date_val < from_date_val:
            raise ValueError("Khoảng thời gian không hợp lệ")

        for it in items:
            name = (it.get("task_name") or "").strip()
            qty = int(it.get("thuc_hien"))
            if not name:
                raise ValueError("Thiếu tên task")
            if qty < 0:
                raise ValueError("Số lượng phải >= 0")
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    with core.get_db_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT ma_nv, chuc_vu
                FROM public.quality_employees
                WHERE ma_nv = ANY(%s)
                ORDER BY CASE WHEN ma_nv = %s THEN 0 ELSE 1 END
                LIMIT 1
                """,
                (ma_nv_variants, ma_nv)
            )
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=403, detail="Không tìm thấy nhân viên")
            ma_nv_db = row["ma_nv"]
            chuc_vu = row["chuc_vu"]

            insert_sql = (
                "INSERT INTO public.input_qa (ma_nv, chuc_vu, from_date, to_date, task_name, thuc_hien)"
                " VALUES (%s, %s, %s, %s, %s, %s)"
                " RETURNING id"
            )
            ids: List[int] = []
            for it in items:
                cur.execute(
                    insert_sql,
                    (
                        ma_nv_db,
                        chuc_vu,
                        from_date_val,
                        to_date_val,
                        it["task_name"],
                        int(it["thuc_hien"]),
                    ),
                )
                ids.append(cur.fetchone()["id"])
            conn.commit()

    return {"status": "ok", "inserted": len(ids), "ids": ids}


@router.post("/api/input-error")
async def api_input_error(request: Request):
    ma_nv_cookie = request.cookies.get("ma_nv")
    if not ma_nv_cookie:
        raise HTTPException(status_code=401, detail="Chưa đăng nhập")
    ma_nv = core.decode_ma_nv_cookie(ma_nv_cookie)
    ma_nv_variants = core.generate_ma_nv_variants(ma_nv)

    payload = await request.json()
    # Optional fields allowed; minimal validation
    ngay_ghi_nhan = payload.get("ngay_ghi_nhan")  # ISO date or empty
    task_name = payload.get("task_name")
    phan_loai_loi = payload.get("phan_loai_loi")
    mo_ta = payload.get("mo_ta")
    muc_do_anh_huong = core.normalize_kpi_impact_level(payload.get("muc_do_anh_huong"))
    huong_giai_quyet = payload.get("huong_giai_quyet")

    with core.get_db_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            # Resolve chuc_vu
            cur.execute(
                """
                SELECT ma_nv, chuc_vu
                FROM public.quality_employees
                WHERE ma_nv = ANY(%s)
                ORDER BY CASE WHEN ma_nv = %s THEN 0 ELSE 1 END
                LIMIT 1
                """,
                (ma_nv_variants, ma_nv)
            )
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=403, detail="Không tìm thấy nhân viên")
            ma_nv_db = row["ma_nv"]
            chuc_vu = row["chuc_vu"]

            cur.execute(
                """
                INSERT INTO public.input_error (
                    ma_nv, chuc_vu, ngay_ghi_nhan, task_name, phan_loai_loi, mo_ta,
                    muc_do_anh_huong, huong_giai_quyet
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s
                ) RETURNING id
                """,
                (
                    ma_nv_db,
                    chuc_vu,
                    date.fromisoformat(ngay_ghi_nhan) if ngay_ghi_nhan else None,
                    task_name,
                    phan_loai_loi,
                    mo_ta,
                    muc_do_anh_huong,
                    huong_giai_quyet,
                ),
            )
            new_id = cur.fetchone()["id"]
            conn.commit()

    return {"status": "ok", "id": new_id}


@router.get("/api/input-edit")
def api_input_edit(
    request: Request,
    from_date: Optional[str] = Query(None, description="Lọc từ ngày (YYYY-MM-DD)"),
    to_date: Optional[str] = Query(None, description="Lọc đến ngày (YYYY-MM-DD)")
):
    """Lấy danh sách dữ liệu input_qa của người đăng nhập, sắp xếp từ mới nhất đến cũ nhất.
    Có thể lọc theo khoảng thời gian (from_date, to_date) - lọc các bản ghi có khoảng thời gian giao với khoảng filter.
    """
    ma_nv_cookie = request.cookies.get("ma_nv")
    if not ma_nv_cookie:
        raise HTTPException(status_code=401, detail="Chưa đăng nhập")
    ma_nv = core.decode_ma_nv_cookie(ma_nv_cookie)
    ma_nv_variants = core.generate_ma_nv_variants(ma_nv)
    
    # Parse filter dates
    from_date_val = None
    to_date_val = None
    if from_date:
        try:
            from_date_val = date.fromisoformat(from_date)
        except ValueError:
            raise HTTPException(status_code=400, detail="Định dạng from_date không hợp lệ (YYYY-MM-DD)")
    if to_date:
        try:
            to_date_val = date.fromisoformat(to_date)
        except ValueError:
            raise HTTPException(status_code=400, detail="Định dạng to_date không hợp lệ (YYYY-MM-DD)")
    
    if from_date_val and to_date_val and to_date_val < from_date_val:
        raise HTTPException(status_code=400, detail="Ngày Đến phải >= Ngày Từ")
    
    with core.get_db_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            # Xác định ma_nv chính xác từ database
            cur.execute(
                """
                SELECT ma_nv
                FROM public.quality_employees
                WHERE ma_nv = ANY(%s)
                ORDER BY CASE WHEN ma_nv = %s THEN 0 ELSE 1 END
                LIMIT 1
                """,
                (ma_nv_variants, ma_nv)
            )
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=403, detail="Không tìm thấy nhân viên")
            ma_nv_db = row["ma_nv"]
            
            # Xây dựng query với filter theo ngày
            # Lọc các bản ghi có khoảng thời gian giao với khoảng filter
            # (from_date <= record.to_date AND to_date >= record.from_date)
            query = """
                SELECT id, from_date, to_date, task_name, thuc_hien, created_at
                FROM public.input_qa
                WHERE ma_nv = %s
            """
            params = [ma_nv_db]
            
            if from_date_val and to_date_val:
                # Cả hai ngày đều có: lọc các bản ghi có khoảng thời gian giao với khoảng filter
                query += " AND from_date <= %s AND to_date >= %s"
                params.extend([to_date_val, from_date_val])
            elif from_date_val:
                # Chỉ có from_date: lọc các bản ghi có to_date >= from_date
                query += " AND to_date >= %s"
                params.append(from_date_val)
            elif to_date_val:
                # Chỉ có to_date: lọc các bản ghi có from_date <= to_date
                query += " AND from_date <= %s"
                params.append(to_date_val)
            
            query += " ORDER BY created_at DESC"
            
            cur.execute(query, tuple(params))
            items = cur.fetchall()
            
            # Chuyển đổi date và datetime thành string
            result_items = []
            for item in items:
                result_items.append({
                    "id": item["id"],
                    "from_date": item["from_date"].isoformat() if item["from_date"] else None,
                    "to_date": item["to_date"].isoformat() if item["to_date"] else None,
                    "task_name": item["task_name"],
                    "thuc_hien": item["thuc_hien"],
                    "created_at": item["created_at"].isoformat() if item["created_at"] else None
                })
    
    return {"status": "ok", "items": result_items}


@router.put("/api/input-edit/{item_id}")
async def api_input_edit_update(item_id: int, request: Request):
    """Cập nhật dữ liệu input_qa theo ID"""
    ma_nv_cookie = request.cookies.get("ma_nv")
    if not ma_nv_cookie:
        raise HTTPException(status_code=401, detail="Chưa đăng nhập")
    ma_nv = core.decode_ma_nv_cookie(ma_nv_cookie)
    ma_nv_variants = core.generate_ma_nv_variants(ma_nv)
    
    payload = await request.json()
    try:
        from_date_str = payload.get("from_date")
        to_date_str = payload.get("to_date")
        task_name = payload.get("task_name")
        thuc_hien = payload.get("thuc_hien")
        
        if not from_date_str or not to_date_str or not task_name:
            raise ValueError("Thiếu dữ liệu bắt buộc")
        
        from_date_val = date.fromisoformat(from_date_str)
        to_date_val = date.fromisoformat(to_date_str)
        if to_date_val < from_date_val:
            raise ValueError("Khoảng thời gian không hợp lệ")
        
        task_name = task_name.strip()
        if not task_name:
            raise ValueError("Tên công việc không được để trống")
        
        thuc_hien = int(thuc_hien) if thuc_hien is not None else 0
        if thuc_hien < 0:
            raise ValueError("Số lượng phải >= 0")
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    
    with core.get_db_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            # Xác định ma_nv chính xác từ database
            cur.execute(
                """
                SELECT ma_nv
                FROM public.quality_employees
                WHERE ma_nv = ANY(%s)
                ORDER BY CASE WHEN ma_nv = %s THEN 0 ELSE 1 END
                LIMIT 1
                """,
                (ma_nv_variants, ma_nv)
            )
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=403, detail="Không tìm thấy nhân viên")
            ma_nv_db = row["ma_nv"]
            
            # Kiểm tra xem record có thuộc về người đăng nhập không
            cur.execute(
                """
                SELECT id, ma_nv
                FROM public.input_qa
                WHERE id = %s
                """,
                (item_id,)
            )
            record = cur.fetchone()
            if not record:
                raise HTTPException(status_code=404, detail="Không tìm thấy bản ghi")
            
            if record["ma_nv"] != ma_nv_db:
                raise HTTPException(status_code=403, detail="Bạn không có quyền chỉnh sửa bản ghi này")
            
            # Cập nhật dữ liệu
            cur.execute(
                """
                UPDATE public.input_qa
                SET from_date = %s, to_date = %s, task_name = %s, thuc_hien = %s
                WHERE id = %s AND ma_nv = %s
                RETURNING id, from_date, to_date, task_name, thuc_hien, created_at
                """,
                (from_date_val, to_date_val, task_name, thuc_hien, item_id, ma_nv_db)
            )
            updated = cur.fetchone()
            if not updated:
                raise HTTPException(status_code=500, detail="Không thể cập nhật dữ liệu")
            conn.commit()
            
            return {
                "status": "ok",
                "id": updated["id"],
                "from_date": updated["from_date"].isoformat() if updated["from_date"] else None,
                "to_date": updated["to_date"].isoformat() if updated["to_date"] else None,
                "task_name": updated["task_name"],
                "thuc_hien": updated["thuc_hien"],
                "created_at": updated["created_at"].isoformat() if updated["created_at"] else None
            }


@router.get("/api/summary")
def api_summary(
    chuc_vu: str = Query(..., pattern="^(QAPL|QANL|QAQT)$"),
    week: Optional[int] = Query(None, ge=1, le=53),
    year: Optional[int] = Query(None, ge=2000, le=2100)
):
    week_clause = ""
    params_qa = [chuc_vu]
    if week is not None:
        week_clause += " AND to_char(GREATEST(from_date, to_date), 'IW') = %s"
        params_qa.append(f"{int(week):02d}")
    if year is not None:
        week_clause += " AND to_char(GREATEST(from_date, to_date), 'YYYY') = %s"
        params_qa.append(str(year))

    err_clause = ""
    err_params = [chuc_vu]
    if week is not None:
        err_clause += " AND to_char(ngay_ghi_nhan, 'IW') = %s"
        err_params.append(f"{int(week):02d}")
    if year is not None:
        err_clause += " AND to_char(ngay_ghi_nhan, 'YYYY') = %s"
        err_params.append(str(year))

    with core.get_db_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT task_name FROM public.tasks_qa WHERE chuc_vu=%s ORDER BY task_name", (chuc_vu,))
            tasks = [r["task_name"] for r in cur.fetchall()]

            cur.execute(
                f"""
                WITH qa AS (
                  SELECT 
                    to_char(GREATEST(from_date, to_date), '"W"IW-YYYY') AS week_year,
                    ma_nv,
                    task_name,
                    SUM(thuc_hien) AS thuc_hien
                  FROM public.input_qa
                  WHERE chuc_vu = %s
                    AND from_date IS NOT NULL
                    AND to_date IS NOT NULL
                  {week_clause}
                  GROUP BY 1,2,3
                )
                SELECT qa.week_year, d.ma_nv, d.ho_ten, qa.task_name, qa.thuc_hien
                FROM qa
                JOIN public.quality_employees d ON d.ma_nv = qa.ma_nv
                WHERE d.chuc_vu = %s
                  AND qa.week_year IS NOT NULL
                ORDER BY qa.week_year, d.ma_nv, qa.task_name
                """,
                (*params_qa, chuc_vu),
            )
            qa_rows = cur.fetchall()

            cur.execute(
                f"""
                SELECT 
                  to_char(ngay_ghi_nhan, '"W"IW-YYYY') AS week_year,
                  e.ma_nv,
                  e.task_name,
                  COUNT(*) AS sai_sot
                FROM public.input_error e
                JOIN public.quality_employees d ON d.ma_nv = e.ma_nv
                WHERE d.chuc_vu = %s
                  AND e.ngay_ghi_nhan IS NOT NULL
                  AND COALESCE(e.ghi_chu, '') NOT LIKE 'Nguồn Final API%%'
                  {err_clause}
                GROUP BY 1,2,3
                HAVING to_char(ngay_ghi_nhan, '"W"IW-YYYY') IS NOT NULL
                ORDER BY 1,2,3
                """,
                tuple(err_params),
            )
            err_rows = cur.fetchall()

    rows_map: Dict[Tuple[str, str], Dict] = {}
    for r in qa_rows:
        if not r.get("week_year") or not r.get("ma_nv"):
            continue
        key = (r["week_year"], r["ma_nv"])
        entry = rows_map.setdefault(key, {"week_year": r["week_year"], "ma_nv": r["ma_nv"], "ho_ten": r.get("ho_ten"), "metrics": {}})
        entry["metrics"].setdefault(r["task_name"], {"thuc_hien": 0, "sai_sot": 0})
        entry["metrics"][r["task_name"]]["thuc_hien"] += int(r["thuc_hien"] or 0)
    
    for r in err_rows:
        if not r.get("week_year") or not r.get("ma_nv"):
            continue
        key = (r["week_year"], r["ma_nv"])
        entry = rows_map.setdefault(key, {"week_year": r["week_year"], "ma_nv": r["ma_nv"], "ho_ten": None, "metrics": {}})
        entry["metrics"].setdefault(r["task_name"], {"thuc_hien": 0, "sai_sot": 0})
        entry["metrics"][r["task_name"]]["sai_sot"] += int(r["sai_sot"] or 0)

    rows = list(rows_map.values())
    rows.sort(key=lambda x: (
        x.get("week_year") or "",
        x.get("ma_nv") or ""
    ))

    return {"tasks": tasks, "rows": rows}


def _normalize_month_filter(month_str: Optional[str]) -> Optional[str]:
    if not month_str:
        return None
    month_str = month_str.strip()
    for fmt in ("%y-%m", "%Y-%m"):
        try:
            dt = datetime.strptime(month_str, fmt)
            return dt.strftime("%Y-%m")
        except ValueError:
            continue
    return None


@router.get("/api/summary/monthly")
def api_summary_monthly(
    chuc_vu: str = Query(..., pattern="^(QAPL|QANL|QAQT)$"),
    month: Optional[str] = Query(None)
):
    month_filter = _normalize_month_filter(month)

    with core.get_db_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT task_name FROM public.tasks_qa WHERE chuc_vu=%s ORDER BY task_name", (chuc_vu,))
            tasks = [r["task_name"] for r in cur.fetchall()]

            qa_params = [chuc_vu]
            qa_month_clause = ""
            if month_filter:
                qa_month_clause = " AND to_char(from_date, 'YYYY-MM') = %s"
                qa_params.append(month_filter)

            cur.execute(
                f"""
                WITH qa AS (
                  SELECT 
                    to_char(from_date, 'YYYY-MM') AS month_key,
                    ma_nv,
                    task_name,
                    SUM(thuc_hien) AS thuc_hien
                  FROM public.input_qa
                  WHERE chuc_vu = %s
                    AND from_date IS NOT NULL
                  {qa_month_clause}
                  GROUP BY 1,2,3
                )
                SELECT qa.month_key, d.ma_nv, d.ho_ten, qa.task_name, qa.thuc_hien
                FROM qa
                JOIN public.quality_employees d ON d.ma_nv = qa.ma_nv
                WHERE d.chuc_vu = %s
                  AND qa.month_key IS NOT NULL
                ORDER BY qa.month_key, d.ma_nv, qa.task_name
                """,
                (*qa_params, chuc_vu),
            )
            qa_rows = cur.fetchall()

            err_params = [chuc_vu]
            err_month_clause = ""
            if month_filter:
                err_month_clause = " AND to_char(ngay_ghi_nhan, 'YYYY-MM') = %s"
                err_params.append(month_filter)

            cur.execute(
                f"""
                SELECT 
                  to_char(ngay_ghi_nhan, 'YYYY-MM') AS month_key,
                  e.ma_nv,
                  e.task_name,
                  COUNT(*) AS sai_sot
                FROM public.input_error e
                JOIN public.quality_employees d ON d.ma_nv = e.ma_nv
                WHERE d.chuc_vu = %s
                  AND e.ngay_ghi_nhan IS NOT NULL
                  AND COALESCE(e.ghi_chu, '') NOT LIKE 'Nguồn Final API%%'
                  {err_month_clause}
                GROUP BY 1,2,3
                HAVING to_char(ngay_ghi_nhan, 'YYYY-MM') IS NOT NULL
                ORDER BY 1,2,3
                """,
                tuple(err_params),
            )
            err_rows = cur.fetchall()

    rows_map: Dict[Tuple[str, str], Dict] = {}

    def convert_month_key(month_key: Optional[str]) -> Tuple[str, str]:
        if not month_key:
            return "", ""
        try:
            dt = datetime.strptime(month_key, "%Y-%m")
            label = dt.strftime("%y-%m")
            iso_first_day = dt.replace(day=1).date().isoformat()
            return label, iso_first_day
        except ValueError:
            return month_key, ""

    for r in qa_rows:
        month_label, first_day = convert_month_key(r.get("month_key"))
        if not month_label or not r.get("ma_nv"):
            continue
        key = (month_label, r["ma_nv"])
        entry = rows_map.setdefault(
            key,
            {
                "month_year": month_label,
                "from_date": first_day,
                "ma_nv": r["ma_nv"],
                "ho_ten": r.get("ho_ten"),
                "metrics": {}
            }
        )
        entry["metrics"].setdefault(r["task_name"], {"thuc_hien": 0, "sai_sot": 0})
        entry["metrics"][r["task_name"]]["thuc_hien"] += int(r["thuc_hien"] or 0)

    for r in err_rows:
        month_label, first_day = convert_month_key(r.get("month_key"))
        if not month_label or not r.get("ma_nv"):
            continue
        key = (month_label, r["ma_nv"])
        entry = rows_map.setdefault(
            key,
            {
                "month_year": month_label,
                "from_date": first_day,
                "ma_nv": r["ma_nv"],
                "ho_ten": None,
                "metrics": {}
            }
        )
        entry["from_date"] = entry.get("from_date") or first_day
        entry["metrics"].setdefault(r["task_name"], {"thuc_hien": 0, "sai_sot": 0})
        entry["metrics"][r["task_name"]]["sai_sot"] += int(r["sai_sot"] or 0)

    rows = list(rows_map.values())
    rows.sort(key=lambda x: (
        x.get("month_year") or "",
        x.get("ma_nv") or ""
    ))

    return {"tasks": tasks, "rows": rows}


@router.get("/api/summary/quarterly")
def api_summary_quarterly(
    chuc_vu: str = Query(..., pattern="^(QAPL|QANL|QAQT)$"),
    quarter: Optional[int] = Query(None, ge=1, le=4),
    year: Optional[int] = Query(None, ge=2000, le=2100)
):
    """Aggregate completed work and errors by calendar quarter and QA employee."""
    with core.get_db_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT task_name FROM public.tasks_qa WHERE chuc_vu=%s ORDER BY task_name", (chuc_vu,))
            tasks = [r["task_name"] for r in cur.fetchall()]

            qa_params: List[Any] = [chuc_vu]
            qa_period_clause = ""
            if quarter is not None:
                qa_period_clause += " AND EXTRACT(QUARTER FROM from_date) = %s"
                qa_params.append(quarter)
            if year is not None:
                qa_period_clause += " AND EXTRACT(YEAR FROM from_date) = %s"
                qa_params.append(year)

            cur.execute(
                f"""
                WITH qa AS (
                  SELECT
                    EXTRACT(YEAR FROM from_date)::int AS year_key,
                    EXTRACT(QUARTER FROM from_date)::int AS quarter_key,
                    ma_nv,
                    task_name,
                    SUM(thuc_hien) AS thuc_hien
                  FROM public.input_qa
                  WHERE chuc_vu = %s
                    AND from_date IS NOT NULL
                  {qa_period_clause}
                  GROUP BY 1,2,3,4
                )
                SELECT qa.year_key, qa.quarter_key, d.ma_nv, d.ho_ten,
                       qa.task_name, qa.thuc_hien
                FROM qa
                JOIN public.quality_employees d ON d.ma_nv = qa.ma_nv
                WHERE d.chuc_vu = %s
                ORDER BY qa.year_key, qa.quarter_key, d.ma_nv, qa.task_name
                """,
                (*qa_params, chuc_vu),
            )
            qa_rows = cur.fetchall()

            err_params: List[Any] = [chuc_vu]
            err_period_clause = ""
            if quarter is not None:
                err_period_clause += " AND EXTRACT(QUARTER FROM ngay_ghi_nhan) = %s"
                err_params.append(quarter)
            if year is not None:
                err_period_clause += " AND EXTRACT(YEAR FROM ngay_ghi_nhan) = %s"
                err_params.append(year)

            cur.execute(
                f"""
                SELECT
                  EXTRACT(YEAR FROM ngay_ghi_nhan)::int AS year_key,
                  EXTRACT(QUARTER FROM ngay_ghi_nhan)::int AS quarter_key,
                  e.ma_nv,
                  d.ho_ten,
                  e.task_name,
                  COUNT(*) AS sai_sot
                FROM public.input_error e
                JOIN public.quality_employees d ON d.ma_nv = e.ma_nv
                WHERE d.chuc_vu = %s
                  AND e.ngay_ghi_nhan IS NOT NULL
                  AND COALESCE(e.ghi_chu, '') NOT LIKE 'Nguồn Final API%%'
                  {err_period_clause}
                GROUP BY 1,2,3,4,5
                ORDER BY 1,2,3,5
                """,
                tuple(err_params),
            )
            err_rows = cur.fetchall()

    rows_map: Dict[Tuple[int, int, str], Dict] = {}

    def get_quarter_entry(row: Dict) -> Optional[Dict]:
        if not row.get("ma_nv") or row.get("year_key") is None or row.get("quarter_key") is None:
            return None
        row_year = int(row["year_key"])
        row_quarter = int(row["quarter_key"])
        key = (row_year, row_quarter, row["ma_nv"])
        return rows_map.setdefault(
            key,
            {
                "quarter_year": f"Q{row_quarter}-{row_year}",
                "quarter": row_quarter,
                "year": row_year,
                "ma_nv": row["ma_nv"],
                "ho_ten": row.get("ho_ten"),
                "metrics": {},
            },
        )

    for row in qa_rows:
        entry = get_quarter_entry(row)
        if entry is None:
            continue
        entry["metrics"].setdefault(row["task_name"], {"thuc_hien": 0, "sai_sot": 0})
        entry["metrics"][row["task_name"]]["thuc_hien"] += int(row["thuc_hien"] or 0)

    for row in err_rows:
        entry = get_quarter_entry(row)
        if entry is None:
            continue
        entry["ho_ten"] = entry.get("ho_ten") or row.get("ho_ten")
        entry["metrics"].setdefault(row["task_name"], {"thuc_hien": 0, "sai_sot": 0})
        entry["metrics"][row["task_name"]]["sai_sot"] += int(row["sai_sot"] or 0)

    rows = sorted(
        rows_map.values(),
        key=lambda item: (item.get("year") or 0, item.get("quarter") or 0, item.get("ma_nv") or ""),
    )
    return {"tasks": tasks, "rows": rows}


@router.get("/api/errors")
def api_errors(chuc_vu: Optional[str] = Query(None, pattern="^(QAPL|QANL|QAQT)$")):
    with core.get_db_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            base = (
                "SELECT id, ngay_ghi_nhan, chuc_vu, ma_nv, task_name, phan_loai_loi, mo_ta, muc_do_anh_huong, huong_giai_quyet, "
                "hanh_dong, trach_nhiem, thoi_han, tien_do, ngay_hoan_thanh, ket_luan, cap_form, ghi_chu, created_at "
                "FROM public.input_error WHERE COALESCE(ghi_chu, '') NOT LIKE 'Nguồn Final API%%'"
            )
            if chuc_vu:
                cur.execute(base + " AND chuc_vu=%s ORDER BY created_at DESC", (chuc_vu,))
            else:
                cur.execute(base + " ORDER BY created_at DESC")
            rows = cur.fetchall()
            
            # Thêm flag để biết có cần HĐKP không
            for row in rows:
                row['needs_hdkp'] = row.get('huong_giai_quyet', '') and 'HĐKP' in str(row.get('huong_giai_quyet', '')).upper()
    return {"rows": rows}


@router.patch("/api/error/{error_id}")
async def api_error_update(error_id: int = Path(...), request: Request = None):
    payload = await request.json()
    # 'tien_do' is derived from 'ngay_hoan_thanh' and MUST NOT be set directly
    allowed_fields = {
        "ngay_ghi_nhan", "task_name", "phan_loai_loi", "mo_ta", "muc_do_anh_huong", "huong_giai_quyet",
        "hanh_dong", "trach_nhiem", "thoi_han", "ngay_hoan_thanh", "ket_luan", "cap_form", "ghi_chu"
    }
    sets = []
    values = []
    for k, v in payload.items():
        if k in allowed_fields:
            if k in ("ngay_ghi_nhan", "thoi_han", "ngay_hoan_thanh") and v:
                try:
                    v = date.fromisoformat(v)
                except Exception:
                    raise HTTPException(status_code=400, detail=f"Ngày không hợp lệ cho {k}")
            if k == "muc_do_anh_huong":
                v = core.normalize_kpi_impact_level(v)
            sets.append(f"{k} = %s")
            values.append(v)
    # Auto set tien_do based on ngay_hoan_thanh when provided (rule)
    if "ngay_hoan_thanh" in payload:
        sets.append("tien_do = %s")
        values.append("Hoàn thành" if payload.get("ngay_hoan_thanh") else "Chưa hoàn thành")
    if not sets:
        raise HTTPException(status_code=400, detail="Không có trường hợp lệ để cập nhật")

    values.append(error_id)
    sql = f"UPDATE public.input_error SET {', '.join(sets)} WHERE id = %s RETURNING id"

    with core.get_db_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, tuple(values))
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Không tìm thấy lỗi")
            conn.commit()
    return {"status": "ok", "id": row["id"]}


@router.get("/api/error/{error_id}")
def api_get_error(error_id: int = Path(...)):
    """Lấy thông tin chi tiết của một error"""
    with core.get_db_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT id, ngay_ghi_nhan, chuc_vu, ma_nv, task_name, phan_loai_loi, mo_ta, 
                       muc_do_anh_huong, huong_giai_quyet, hanh_dong, trach_nhiem, 
                       thoi_han, tien_do, ngay_hoan_thanh, ket_luan, cap_form, ghi_chu, created_at
                FROM public.input_error WHERE id = %s
                """,
                (error_id,)
            )
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Không tìm thấy lỗi")
            
            # Thêm flag để biết có cần HĐKP không
            row['needs_hdkp'] = row.get('huong_giai_quyet', '') and 'HĐKP' in str(row.get('huong_giai_quyet', '')).upper()
            
            return {"error": dict(row)}


@router.get("/api/hdkp/{error_id}")
def api_get_hdkp(error_id: int = Path(...), request: Request = None):
    """Lấy dữ liệu HĐKP đã lưu cho một error"""
    user = core.require_authenticated_api_user(request)
    core.check_final_hdkp_error_access(user, error_id)
    with core.get_db_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            # Lấy Section I: Mô tả vấn đề
            cur.execute("SELECT * FROM public.cap_mota WHERE error_id = %s", (error_id,))
            mota = cur.fetchone()
            
            # Lấy Section II: Kế hoạch
            cur.execute(
                "SELECT * FROM public.cap_kehoach WHERE error_id = %s ORDER BY section, thu_tu",
                (error_id,)
            )
            kehoach = cur.fetchall()
            
            # Lấy Section III: Chi tiết
            cur.execute(
                "SELECT * FROM public.cap_chitiet WHERE error_id = %s ORDER BY thu_tu",
                (error_id,)
            )
            chitiet = cur.fetchall()
    
    return {
        "mota": dict(mota) if mota else None,
        "kehoach": [dict(r) for r in kehoach],
        "chitiet": [dict(r) for r in chitiet]
    }


@router.get("/hdkp-form/{error_id}")
def hdkp_form_page(
    error_id: int = Path(...),
    request: Request = None,
    next_url: Optional[str] = Query(None, alias="next"),
):
    """Trang form nhập HĐKP cho một error"""
    user = core.get_authenticated_user(request) if request else None
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    core.check_final_hdkp_error_access(user, error_id)
    
    with core.get_db_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT id, ngay_ghi_nhan, ma_nv, task_name, phan_loai_loi, mo_ta, huong_giai_quyet FROM public.input_error WHERE id = %s",
                (error_id,)
            )
            error_row = cur.fetchone()
            if not error_row:
                raise HTTPException(status_code=404, detail="Không tìm thấy lỗi")
            
            # Kiểm tra có cần HĐKP không
            needs_hdkp = error_row.get('huong_giai_quyet', '') and 'HĐKP' in str(error_row.get('huong_giai_quyet', '')).upper()
            if not needs_hdkp:
                raise HTTPException(status_code=400, detail="Lỗi này không yêu cầu HĐKP")
    
    if core.get_qc_role(user) == core.FINAL_CAP_ROLE:
        return_url = "/final-noi-bo"
    else:
        return_url = next_url if next_url and next_url.startswith("/") else "/view-kpi#pane-errors"
    return core.templates.TemplateResponse("hdkp_form.html", {
        "request": request,
        "error": dict(error_row),
        "error_id": error_id,
        "return_url": return_url,
    })


@router.post("/api/hdkp/{error_id}")
async def api_save_hdkp(error_id: int = Path(...), request: Request = None):
    """
    Lưu thông tin HĐKP cho một error vào 3 tables: cap_mota, cap_kehoach, cap_chitiet
    """
    user = core.require_authenticated_api_user(request)
    core.check_final_hdkp_error_access(user, error_id)
    
    payload = await request.json()
    
    # Lấy thông tin error
    with core.get_db_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT id, ma_nv, ngay_ghi_nhan FROM public.input_error WHERE id = %s",
                (error_id,)
            )
            error_row = cur.fetchone()
            if not error_row:
                raise HTTPException(status_code=404, detail="Không tìm thấy lỗi")
            
            # 1. Lưu Section I: Mô tả vấn đề vào cap_mota
            mota_data = payload.get('mota', {})
            cur.execute(
                """
                INSERT INTO public.cap_mota (
                    error_id, vd_what, vd_when, vd_who, vd_where, 
                    vd_how, vd_before, vd_importance, vd_image
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (error_id) DO UPDATE SET
                    vd_what = EXCLUDED.vd_what,
                    vd_when = EXCLUDED.vd_when,
                    vd_who = EXCLUDED.vd_who,
                    vd_where = EXCLUDED.vd_where,
                    vd_how = EXCLUDED.vd_how,
                    vd_before = EXCLUDED.vd_before,
                    vd_importance = EXCLUDED.vd_importance,
                    vd_image = EXCLUDED.vd_image,
                    updated_at = NOW()
                RETURNING id
                """,
                (
                    error_id,
                    mota_data.get('vd_what'),
                    mota_data.get('vd_when'),
                    mota_data.get('vd_who'),
                    mota_data.get('vd_where'),
                    mota_data.get('vd_how'),
                    mota_data.get('vd_before'),
                    mota_data.get('vd_importance'),
                    mota_data.get('vd_image'),
                )
            )
            
            # 2. Lưu Section II: Kế hoạch khắc phục vào cap_kehoach
            # Xóa các rows cũ
            cur.execute("DELETE FROM public.cap_kehoach WHERE error_id = %s", (error_id,))
            
            # Lưu các rows mới
            kehoach_list = payload.get('kehoach', [])
            for idx, item in enumerate(kehoach_list, 1):
                cur.execute(
                    """
                    INSERT INTO public.cap_kehoach (
                        error_id, section, root_cause, hdkp_tuc_thoi, hd_phong_ngua,
                        tg_theo_doi, trach_nhiem, tg_thuc_hien, thu_tu
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        error_id,
                        item.get('section'),  # 'A' hoặc 'B'
                        item.get('root_cause'),
                        item.get('hdkp_tuc_thoi'),
                        item.get('hd_phong_ngua'),
                        item.get('tg_theo_doi'),
                        item.get('trach_nhiem'),
                        item.get('tg_thuc_hien'),
                        idx,
                    )
                )
            
            # 3. Lưu Section III: Chi tiết kế hoạch vào cap_chitiet
            # Xóa các rows cũ
            cur.execute("DELETE FROM public.cap_chitiet WHERE error_id = %s", (error_id,))
            
            # Lưu các rows mới
            chitiet_list = payload.get('chitiet', [])
            for idx, item in enumerate(chitiet_list, 1):
                ngay_bat_dau = date.fromisoformat(item['ngay_bat_dau']) if item.get('ngay_bat_dau') else None
                ngay_hoan_thanh = date.fromisoformat(item['ngay_hoan_thanh']) if item.get('ngay_hoan_thanh') else None
                
                cur.execute(
                    """
                    INSERT INTO public.cap_chitiet (
                        error_id, cong_viec, trach_nhiem, ngay_bat_dau, ngay_hoan_thanh,
                        giam_sat, ket_qua, ket_luan, thu_tu
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        error_id,
                        item.get('cong_viec'),
                        item.get('trach_nhiem'),
                        ngay_bat_dau,
                        ngay_hoan_thanh,
                        item.get('giam_sat'),
                        item.get('ket_qua'),  # 'Đạt' hoặc 'Không đạt'
                        item.get('ket_luan'),
                        idx,
                    )
                )
            
            conn.commit()
            
            # 4. Tạo PDF nếu có đủ dữ liệu
            pdf_url = None
            if error_row.get('ngay_ghi_nhan'):
                try:
                    # Lấy dữ liệu từ 3 tables để tạo PDF
                    core.logger.info(f"Bắt đầu tạo PDF cho error_id={error_id}")
                    hdkp_data = core.prepare_hdkp_data_for_pdf(error_id, error_row)
                    core.logger.info(f"Dữ liệu HĐKP đã chuẩn bị: {len(hdkp_data)} fields")
                    pdf_url = core.create_hdkp_pdf(error_id, hdkp_data)
                    core.logger.info(f"PDF đã được tạo: {pdf_url}")
                    
                    # Cập nhật cap_form với URL PDF
                    cur.execute(
                        "UPDATE public.input_error SET cap_form = %s WHERE id = %s",
                        (pdf_url, error_id)
                    )
                    conn.commit()
                    core.logger.info(f"Đã cập nhật cap_form cho error_id={error_id}")
                except Exception as e:
                    # Log error để debug
                    core.logger.error(f"Lỗi khi tạo PDF cho error_id={error_id}: {str(e)}", exc_info=True)
                    # Không raise để không làm gián đoạn việc lưu dữ liệu
    
    return {"status": "ok", "id": error_id, "pdf_url": pdf_url}


@router.post("/api/hdkp/{error_id}/regenerate-pdf")
async def api_regenerate_hdkp_pdf(error_id: int = Path(...), request: Request = None):
    """
    Tạo lại PDF HĐKP từ dữ liệu đã có (để kiểm tra lề và format).
    """
    user = core.require_authenticated_api_user(request)
    core.check_final_hdkp_error_access(user, error_id)
    
    with core.get_db_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            # Lấy thông tin error
            cur.execute(
                "SELECT id, ma_nv, ngay_ghi_nhan FROM public.input_error WHERE id = %s",
                (error_id,)
            )
            error_row = cur.fetchone()
            if not error_row:
                raise HTTPException(status_code=404, detail="Không tìm thấy lỗi")
            
            # Kiểm tra có dữ liệu HĐKP không
            cur.execute("SELECT COUNT(*) as cnt FROM public.cap_mota WHERE error_id = %s", (error_id,))
            has_data = cur.fetchone()['cnt'] > 0
            if not has_data:
                raise HTTPException(status_code=400, detail="Chưa có dữ liệu HĐKP để tạo PDF")
            
            # Tạo lại PDF
            try:
                hdkp_data = core.prepare_hdkp_data_for_pdf(error_id, error_row)
                pdf_url = core.create_hdkp_pdf(error_id, hdkp_data)
                
                # Cập nhật cap_form với URL PDF mới
                cur.execute(
                    "UPDATE public.input_error SET cap_form = %s WHERE id = %s",
                    (pdf_url, error_id)
                )
                conn.commit()
                
                return {"status": "ok", "pdf_url": pdf_url, "message": "PDF đã được tạo lại thành công"}
            except Exception as e:
                raise HTTPException(status_code=500, detail=f"Lỗi khi tạo lại PDF: {str(e)}")


@router.post("/api/upload-image")
async def upload_image(request: Request, file: UploadFile = File(...)):
    """
    Upload hình ảnh cho HĐKP.
    Returns: URL của file đã upload
    """
    core.require_authenticated_api_user(request)
    # Kiá»ƒm tra file type
    allowed_extensions = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp'}
    file_ext = PathLib(file.filename).suffix.lower()
    if file_ext not in allowed_extensions:
        raise HTTPException(status_code=400, detail=f"File không hợp lệ. Chỉ chấp nhận: {', '.join(allowed_extensions)}")
    
    # Tạo tên file unique
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_filename = f"{timestamp}_{file.filename}"
    file_path = os.path.join(core.IMAGES_STORAGE_DIR, safe_filename)
    
    # LÆ°u file
    try:
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        
        # Return URL
        image_url = f"/api/images/{safe_filename}"
        return {"status": "ok", "url": image_url, "filename": safe_filename}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Lá»—i khi upload file: {str(e)}")
