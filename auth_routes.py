"""Đăng nhập / đăng xuất (KPI và QC).

Tách từ main.py. Hàm/biến dùng chung (DB, đăng nhập, phân quyền, template, cấu hình...) vẫn ở main.py
và được gọi qua `core.<tên>` lúc chạy, nên test patch `main.<tên>` vẫn có hiệu lực.
"""
import psycopg2
import psycopg2.extras
import psycopg2.pool
from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse

from app_core import core

router = APIRouter()


@router.get("/login")
def login_page(request: Request):
    next_url = (request.query_params.get("next") or "").strip()
    current_user = core.get_authenticated_user(request)
    if current_user:
        return RedirectResponse(url=core.post_login_target(core.get_qc_role(current_user), next_url), status_code=303)
    return core.templates.TemplateResponse("login.html", {"request": request, "next_url": next_url})


@router.post("/login")
def login(request: Request, ma_nv: str = Form(...), next_url: str = Form("")):
    ma_nv = (ma_nv or "").strip()
    next_url = (next_url or "").strip()
    if not ma_nv:
        return core.templates.TemplateResponse(
            "login.html",
            {"request": request, "error": "Vui lòng nhập mã nhân viên", "next_url": next_url},
            status_code=400,
        )
    ma_nv_upper = ma_nv.upper()
    ma_nv_variants = core.generate_ma_nv_variants(ma_nv)
    with core.get_db_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT ma_nv, ho_ten, chuc_vu, qc_role
                FROM public.quality_employees
                WHERE ma_nv = ANY(%s)
                ORDER BY CASE WHEN ma_nv = %s THEN 0 ELSE 1 END
                LIMIT 1
                """,
                (ma_nv_variants, ma_nv_upper)
            )
            user_row = cur.fetchone()
            if not user_row:
                return core.templates.TemplateResponse(
                    "login.html",
                    {"request": request, "error": "Mã nhân viên không tồn tại", "next_url": next_url},
                    status_code=401,
                )

    response = RedirectResponse(url=core.post_login_target(user_row.get("qc_role"), next_url), status_code=303)
    response.set_cookie(
        key="ma_nv",
        value=core.encode_ma_nv_cookie(user_row["ma_nv"]),
        httponly=True,
        samesite="lax",
        max_age=2*24*60*60,
    )
    return response


@router.post("/logout")
def logout(request: Request):
    response = RedirectResponse(url="/login", status_code=303)
    response.delete_cookie("ma_nv")
    return response


@router.get("/qc-login")
def qc_login_page(request: Request):
    current_user = core.get_authenticated_user(request)
    if current_user:
        target = core.QC_INPUT_HOME if core.get_qc_role(current_user) == "QC" else "/qc"
        return RedirectResponse(url=target, status_code=303)
    return core.templates.TemplateResponse("login.html", {"request": request, "qc_mode": True})

@router.post("/qc-login")
def qc_login(request: Request, ma_nv: str = Form(...)):
    ma_nv = (ma_nv or "").strip()
    if not ma_nv:
        return core.templates.TemplateResponse("login.html", {"request": request, "error": "Vui lòng nhập mã nhân viên", "qc_mode": True}, status_code=400)
    ma_nv_upper = ma_nv.upper()
    ma_nv_variants = core.generate_ma_nv_variants(ma_nv)
    with core.get_db_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT ma_nv, ho_ten, chuc_vu, qc_role
                FROM public.quality_employees
                WHERE ma_nv = ANY(%s) AND qc_role IN ('QA_ADMIN', 'FACTORY_ADMIN', 'QC')
                ORDER BY CASE WHEN ma_nv = %s THEN 0 ELSE 1 END
                LIMIT 1
                """,
                (ma_nv_variants, ma_nv_upper)
            )
            user_row = cur.fetchone()
            if not user_row:
                return core.templates.TemplateResponse("login.html", {"request": request, "error": "Tài khoản chưa được cấp quyền QC hoặc mã nhân viên không đúng", "qc_mode": True}, status_code=401)

    target = core.QC_INPUT_HOME if (user_row.get("qc_role") or "").upper() == "QC" else "/qc"
    response = RedirectResponse(url=target, status_code=303)
    response.set_cookie(
        key="ma_nv",
        value=core.encode_ma_nv_cookie(user_row["ma_nv"]),
        httponly=True,
        samesite="lax",
        max_age=2*24*60*60,
    )
    return response
