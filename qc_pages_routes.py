"""Trang QC có sidebar: kế hoạch, cài đặt danh mục, CAP, dashboard.

Tách từ main.py. Hàm/biến dùng chung (DB, đăng nhập, phân quyền, template, cấu hình...) vẫn ở main.py
và được gọi qua `core.<tên>` lúc chạy, nên test patch `main.<tên>` vẫn có hiệu lực.
"""
from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

from app_core import core

router = APIRouter()


@router.get("/qc")
def qc_page(request: Request):
    user_data = core.get_authenticated_user(request)
    if not user_data:
        return core.redirect_to_login_for_current_path(request)
    core.require_qc_api_user(request)
    role = core.get_qc_role(user_data)
    if role == "QC":
        return RedirectResponse(url="/qc-input", status_code=303)
    if role not in core.QC_PLAN_ROLES:
        return RedirectResponse(url="/qc/dashboard", status_code=303)
    if role not in core.QC_KNOWN_ROLES:
        return RedirectResponse(url="/", status_code=303)
    return core.templates.TemplateResponse(
        "qc.html",
        core.build_qc_template_context(request, user_data, don_vi_options=core.DON_VI_OPTIONS, page_subtitle="Kế hoạch sản xuất", active_page="plan"),
    )


@router.get("/qc/settings/customer")
def qc_settings_customer(request: Request):
    user = core.get_authenticated_user(request)
    if not user:
        return core.redirect_to_login_for_current_path(request)
    if core.get_qc_role(user) not in core.QC_SETTINGS_ROLES:
        return RedirectResponse(url="/qc", status_code=303)
    return core.templates.TemplateResponse(
        "qc_settings_customer.html",
        core.build_qc_template_context(request, user, page_subtitle="Khách hàng & Mã hàng", active_page="settings_customer"),
    )

@router.get("/qc/settings/details")
def qc_settings_details(request: Request):
    user = core.get_authenticated_user(request)
    if not user:
        return core.redirect_to_login_for_current_path(request)
    if core.get_qc_role(user) not in core.QC_SETTINGS_ROLES:
        return RedirectResponse(url="/qc", status_code=303)
    return core.templates.TemplateResponse(
        "qc_settings_details.html",
        core.build_qc_template_context(request, user, page_subtitle="Bộ phận & Chi tiết", active_page="settings_details"),
    )

@router.get("/qc/settings/qc-list")
def qc_settings_qc_list(request: Request):
    user = core.get_authenticated_user(request)
    if not user:
        return core.redirect_to_login_for_current_path(request)
    if core.get_qc_role(user) not in core.QC_EMPLOYEE_MGMT_ROLES:
        return RedirectResponse(url="/qc", status_code=303)
    return core.templates.TemplateResponse(
        "qc_settings_qcs.html",
        core.build_qc_template_context(request, user, don_vi_options=core.DON_VI_OPTIONS, page_subtitle="Tài khoản & phân quyền", active_page="settings_qcs"),
    )

@router.get("/qc/cap")
def qc_cap_page(request: Request):
    user = core.get_authenticated_user(request)
    if not user:
        return core.redirect_to_login_for_current_path(request)
    role = core.get_qc_role(user)
    if role not in core.QC_DASHBOARD_ROLES:
        return RedirectResponse(url="/", status_code=303)
    return core.templates.TemplateResponse("cap.html", core.build_qc_template_context(request, user, page_subtitle="Hành động khắc phục", active_page="cap"))

@router.get("/qc/dashboard")
def qc_dashboard_page(request: Request):
    user = core.get_authenticated_user(request)
    if not user:
        return core.redirect_to_login_for_current_path(request)
    role = core.get_qc_role(user)
    if role not in core.QC_DASHBOARD_ROLES:
        return RedirectResponse(url="/", status_code=303)
    return core.templates.TemplateResponse(
        "qc_dashboard.html",
        core.build_qc_template_context(request, user, page_subtitle="Dashboard tỉ lệ lỗi", active_page="dashboard"),
    )
