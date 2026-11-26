"""API dashboard tỉ lệ lỗi QC.

Tách từ main.py. Hàm/biến dùng chung (DB, đăng nhập, phân quyền, template, cấu hình...) vẫn ở main.py
và được gọi qua `core.<tên>` lúc chạy, nên test patch `main.<tên>` vẫn có hiệu lực.
"""
import psycopg2
import psycopg2.extras
import psycopg2.pool
from datetime import datetime, timedelta
from fastapi import APIRouter, Query, Request
from typing import Any, Dict, List, Optional, Tuple

from app_core import core

router = APIRouter()


@router.get("/api/qc/dashboard/filters")
def api_qc_dashboard_filters(
    request: Request,
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    don_vi: Optional[str] = Query(None),
    bo_phan: Optional[str] = Query(None),
    station: Optional[str] = Query(None),
    ma_hang: Optional[str] = Query(None),
    type_name: Optional[str] = Query(None),
):
    """Return cascading filter options for QC Dashboard."""
    don_vi, scoped_user = core.resolve_qc_don_vi_scope(request, don_vi)
    if not date_to:
        date_to = datetime.now().strftime("%Y-%m-%d")
    if not date_from:
        date_from = date_to

    resolved_bo_phan_expr = "COALESCE(NULLIF(qe.bo_phan, ''), '')"

    with core.get_db_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            def option_query(
                select_expr: str,
                not_blank_expr: str,
                *,
                apply_don_vi: bool = True,
                include_bo_phan: bool = False,
                include_station: bool = False,
                include_ma_hang: bool = False,
            ) -> Tuple[str, List[Any]]:
                where_clauses = ["o.date BETWEEN %s AND %s", f"{not_blank_expr} IS NOT NULL", f"{not_blank_expr} <> ''"]
                params: List[Any] = [date_from, date_to]
                if apply_don_vi and don_vi:
                    where_clauses.append("p.don_vi = %s")
                    params.append(don_vi)
                if include_bo_phan and bo_phan:
                    where_clauses.append(f"{resolved_bo_phan_expr} = %s")
                    params.append(bo_phan)
                if include_station and station:
                    where_clauses.append("COALESCE(o.station, '') = %s")
                    params.append(station)
                if include_ma_hang and ma_hang:
                    where_clauses.append("COALESCE(p.ma_hang, '') = %s")
                    params.append(ma_hang)

                sql = f"""
                    SELECT DISTINCT {select_expr} AS value
                    FROM public.qc_output_sp_log o
                    JOIN public.prod_plan p ON p.id = o.plan_id
                    LEFT JOIN public.quality_employees qe ON qe.ma_nv = o.ma_nv
                    LEFT JOIN public.dm_loai_hang lh ON lh.ten_loai = p.loai_hang
                    LEFT JOIN public.dm_loai_hang_target tgt ON tgt.id_type = lh.id_type
                    WHERE {" AND ".join(where_clauses)}
                    ORDER BY value
                """
                return sql, params

            sql, params = option_query("p.don_vi", "p.don_vi", apply_don_vi=core.is_qc_don_vi_scoped_role(scoped_user))
            cur.execute(sql, tuple(params))
            don_vi_options = [r["value"] for r in cur.fetchall()]

            # "Tổ" on QC dashboard must reflect QC employee team (quality_employees.bo_phan),
            # i.e. filter by the team of the QC employee code (ma_nv) that created each row.
            sql, params = option_query(resolved_bo_phan_expr, resolved_bo_phan_expr)
            cur.execute(sql, tuple(params))
            bo_phan_options = [r["value"] for r in cur.fetchall()]

            sql, params = option_query("o.station", "o.station", include_bo_phan=True)
            cur.execute(sql, tuple(params))
            station_options = [r["value"] for r in cur.fetchall()]

            sql, params = option_query("p.ma_hang", "p.ma_hang", include_bo_phan=True, include_station=True)
            cur.execute(sql, tuple(params))
            ma_hang_options = [r["value"] for r in cur.fetchall()]

            sql, params = option_query("tgt.type", "tgt.type", include_bo_phan=True, include_station=True, include_ma_hang=True)
            cur.execute(sql, tuple(params))
            type_options = [r["value"] for r in cur.fetchall()]
            default_type_name = type_name or ("Thường" if "Thường" in type_options else None)
            default_station = core.resolve_dashboard_default_station(
                cur,
                scoped_user=scoped_user,
                don_vi=don_vi,
                bo_phan=bo_phan,
                ma_hang=ma_hang,
                type_name=default_type_name,
                date_from=date_from,
                date_to=date_to,
            )

    return {
        "don_vi": don_vi_options,
        "bo_phan": bo_phan_options,
        "station": station_options,
        "default_station": default_station,
        "ma_hang": ma_hang_options,
        "type": type_options,
    }

@router.get("/api/qc/dashboard/prev-date")
def api_qc_dashboard_prev_date(
    request: Request,
    date_before: Optional[str] = Query(None),
    don_vi: Optional[str] = Query(None),
    bo_phan: Optional[str] = Query(None),
    station: Optional[str] = Query(None),
    ma_hang: Optional[str] = Query(None),
    type_name: Optional[str] = Query(None),
):
    """Return the nearest previous day (before date_before) that has data, to skip off days."""
    don_vi, scoped_user = core.resolve_qc_don_vi_scope(request, don_vi)
    if not date_before:
        date_before = datetime.now().strftime("%Y-%m-%d")

    # "Tổ" filter is based on QC employee team only.
    resolved_bo_phan_expr = "COALESCE(NULLIF(qe.bo_phan, ''), '')"

    where_clauses = ["o.date < %s"]
    params: List = [date_before]

    if don_vi:
        where_clauses.append("p.don_vi = %s")
        params.append(don_vi)
    if bo_phan:
        where_clauses.append(f"{resolved_bo_phan_expr} = %s")
        params.append(bo_phan)
    if ma_hang:
        where_clauses.append("COALESCE(p.ma_hang, '') = %s")
        params.append(ma_hang)
    if type_name:
        where_clauses.append("COALESCE(tgt.type, '') = %s")
        params.append(type_name)

    with core.get_db_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            station_for_calc = core.resolve_dashboard_default_station(
                cur,
                station=station,
                scoped_user=scoped_user,
                don_vi=don_vi,
                bo_phan=bo_phan,
                ma_hang=ma_hang,
                type_name=type_name,
                date_before=date_before,
                resolved_bo_phan_expr=resolved_bo_phan_expr,
            )
            if station_for_calc:
                where_clauses.append("COALESCE(o.station, '') = %s")
                params.append(station_for_calc)

            where_sql = " AND ".join(where_clauses)
            cur.execute(
                f"""
                SELECT MAX(o.date) AS prev_date
                FROM public.qc_output_sp_log o
                JOIN public.prod_plan p ON p.id = o.plan_id
                LEFT JOIN public.quality_employees qe ON qe.ma_nv = o.ma_nv
                LEFT JOIN public.dm_loai_hang lh ON lh.ten_loai = p.loai_hang
                LEFT JOIN public.dm_loai_hang_target tgt ON tgt.id_type = lh.id_type
                WHERE {where_sql}
                """,
                tuple(params),
            )
            row = cur.fetchone() or {}

    prev_date = row.get("prev_date")
    return {"status": "ok", "date": str(prev_date) if prev_date else None}

@router.get("/api/qc/dashboard")
def api_qc_dashboard(
    request: Request,
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    focus_date: Optional[str] = Query(None),
    don_vi: Optional[str] = Query(None),
    bo_phan: Optional[str] = Query(None),
    station: Optional[str] = Query(None),
    ma_hang: Optional[str] = Query(None),
    type_name: Optional[str] = Query(None),
    detail_bo_phan: Optional[str] = Query(None),
    ma_loi_bo_phan: Optional[str] = Query(None),
    ma_loi_chi_tiet: Optional[str] = Query(None),
):
    """QC Dashboard data source."""
    don_vi, scoped_user = core.resolve_qc_don_vi_scope(request, don_vi)
    if not date_to:
        date_to = datetime.now().strftime("%Y-%m-%d")
    if not date_from:
        # Default: last 7 days (inclusive) to match dashboard UX.
        try:
            dt_to = datetime.strptime(date_to, "%Y-%m-%d")
            date_from = (dt_to - timedelta(days=7)).strftime("%Y-%m-%d")
        except Exception:
            date_from = date_to
    if not focus_date:
        focus_date = date_to

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

    bucket_order = ["7H30 - 9H30", "9H30 - 11H30", "12H30 - 14H30", "14H30 - 16H30", "Sau 16H30"]

    with core.get_db_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            # Detect prod_plan.bo_phan type for compatibility
            use_jsonb_bo_phan = core._detect_bo_phan_jsonb()

            # NOTE: Use a non-conflicting alias for this LATERAL join because
            # other queries in this endpoint also join dm_bo_phan as "bp".
            bo_phan_expr = "bp_plan.bo_phan_text" if use_jsonb_bo_phan else "p.bo_phan"
            bo_phan_join = (
                """
                LEFT JOIN LATERAL (
                    SELECT string_agg(value, ', ') AS bo_phan_text
                    FROM jsonb_array_elements_text(COALESCE(p.bo_phan, '[]'::jsonb)) AS t(value)
                ) bp_plan ON true
                """
                if use_jsonb_bo_phan
                else ""
            )
            # "Tổ" filter must be based on QC employee team only (qe.bo_phan).
            resolved_bo_phan_expr = "COALESCE(NULLIF(qe.bo_phan, ''), '')"

            station_for_calc = core.resolve_dashboard_default_station(
                cur,
                station=station,
                scoped_user=scoped_user,
                don_vi=don_vi,
                bo_phan=bo_phan,
                ma_hang=ma_hang,
                type_name=type_name,
                date_from=date_from,
                date_to=date_to,
                resolved_bo_phan_expr=resolved_bo_phan_expr,
            )

            # Filters used for KPI/charts (force station_for_calc).
            base_clauses_calc = ["o.date BETWEEN %s AND %s"]
            base_params_calc: List = [date_from, date_to]
            if don_vi:
                base_clauses_calc.append("p.don_vi = %s")
                base_params_calc.append(don_vi)
            if bo_phan:
                base_clauses_calc.append(f"{resolved_bo_phan_expr} = %s")
                base_params_calc.append(bo_phan)
            if station_for_calc:
                base_clauses_calc.append("COALESCE(o.station, '') = %s")
                base_params_calc.append(station_for_calc)
            if ma_hang:
                base_clauses_calc.append("COALESCE(p.ma_hang, '') = %s")
                base_params_calc.append(ma_hang)
            if type_name:
                base_clauses_calc.append("COALESCE(tgt.type, '') = %s")
                base_params_calc.append(type_name)

            where_sql_calc = " AND ".join(base_clauses_calc)

            # Filters used for the station summary table (show all stations).
            base_clauses_station = ["o.date BETWEEN %s AND %s"]
            base_params_station: List = [date_from, date_to]
            if don_vi:
                base_clauses_station.append("p.don_vi = %s")
                base_params_station.append(don_vi)
            if bo_phan:
                base_clauses_station.append(f"{resolved_bo_phan_expr} = %s")
                base_params_station.append(bo_phan)
            if ma_hang:
                base_clauses_station.append("COALESCE(p.ma_hang, '') = %s")
                base_params_station.append(ma_hang)
            if type_name:
                base_clauses_station.append("COALESCE(tgt.type, '') = %s")
                base_params_station.append(type_name)

            where_sql_station = " AND ".join(base_clauses_station)

            # A. Mixed chart by date (defect rate + target line)
            cur.execute(f"""
                SELECT
                    o.date,
                    SUM(o.delta) AS inspected_total,
                    SUM(CASE WHEN o.status = 'Failed' THEN o.delta ELSE 0 END) AS defect_total,
                    CASE
                        WHEN SUM(o.delta) > 0
                        THEN ROUND(SUM(CASE WHEN o.status = 'Failed' THEN o.delta ELSE 0 END)::numeric * 100.0 / SUM(o.delta), 4)
                        ELSE 0
                    END AS defect_rate,
                    CASE
                        WHEN SUM(o.delta) > 0
                        THEN ROUND(SUM(o.delta * COALESCE(tgt.target_percent, 0))::numeric / SUM(o.delta), 4)
                        ELSE 0
                    END AS target_rate
                FROM public.qc_output_sp_log o
                JOIN public.prod_plan p ON p.id = o.plan_id
                LEFT JOIN public.quality_employees qe ON qe.ma_nv = o.ma_nv
                {bo_phan_join}
                LEFT JOIN public.dm_loai_hang lh ON lh.ten_loai = p.loai_hang
                LEFT JOIN public.dm_loai_hang_target tgt ON tgt.id_type = lh.id_type
                WHERE {where_sql_calc}
                GROUP BY o.date
                ORDER BY o.date
            """, tuple(base_params_calc))
            daily_rows = cur.fetchall()

            # By station summary
            cur.execute(f"""
                SELECT
                    COALESCE(NULLIF(o.station, ''), 'N/A') AS station,
                    SUM(o.delta) AS inspected_total,
                    SUM(CASE WHEN o.status = 'Failed' THEN o.delta ELSE 0 END) AS defect_total,
                    CASE
                        WHEN SUM(o.delta) > 0
                        THEN ROUND(SUM(CASE WHEN o.status = 'Failed' THEN o.delta ELSE 0 END)::numeric * 100.0 / SUM(o.delta), 4)
                        ELSE 0
                    END AS defect_rate,
                    CASE
                        WHEN SUM(o.delta) > 0
                        THEN ROUND(SUM(o.delta * COALESCE(tgt.target_percent, 0))::numeric / SUM(o.delta), 4)
                        ELSE 0
                    END AS target_rate
                FROM public.qc_output_sp_log o
                JOIN public.prod_plan p ON p.id = o.plan_id
                LEFT JOIN public.quality_employees qe ON qe.ma_nv = o.ma_nv
                {bo_phan_join}
                LEFT JOIN public.dm_loai_hang lh ON lh.ten_loai = p.loai_hang
                LEFT JOIN public.dm_loai_hang_target tgt ON tgt.id_type = lh.id_type
                WHERE {where_sql_station}
                GROUP BY COALESCE(NULLIF(o.station, ''), 'N/A')
                ORDER BY inspected_total DESC, station
            """, tuple(base_params_station))
            station_rows = cur.fetchall()

            # B. Defect rate by time buckets in selected day
            bucket_clauses = ["o.date = %s"]
            bucket_params: List = [focus_date]
            if don_vi:
                bucket_clauses.append("p.don_vi = %s")
                bucket_params.append(don_vi)
            if bo_phan:
                bucket_clauses.append(f"{resolved_bo_phan_expr} = %s")
                bucket_params.append(bo_phan)
            if station_for_calc:
                bucket_clauses.append("COALESCE(o.station, '') = %s")
                bucket_params.append(station_for_calc)
            if ma_hang:
                bucket_clauses.append("COALESCE(p.ma_hang, '') = %s")
                bucket_params.append(ma_hang)
            if type_name:
                bucket_clauses.append("COALESCE(tgt.type, '') = %s")
                bucket_params.append(type_name)
            bucket_where_sql = " AND ".join(bucket_clauses)

            cur.execute(f"""
                SELECT
                    {_bucket_case("timezone('Asia/Bangkok', o.created_at)::time")} AS time_bucket,
                    SUM(o.delta) AS inspected_total,
                    SUM(CASE WHEN o.status = 'Failed' THEN o.delta ELSE 0 END) AS defect_total,
                    CASE
                        WHEN SUM(o.delta) > 0
                        THEN ROUND(SUM(CASE WHEN o.status = 'Failed' THEN o.delta ELSE 0 END)::numeric * 100.0 / SUM(o.delta), 4)
                        ELSE 0
                    END AS defect_rate,
                    CASE
                        WHEN SUM(o.delta) > 0
                        THEN ROUND(SUM(o.delta * COALESCE(tgt.target_percent, 0))::numeric / SUM(o.delta), 4)
                        ELSE 0
                    END AS target_rate
                FROM public.qc_output_sp_log o
                JOIN public.prod_plan p ON p.id = o.plan_id
                LEFT JOIN public.quality_employees qe ON qe.ma_nv = o.ma_nv
                {bo_phan_join}
                LEFT JOIN public.dm_loai_hang lh ON lh.ten_loai = p.loai_hang
                LEFT JOIN public.dm_loai_hang_target tgt ON tgt.id_type = lh.id_type
                WHERE {bucket_where_sql}
                GROUP BY time_bucket
            """, tuple(bucket_params))
            bucket_rows = {r["time_bucket"]: r for r in cur.fetchall()}

            # "Thống kê theo vị trí" (panel cạnh chart B): defects theo (Bộ phận -> Chi tiết)
            # cho focus_date, dùng chung bộ lọc với chart B.
            pos_clauses = ["sp.date = %s"]
            pos_params: List = [focus_date]
            if don_vi:
                pos_clauses.append("p.don_vi = %s")
                pos_params.append(don_vi)
            if bo_phan:
                pos_clauses.append(f"{resolved_bo_phan_expr} = %s")
                pos_params.append(bo_phan)
            if station_for_calc:
                pos_clauses.append("COALESCE(sp.station, '') = %s")
                pos_params.append(station_for_calc)
            if ma_hang:
                pos_clauses.append("COALESCE(p.ma_hang, '') = %s")
                pos_params.append(ma_hang)
            if type_name:
                pos_clauses.append("COALESCE(tgt.type, '') = %s")
                pos_params.append(type_name)
            pos_where_sql = " AND ".join(pos_clauses)

            cur.execute(
                f"""
                SELECT
                    {_bucket_case("timezone('Asia/Bangkok', sp.created_at)::time")} AS time_bucket,
                    COALESCE(NULLIF(bp.ten_bo_phan, ''), '(Trống)') AS bo_phan_name,
                    COALESCE(NULLIF(ct.ten_chi_tiet, ''), '(Trống)') AS chi_tiet_name,
                    COALESCE(NULLIF(ml.ten_ma, ''), '(Trống)') AS ma_loi_name,
                    COUNT(*) AS qty
                FROM public.qc_defect d
                JOIN public.qc_error_log_sp sp ON sp.id = d.error_log_sp_id
                JOIN public.prod_plan p ON p.id = sp.plan_id
                LEFT JOIN public.quality_employees qe ON qe.ma_nv = sp.ma_nv
                {bo_phan_join}
                LEFT JOIN public.dm_loai_hang lh ON lh.ten_loai = p.loai_hang
                LEFT JOIN public.dm_loai_hang_target tgt ON tgt.id_type = lh.id_type
                LEFT JOIN public.dm_bo_phan bp ON bp.id = d.bo_phan_id
                LEFT JOIN public.dm_chi_tiet ct ON ct.id = d.chi_tiet_id
                LEFT JOIN public.dm_ma_loi ml ON ml.id = d.ma_loi_id
                WHERE {pos_where_sql}
                GROUP BY time_bucket, bo_phan_name, chi_tiet_name, ma_loi_name
                """,
                tuple(pos_params),
            )
            pos_rows = cur.fetchall()

            # Defect aggregates for C/D
            defect_clauses = ["sp.date BETWEEN %s AND %s"]
            defect_params: List = [date_from, date_to]
            if don_vi:
                defect_clauses.append("p.don_vi = %s")
                defect_params.append(don_vi)
            if bo_phan:
                defect_clauses.append(f"{resolved_bo_phan_expr} = %s")
                defect_params.append(bo_phan)
            if station_for_calc:
                defect_clauses.append("COALESCE(sp.station, '') = %s")
                defect_params.append(station_for_calc)
            if ma_hang:
                defect_clauses.append("COALESCE(p.ma_hang, '') = %s")
                defect_params.append(ma_hang)
            if type_name:
                defect_clauses.append("COALESCE(tgt.type, '') = %s")
                defect_params.append(type_name)
            defect_where_sql = " AND ".join(defect_clauses)

            cur.execute(f"""
                SELECT
                    COALESCE(NULLIF(bp.ten_bo_phan, ''), '(Trống)') AS bo_phan_name,
                    COALESCE(NULLIF(ct.ten_chi_tiet, ''), '(Trống)') AS chi_tiet_name,
                    COALESCE(NULLIF(ml.ten_ma, ''), d.ma_loi_id::text, '(Trống)') AS ma_loi_name,
                    COUNT(*) AS qty
                FROM public.qc_defect d
                JOIN public.qc_error_log_sp sp ON sp.id = d.error_log_sp_id
                JOIN public.prod_plan p ON p.id = sp.plan_id
                LEFT JOIN public.quality_employees qe ON qe.ma_nv = sp.ma_nv
                {bo_phan_join}
                LEFT JOIN public.dm_loai_hang lh ON lh.ten_loai = p.loai_hang
                LEFT JOIN public.dm_loai_hang_target tgt ON tgt.id_type = lh.id_type
                LEFT JOIN public.dm_bo_phan bp ON bp.id = d.bo_phan_id
                LEFT JOIN public.dm_chi_tiet ct ON ct.id = d.chi_tiet_id
                LEFT JOIN public.dm_ma_loi ml ON ml.id = d.ma_loi_id
                WHERE {defect_where_sql}
                GROUP BY bo_phan_name, chi_tiet_name, ma_loi_name
            """, tuple(defect_params))
            defect_agg_rows = cur.fetchall()

            # Rework done / recycle stats based on product-level defects
            cur.execute(f"""
                WITH per_sp AS (
                    SELECT
                        d.error_log_sp_id,
                        d.sp_index,
                        BOOL_AND(COALESCE(d.rework_done, FALSE)) AS done
                    FROM public.qc_defect d
                    WHERE d.error_log_sp_id IS NOT NULL
                      AND d.sp_index IS NOT NULL
                    GROUP BY d.error_log_sp_id, d.sp_index
                )
                SELECT
                    COUNT(*) AS defect_sp_total,
                    COUNT(*) FILTER (WHERE per_sp.done) AS rework_done_total
                FROM per_sp
                JOIN public.qc_error_log_sp sp ON sp.id = per_sp.error_log_sp_id
                JOIN public.prod_plan p ON p.id = sp.plan_id
                LEFT JOIN public.quality_employees qe ON qe.ma_nv = sp.ma_nv
                {bo_phan_join}
                LEFT JOIN public.dm_loai_hang lh ON lh.ten_loai = p.loai_hang
                LEFT JOIN public.dm_loai_hang_target tgt ON tgt.id_type = lh.id_type
                WHERE {defect_where_sql}
            """, tuple(defect_params))
            rework_stats_row = cur.fetchone() or {}

    def _to_float(v) -> float:
        try:
            return float(v or 0)
        except Exception:
            return 0.0

    daily = []
    for r in daily_rows:
        daily.append({
            "date": str(r["date"]) if r.get("date") else None,
            "inspected_total": int(r.get("inspected_total") or 0),
            "defect_total": int(r.get("defect_total") or 0),
            "defect_rate": _to_float(r.get("defect_rate")),
            "target_rate": _to_float(r.get("target_rate")),
        })

    station_summary = []
    for r in station_rows:
        station_summary.append({
            "station": r.get("station") or "N/A",
            "inspected_total": int(r.get("inspected_total") or 0),
            "defect_total": int(r.get("defect_total") or 0),
            "defect_rate": _to_float(r.get("defect_rate")),
            "target_rate": _to_float(r.get("target_rate")),
        })

    combo_by_bucket: Dict[str, Dict[str, int]] = {}
    for r in (pos_rows or []):
        bucket = r.get("time_bucket") or "N/A"
        bp_name = r.get("bo_phan_name") or "(Trống)"
        ct_name = r.get("chi_tiet_name") or "(Trống)"
        ml_name = r.get("ma_loi_name") or "(Trống)"
        qty = int(r.get("qty") or 0)
        if qty <= 0:
            continue
        combo_key = f"{bp_name} - {ct_name} - {ml_name}"
        combo_by_bucket.setdefault(bucket, {})
        combo_by_bucket[bucket][combo_key] = combo_by_bucket[bucket].get(combo_key, 0) + qty

    pos_buckets = []
    for b in bucket_order:
        combos_map = combo_by_bucket.get(b, {})
        combos = sorted(combos_map.items(), key=lambda x: (-x[1], x[0]))
        pos_buckets.append({
            "time_bucket": b,
            "combos": [{"combo": k, "count": v} for k, v in combos],
        })
    pos_stats = {"date": focus_date, "buckets": pos_buckets}

    by_bucket = []
    for b in bucket_order:
        r = bucket_rows.get(b) or {}
        by_bucket.append({
            "time_bucket": b,
            "inspected_total": int(r.get("inspected_total") or 0),
            "defect_total": int(r.get("defect_total") or 0),
            "defect_rate": _to_float(r.get("defect_rate")),
            "target_rate": _to_float(r.get("target_rate")),
        })

    bo_phan_counts: Dict[str, int] = {}
    chi_tiet_by_bo_phan: Dict[str, Dict[str, int]] = {}
    ma_loi_counts_all: Dict[str, int] = {}
    all_chi_tiet: Dict[str, int] = {}

    for r in defect_agg_rows:
        bp_name = r.get("bo_phan_name") or "(Trống)"
        ct_name = r.get("chi_tiet_name") or "(Trống)"
        ml_name = r.get("ma_loi_name") or "(Trống)"
        qty = int(r.get("qty") or 0)

        bo_phan_counts[bp_name] = bo_phan_counts.get(bp_name, 0) + qty
        chi_tiet_by_bo_phan.setdefault(bp_name, {})
        chi_tiet_by_bo_phan[bp_name][ct_name] = chi_tiet_by_bo_phan[bp_name].get(ct_name, 0) + qty
        ma_loi_counts_all[ml_name] = ma_loi_counts_all.get(ml_name, 0) + qty
        all_chi_tiet[ct_name] = all_chi_tiet.get(ct_name, 0) + qty

    bo_phan_total = sum(bo_phan_counts.values())
    top_bo_phan_items = sorted(bo_phan_counts.items(), key=lambda x: (-x[1], x[0]))[:5]
    top_bo_phan = [
        {
            "name": name,
            "count": cnt,
            "percent_total": round((cnt * 100.0 / bo_phan_total), 4) if bo_phan_total > 0 else 0.0,
        }
        for name, cnt in top_bo_phan_items
    ]

    selected_detail_bo_phan = detail_bo_phan or (top_bo_phan[0]["name"] if top_bo_phan else "")
    selected_chi_tiet_map = chi_tiet_by_bo_phan.get(selected_detail_bo_phan, {})
    chi_tiet_total = sum(selected_chi_tiet_map.values())
    top_chi_tiet_items = sorted(selected_chi_tiet_map.items(), key=lambda x: (-x[1], x[0]))[:5]
    top_chi_tiet = [
        {
            "name": name,
            "count": cnt,
            "percent_total": round((cnt * 100.0 / chi_tiet_total), 4) if chi_tiet_total > 0 else 0.0,
        }
        for name, cnt in top_chi_tiet_items
    ]

    ma_loi_filtered_counts: Dict[str, int] = {}
    for r in defect_agg_rows:
        bp_name = r.get("bo_phan_name") or "(Trống)"
        ct_name = r.get("chi_tiet_name") or "(Trống)"
        ml_name = r.get("ma_loi_name") or "(Trống)"
        qty = int(r.get("qty") or 0)
        if ma_loi_bo_phan and bp_name != ma_loi_bo_phan:
            continue
        if ma_loi_chi_tiet and ct_name != ma_loi_chi_tiet:
            continue
        ma_loi_filtered_counts[ml_name] = ma_loi_filtered_counts.get(ml_name, 0) + qty

    ma_loi_total = sum(ma_loi_filtered_counts.values())
    # Return a longer list for table display (still sorted by frequency).
    top_ma_loi_items = sorted(ma_loi_filtered_counts.items(), key=lambda x: (-x[1], x[0]))[:20]
    top_ma_loi = [
        {
            "name": name,
            "count": cnt,
            "percent_total": round((cnt * 100.0 / ma_loi_total), 4) if ma_loi_total > 0 else 0.0,
        }
        for name, cnt in top_ma_loi_items
    ]

    defect_combo_counts: Dict[str, int] = {}
    for r in defect_agg_rows:
        bp_name = r.get("bo_phan_name") or "(Trống)"
        ct_name = r.get("chi_tiet_name") or "(Trống)"
        ml_name = r.get("ma_loi_name") or "(Trống)"
        qty = int(r.get("qty") or 0)
        if qty <= 0:
            continue
        combo_key = f"{bp_name} - {ct_name} - {ml_name}"
        defect_combo_counts[combo_key] = defect_combo_counts.get(combo_key, 0) + qty
    defect_combos = [
        {"combo": k, "count": v}
        for k, v in sorted(defect_combo_counts.items(), key=lambda x: (-x[1], x[0]))
    ]

    defect_filter_bo_phan = sorted(bo_phan_counts.keys())
    if ma_loi_bo_phan:
        defect_filter_chi_tiet = sorted((chi_tiet_by_bo_phan.get(ma_loi_bo_phan) or {}).keys())
    else:
        defect_filter_chi_tiet = sorted(all_chi_tiet.keys())

    # Adjust inspected_total for hanging_line plans: add MES output from qc_hanging_output.
    # For these plans, qc_output_sp_log only has Failed entries ("+1 Đạt" hidden),
    # so inspected_total would equal defect_total without this correction.
    hl_by_date: Dict[str, int] = {}
    try:
        with core.get_db_connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                hl_clauses = ["p.source_system = 'hanging_line'", "ho.report_date BETWEEN %s AND %s"]
                hl_params: List = [date_from, date_to]
                if don_vi:
                    hl_clauses.append("ho.don_vi = %s")
                    hl_params.append(don_vi)
                if ma_hang:
                    hl_clauses.append("COALESCE(p.ma_hang, '') = %s")
                    hl_params.append(ma_hang)
                cur.execute(
                    f"""
                    SELECT ho.report_date, SUM(ho.qty) AS mes_qty
                    FROM public.qc_hanging_output ho
                    JOIN public.prod_plan p ON p.mono = ho.mono AND p.don_vi = ho.don_vi AND p.source_system = 'hanging_line'
                    WHERE {" AND ".join(hl_clauses)}
                    GROUP BY ho.report_date
                    """,
                    tuple(hl_params),
                )
                hl_by_date = {str(r["report_date"]): int(r["mes_qty"] or 0) for r in cur.fetchall()}
    except Exception:
        pass

    for d in daily:
        mes_add = hl_by_date.get(d["date"], 0)
        if mes_add > 0:
            d["inspected_total"] += mes_add
            d["defect_rate"] = round(d["defect_total"] * 100.0 / d["inspected_total"], 4) if d["inspected_total"] > 0 else 0.0

    totals = {
        "inspected_total": sum(x["inspected_total"] for x in daily),
        "defect_total": sum(x["defect_total"] for x in daily),
    }
    totals["defect_rate"] = round((totals["defect_total"] * 100.0 / totals["inspected_total"]), 4) if totals["inspected_total"] > 0 else 0.0
    totals["defect_sp_total"] = int(rework_stats_row.get("defect_sp_total") or 0)
    totals["rework_done_total"] = int(rework_stats_row.get("rework_done_total") or 0)
    totals["recycle_rate"] = round((totals["rework_done_total"] * 100.0 / totals["defect_sp_total"]), 4) if totals["defect_sp_total"] > 0 else 0.0

    return {
        "range": {"date_from": date_from, "date_to": date_to, "focus_date": focus_date},
        "active_station": station_for_calc,
        "totals": totals,
        "daily": daily,
        "by_bucket": by_bucket,
        "pos_stats": pos_stats,
        "station_summary": station_summary,
        "top_bo_phan": {
            "total": bo_phan_total,
            "items": top_bo_phan,
        },
        "top_chi_tiet": {
            "selected_bo_phan": selected_detail_bo_phan,
            "total": chi_tiet_total,
            "items": top_chi_tiet,
        },
        "top_ma_loi": {
            "filter_bo_phan": ma_loi_bo_phan or "",
            "filter_chi_tiet": ma_loi_chi_tiet or "",
            "total": ma_loi_total,
            "items": top_ma_loi,
        },
        "defect_combos": defect_combos,
        "defect_filters": {
            "bo_phan": defect_filter_bo_phan,
            "chi_tiet": defect_filter_chi_tiet,
        },
    }
