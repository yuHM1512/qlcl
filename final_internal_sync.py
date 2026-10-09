"""Sync internal Final inspection history from po.hachiba.app into PostgreSQL."""

from __future__ import annotations

from datetime import date, datetime
import json
import re
from typing import Any, Callable, Dict, Iterable, Optional

import httpx
import psycopg2.extras


ORDER_TYPE_LABELS = {
    "0": "Replenishment (Lặp lại)",
    "1": "Implantation (Đầu tiên)",
}


def _as_int(value: Any) -> Optional[int]:
    if value is None or value == "":
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _parse_date(value: Any) -> Optional[date]:
    if not value:
        return None
    raw = str(value).strip()
    for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


def _parse_datetime(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _inspector_name(history: Dict[str, Any]) -> str:
    name = str(history.get("name") or "").strip()
    return re.sub(r"-\d{2}/\d{2}/\d{4}$", "", name).strip()


class FinalApiClient:
    def __init__(self, base_url: str, username: str, password: str, timeout: float = 30.0):
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.password = password
        self.timeout = timeout
        self._client = httpx.Client(timeout=timeout, follow_redirects=True)
        self._token: Optional[str] = None

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "FinalApiClient":
        return self

    def __exit__(self, *_args: Any) -> None:
        self.close()

    def _headers(self) -> Dict[str, str]:
        if not self._token:
            response = self._client.post(
                f"{self.base_url}/auth/login_token/",
                json={"username": self.username, "password": self.password},
            )
            response.raise_for_status()
            self._token = (response.json() or {}).get("token")
            if not self._token:
                raise RuntimeError("API Final đăng nhập thành công nhưng không trả token")
        return {"Authorization": f"Token {self._token}"}

    def get(self, path: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        response = self._client.get(
            f"{self.base_url}{path}", headers=self._headers(), params=params
        )
        response.raise_for_status()
        payload = response.json()
        if payload.get("success") is False:
            raise RuntimeError(payload.get("message") or "API Final trả lỗi")
        return payload

    def iter_plans(self, page_size: int = 100, max_pages: Optional[int] = None) -> Iterable[Dict[str, Any]]:
        page_number = 1
        while True:
            payload = self.get(
                "/api/qa/plans/",
                {"page_number": page_number, "page_size": page_size},
            )
            for plan in payload.get("data") or []:
                yield plan
            paging = payload.get("paging") or {}
            total_page = int(paging.get("total_page") or page_number)
            if page_number >= total_page or (max_pages and page_number >= max_pages):
                break
            page_number += 1

    def plan_detail(self, plan_id: int) -> Dict[str, Any]:
        return (self.get(f"/api/qa/plans/{plan_id}/").get("data") or {})

    def final_detail(self, plan_delegate_id: int) -> Dict[str, Any]:
        return (self.get(f"/api/qa/final/{plan_delegate_id}/").get("data") or {})


def _upsert_inspection(
    cur: Any,
    plan: Dict[str, Any],
    delegate: Dict[str, Any],
    final_data: Dict[str, Any],
    history: Dict[str, Any],
) -> int:
    final_delegate = final_data.get("plan_delegate") or delegate
    po = final_data.get("po") or {}
    total = final_data.get("tong") or {}
    status_code = str(history.get("status_final_internal") or "").strip()
    order_type_code = str(history.get("qa_times_check") or "").strip()
    source_history_id = _as_int(history.get("id"))
    if source_history_id is None:
        raise ValueError("Bản ghi lịch sử Final thiếu id")

    cur.execute(
        """
        INSERT INTO public.qa_final_inspection (
            source_history_id, source_plan_id, source_plan_delegate_id, source_po_id,
            plan_code, po_code, product_id, fg_model, factory,
            order_type_code, order_type_display, inspector_name,
            quantity_pcs, sample_count, source_amount_qa_check,
            qa_check_date, source_created_at, metal_detection,
            measurement_result, destructive_measurement_result, appearance_result,
            quality_status_code, final_status_code, final_status_display, cap_required,
            image_urls, raw_data, source_updated_at, synced_at
        ) VALUES (
            %s, %s, %s, %s, %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s, NOW()
        )
        ON CONFLICT (source_history_id) DO UPDATE SET
            source_plan_id = EXCLUDED.source_plan_id,
            source_plan_delegate_id = EXCLUDED.source_plan_delegate_id,
            source_po_id = EXCLUDED.source_po_id,
            plan_code = EXCLUDED.plan_code,
            po_code = EXCLUDED.po_code,
            product_id = EXCLUDED.product_id,
            fg_model = EXCLUDED.fg_model,
            factory = EXCLUDED.factory,
            order_type_code = EXCLUDED.order_type_code,
            order_type_display = EXCLUDED.order_type_display,
            inspector_name = EXCLUDED.inspector_name,
            quantity_pcs = EXCLUDED.quantity_pcs,
            sample_count = EXCLUDED.sample_count,
            source_amount_qa_check = EXCLUDED.source_amount_qa_check,
            qa_check_date = EXCLUDED.qa_check_date,
            source_created_at = EXCLUDED.source_created_at,
            metal_detection = EXCLUDED.metal_detection,
            measurement_result = EXCLUDED.measurement_result,
            destructive_measurement_result = EXCLUDED.destructive_measurement_result,
            appearance_result = EXCLUDED.appearance_result,
            quality_status_code = EXCLUDED.quality_status_code,
            final_status_code = EXCLUDED.final_status_code,
            final_status_display = EXCLUDED.final_status_display,
            cap_required = EXCLUDED.cap_required,
            image_urls = EXCLUDED.image_urls,
            raw_data = EXCLUDED.raw_data,
            source_updated_at = EXCLUDED.source_updated_at,
            synced_at = NOW()
        RETURNING id
        """,
        (
            source_history_id,
            _as_int(plan.get("id")),
            _as_int(final_delegate.get("id") or delegate.get("id")),
            _as_int(po.get("id")),
            final_delegate.get("plan_code") or plan.get("code"),
            final_delegate.get("po_code") or delegate.get("po_code") or po.get("po_code"),
            final_delegate.get("product_id") or po.get("product_id"),
            final_delegate.get("fg_model") or po.get("fg_model"),
            final_delegate.get("fac") or delegate.get("fac") or po.get("fac"),
            order_type_code,
            ORDER_TYPE_LABELS.get(order_type_code, order_type_code or None),
            _inspector_name(history),
            _as_int(total.get("pcs") or final_delegate.get("so_chiec_ke_hoach")),
            _as_int(history.get("amount_error_internal")),
            _as_int(history.get("amount_QA_check")),
            _parse_date(history.get("date_qa_check")),
            _parse_datetime(history.get("created_at")),
            history.get("do_kim"),
            history.get("qa_ktcn_khong_pha_huy"),
            history.get("qa_ktcn_pha_huy"),
            history.get("qa_gtd_ngoai_quan"),
            str(history.get("status_quality_internal") or "").strip(),
            status_code,
            history.get("status_final_internal_display"),
            status_code == "0",
            json.dumps(history.get("anh_qa") or [], ensure_ascii=False),
            json.dumps(history, ensure_ascii=False),
            _parse_datetime(final_delegate.get("updated_at")),
        ),
    )
    inspection_id = int(cur.fetchone()[0])
    cur.execute("DELETE FROM public.qa_final_defect WHERE inspection_id = %s", (inspection_id,))
    for defect in history.get("loi_noi_bo") or []:
        cur.execute(
            """
            INSERT INTO public.qa_final_defect (
                inspection_id, source_defect_id, error_code, error_name,
                amount, description, level, raw_data
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb)
            """,
            (
                inspection_id,
                _as_int(defect.get("id")),
                defect.get("error_detail_code"),
                defect.get("error_detail_name"),
                _as_int(defect.get("amount")) or 0,
                defect.get("description"),
                str(defect.get("level") or "").strip(),
                json.dumps(defect, ensure_ascii=False),
            ),
        )
    return inspection_id


def sync_final_internal(
    connection_factory: Callable[[], Any],
    client: FinalApiClient,
    *,
    page_size: int = 100,
    max_pages: Optional[int] = None,
    triggered_by: Optional[str] = None,
) -> Dict[str, Any]:
    stats = {"plans_scanned": 0, "delegates_scanned": 0, "inspections_upserted": 0}
    with connection_factory() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO public.qa_final_sync_run (triggered_by) VALUES (%s) RETURNING id",
                (triggered_by,),
            )
            run_id = int(cur.fetchone()[0])
            conn.commit()
        try:
            for plan in client.iter_plans(page_size=page_size, max_pages=max_pages):
                stats["plans_scanned"] += 1
                detail = client.plan_detail(int(plan["id"]))
                for delegate in detail.get("po") or []:
                    if (_as_int(delegate.get("so_lan_kiem")) or 0) <= 0:
                        continue
                    stats["delegates_scanned"] += 1
                    final_data = client.final_detail(int(delegate["id"]))
                    histories = final_data.get("lich_su") or []
                    with conn.cursor() as cur:
                        for history in histories:
                            _upsert_inspection(cur, plan, delegate, final_data, history)
                            stats["inspections_upserted"] += 1
                    conn.commit()
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE public.qa_final_sync_run
                    SET finished_at = NOW(), status = 'success', plans_scanned = %s,
                        delegates_scanned = %s, inspections_upserted = %s
                    WHERE id = %s
                    """,
                    (
                        stats["plans_scanned"], stats["delegates_scanned"],
                        stats["inspections_upserted"], run_id,
                    ),
                )
            conn.commit()
            return {"run_id": run_id, **stats}
        except Exception as exc:
            conn.rollback()
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE public.qa_final_sync_run
                    SET finished_at = NOW(), status = 'failed', plans_scanned = %s,
                        delegates_scanned = %s, inspections_upserted = %s, error_message = %s
                    WHERE id = %s
                    """,
                    (
                        stats["plans_scanned"], stats["delegates_scanned"],
                        stats["inspections_upserted"], str(exc)[:2000], run_id,
                    ),
                )
            conn.commit()
            raise
