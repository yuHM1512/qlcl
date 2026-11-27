"""Nhân sự QC — CRUD, đồng bộ từ chuyền treo.

Tách từ main.py. Hàm/biến dùng chung (DB, đăng nhập, phân quyền, template, cấu hình...) vẫn ở main.py
và được gọi qua `core.<tên>` lúc chạy, nên test patch `main.<tên>` vẫn có hiệu lực.
"""
import json
import psycopg2
import psycopg2.extras
import psycopg2.pool
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from typing import List, Optional

from app_core import core

router = APIRouter()


class QCEmployee(BaseModel):
    ma_nv: str
    ho_ten: str
    chuc_vu: str = 'QC'
    don_vi: str
    bo_phan: str
    station: Optional[List[str]] = None
    qc_role: Optional[str] = None

@router.get("/api/qc/employees", dependencies=[Depends(core.require_employee_mgmt_user)])
def get_qc_employees(request: Request):
    actor = core.require_employee_mgmt_user(request)
    actor_role = core.get_qc_role(actor)
    with core.get_db_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            if actor_role == "FACTORY_ADMIN":
                cur.execute(
                    "SELECT ma_nv, ho_ten, chuc_vu, qc_role, don_vi, bo_phan, station FROM public.quality_employees WHERE don_vi = %s ORDER BY ma_nv",
                    (actor.get("don_vi"),),
                )
            else:
                cur.execute("SELECT ma_nv, ho_ten, chuc_vu, qc_role, don_vi, bo_phan, station FROM public.quality_employees ORDER BY ma_nv")
            rows = cur.fetchall()
            return {"status": "ok", "rows": rows}

@router.post("/api/qc/employees", dependencies=[Depends(core.require_employee_mgmt_user)])
def upsert_qc_employee(payload: QCEmployee, request: Request):
    actor = core.require_employee_mgmt_user(request)
    actor_role = core.get_qc_role(actor)
    if payload.qc_role not in core.QC_KNOWN_ROLES | {core.FINAL_CAP_ROLE, None}:
        raise HTTPException(status_code=422, detail="Role không hợp lệ")
    if payload.qc_role in core.QC_DON_VI_SCOPED_ROLES | {core.FINAL_CAP_ROLE} and payload.don_vi not in core.DON_VI_OPTIONS:
        raise HTTPException(status_code=422, detail="Quyền theo Xí nghiệp phải được gán đơn vị hợp lệ")
    if not payload.ma_nv.strip() or not payload.ho_ten.strip() or not payload.chuc_vu.strip():
        raise HTTPException(status_code=422, detail="Thiếu mã nhân viên, họ tên hoặc chức vụ")
    if actor_role == "QA_ADMIN" and payload.ma_nv == actor['ma_nv'] and payload.qc_role != 'QA_ADMIN':
        raise HTTPException(status_code=400, detail="Không thể tự thu hồi quyền QA_ADMIN của mình")
    if actor_role == "FACTORY_ADMIN":
        actor_don_vi = (actor.get("don_vi") or "").strip()
        if payload.don_vi != actor_don_vi:
            raise HTTPException(status_code=403, detail="Chỉ được quản lý tài khoản thuộc đơn vị của mình")
        if payload.qc_role and payload.qc_role not in {"QC", None}:
            raise HTTPException(status_code=403, detail="FACTORY_ADMIN chỉ được gán quyền QC hoặc bỏ trống")
        with core.get_db_connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("SELECT qc_role, don_vi FROM public.quality_employees WHERE ma_nv = %s", (payload.ma_nv,))
                existing_emp = cur.fetchone()
        if existing_emp:
            if existing_emp["qc_role"] in {"QA_ADMIN", "FACTORY_ADMIN"}:
                raise HTTPException(status_code=403, detail="Không có quyền chỉnh sửa tài khoản QA_ADMIN hoặc FACTORY_ADMIN")
            if existing_emp["don_vi"] != actor_don_vi:
                raise HTTPException(status_code=403, detail="Tài khoản này không thuộc đơn vị của bạn")
    bo_phan = core.normalize_bo_phan_value(payload.bo_phan)
    with core.get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT ma_nv FROM public.quality_employees WHERE ma_nv = %s", (payload.ma_nv,))
            existing = cur.fetchone()
            if existing:
                cur.execute("""
                    UPDATE public.quality_employees
                    SET ho_ten = %s, chuc_vu = %s, don_vi = %s, bo_phan = %s, station = %s, qc_role = %s
                    WHERE ma_nv = %s
                """, (payload.ho_ten, payload.chuc_vu, payload.don_vi, bo_phan, json.dumps(payload.station or []), payload.qc_role, payload.ma_nv))
            else:
                cur.execute("""
                    INSERT INTO public.quality_employees (ma_nv, ho_ten, chuc_vu, don_vi, bo_phan, station, qc_role)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                """, (payload.ma_nv, payload.ho_ten, payload.chuc_vu, payload.don_vi, bo_phan, json.dumps(payload.station or []), payload.qc_role))
        conn.commit()
    return {"status": "ok"}

@router.delete("/api/qc/employees/{ma_nv}", dependencies=[Depends(core.require_employee_mgmt_user)])
def delete_qc_employee(ma_nv: str, request: Request):
    actor = core.require_employee_mgmt_user(request)
    actor_role = core.get_qc_role(actor)
    if actor_role == "FACTORY_ADMIN":
        actor_don_vi = (actor.get("don_vi") or "").strip()
        with core.get_db_connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("SELECT qc_role, don_vi FROM public.quality_employees WHERE ma_nv = %s", (ma_nv,))
                target = cur.fetchone()
        if not target:
            raise HTTPException(status_code=404, detail="Không tìm thấy tài khoản")
        if target["don_vi"] != actor_don_vi:
            raise HTTPException(status_code=403, detail="Không có quyền xóa tài khoản ngoài đơn vị của mình")
        if target["qc_role"] != "QC":
            raise HTTPException(status_code=403, detail="FACTORY_ADMIN chỉ được xóa tài khoản có quyền QC")
    with core.get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM public.quality_employees WHERE ma_nv = %s AND qc_role = 'QC'", (ma_nv,))
        conn.commit()
    return {"status": "ok"}


@router.post("/api/qc/employees/push-from-hl")
def api_push_qc_employees_from_hanging_line(request: Request, payload: dict):
    """Receive employee/operation assignments from hanging-line apps.

    Body:
      {
        "don_vi": "XN2",
        "plan_monos": ["MONo-1", ...],
        "employees": [
          {"ma_nv": "A001", "ho_ten": "...", "bo_phan": "Tổ 3",
           "station": ["Odr 1 - CẤP PHÔI", ...],
           "plans": [{"mono": "MONo-1", "station": ["Odr 1 - CẤP PHÔI"]}]}
        ]
      }

    plan_monos (tuỳ chọn): các MONo được đồng bộ ở lần gửi này. Công đoạn theo
    MONo của các MONo này được thay toàn bộ (cả khi không còn NV nào). Bản app
    cũ không gửi plan_monos thì bảng công đoạn theo MONo giữ nguyên.
    """
    if not core._PUSH_API_KEY or request.headers.get("X-API-Key") != core._PUSH_API_KEY:
        raise HTTPException(status_code=403, detail="API key không hợp lệ")

    don_vi = str(payload.get("don_vi") or "").strip()
    employees = payload.get("employees") or []
    replace_station_scope = bool(payload.get("replace_station_scope"))
    raw_plan_monos = payload.get("plan_monos")
    if not don_vi:
        raise HTTPException(status_code=422, detail="Thiếu don_vi")
    if not isinstance(employees, list):
        raise HTTPException(status_code=422, detail="employees phải là list")
    if raw_plan_monos is not None and not isinstance(raw_plan_monos, list):
        raise HTTPException(status_code=422, detail="plan_monos phải là list")
    plan_monos = sorted({str(m).strip() for m in (raw_plan_monos or []) if str(m or "").strip()})
    track_plan_stations = raw_plan_monos is not None

    inserted = updated = skipped = 0
    plan_station_rows = 0
    warnings: list[str] = []

    with core.get_db_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            if replace_station_scope:
                cur.execute(
                    """
                    UPDATE public.quality_employees
                    SET station = '[]'::jsonb
                    WHERE qc_role = 'QC' AND don_vi = %s
                    """,
                    (don_vi,),
                )
            if track_plan_stations:
                if replace_station_scope:
                    cur.execute(
                        "DELETE FROM public.qc_employee_plan_station WHERE don_vi = %s",
                        (don_vi,),
                    )
                elif plan_monos:
                    cur.execute(
                        "DELETE FROM public.qc_employee_plan_station WHERE don_vi = %s AND mono = ANY(%s)",
                        (don_vi, plan_monos),
                    )
            for row in employees:
                ma_nv = str(row.get("ma_nv") or "").strip()
                ho_ten = str(row.get("ho_ten") or "").strip()
                bo_phan = core.normalize_bo_phan_value(str(row.get("bo_phan") or "").strip())
                raw_station = row.get("station") or []
                if isinstance(raw_station, str):
                    station_list = [raw_station.strip()] if raw_station.strip() else []
                else:
                    station_list = [
                        str(item).strip()
                        for item in raw_station
                        if str(item or "").strip()
                    ]

                if not ma_nv or not ho_ten:
                    skipped += 1
                    warnings.append("Bỏ qua 1 nhân viên vì thiếu ma_nv/ho_ten")
                    continue

                cur.execute(
                    "SELECT station, qc_role, don_vi FROM public.quality_employees WHERE ma_nv = %s",
                    (ma_nv,),
                )
                existing = cur.fetchone()
                if existing:
                    if existing['qc_role'] != 'QC' or existing['don_vi'] != don_vi:
                        skipped += 1
                        warnings.append(f"Bỏ qua {ma_nv}: tài khoản chưa được cấp QC tại Xí nghiệp này")
                        continue
                    cur.execute(
                        """
                        UPDATE public.quality_employees
                        SET ho_ten = %s,
                            chuc_vu = 'QC',
                            don_vi = %s,
                            bo_phan = %s,
                            station = %s::jsonb
                        WHERE ma_nv = %s
                        """,
                        (ho_ten, don_vi, bo_phan, json.dumps(sorted(set(station_list))), ma_nv),
                    )
                    updated += 1
                else:
                    cur.execute(
                        """
                        INSERT INTO public.quality_employees
                            (ma_nv, ho_ten, chuc_vu, don_vi, bo_phan, station, qc_role)
                        VALUES (%s, %s, 'QC', %s, %s, %s::jsonb, 'QC')
                        """,
                        (ma_nv, ho_ten, don_vi, bo_phan, json.dumps(sorted(set(station_list)))),
                    )
                    inserted += 1

                if track_plan_stations:
                    for plan in row.get("plans") or []:
                        mono = str((plan or {}).get("mono") or "").strip()
                        if not mono or (not replace_station_scope and mono not in plan_monos):
                            continue
                        for station in {str(s).strip() for s in (plan.get("station") or []) if str(s or "").strip()}:
                            cur.execute(
                                """
                                INSERT INTO public.qc_employee_plan_station (don_vi, mono, ma_nv, station)
                                VALUES (%s, %s, %s, %s)
                                ON CONFLICT (don_vi, mono, ma_nv, station) DO UPDATE SET synced_at = NOW()
                                """,
                                (don_vi, mono, ma_nv, station),
                            )
                            plan_station_rows += 1

        conn.commit()

    return {
        "status": "ok",
        "don_vi": don_vi,
        "inserted": inserted,
        "updated": updated,
        "skipped": skipped,
        "plan_station_rows": plan_station_rows,
        "warnings": warnings[:20],
    }
