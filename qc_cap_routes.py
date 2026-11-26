"""CAP (hành động khắc phục) của QC — danh sách, xử lý, heartbeat, backfill.

Tách từ main.py. Hàm/biến dùng chung (DB, đăng nhập, phân quyền, template, cấu hình...) vẫn ở main.py
và được gọi qua `core.<tên>` lúc chạy, nên test patch `main.<tên>` vẫn có hiệu lực.
"""
import psycopg2
import psycopg2.extras
import psycopg2.pool
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from typing import Any, Dict, List, Optional

from app_core import core

router = APIRouter()


class QcErrorDpsPayload(BaseModel):
    plan_id: int
    date: str
    time_bucket: str
    station: Optional[str] = None
    bo_phan: Optional[str] = None
    loai_loi: str
    ma_loi: Optional[str] = None
    vi_tri: Optional[str] = None
    nn_cong_nhan: bool = False
    nn_may_moc: bool = False
    nn_phuong_phap: bool = False
    nn_nguyen_phu_lieu: bool = False
    nn_moi_truong: bool = False
    mo_ta: Optional[str] = None
    giai_phap: Optional[str] = None
    tram_ap_dung: Optional[str] = None
    tien_do: Optional[str] = None
    ngay_hoan_thanh: Optional[str] = None
    ket_luan: Optional[str] = None
    ghi_chu: Optional[str] = None


COMBO_SHARED_CAP_TYPES = {
    "Lỗi đại trà",
    "Lỗi vượt mục tiêu",
    "Tỉ lệ theo dạng lỗi",
    "CAP theo combo lỗi",
}


def normalize_qc_cap_loai_loi(loai_loi: Optional[str], ma_loi: Optional[str], vi_tri: Optional[str]) -> str:
    normalized = (loai_loi or "").strip()
    if normalized in COMBO_SHARED_CAP_TYPES and ((ma_loi or "").strip() or (vi_tri or "").strip()):
        return "CAP theo combo lỗi"
    return normalized

@router.post("/api/qc/cap/action")
def upsert_qc_cap_action(
    payload: QcErrorDpsPayload,
    _user: Dict = Depends(core.require_qa_admin_api_user),
):
    loai_loi = normalize_qc_cap_loai_loi(payload.loai_loi, payload.ma_loi, payload.vi_tri)
    if not loai_loi:
        raise HTTPException(status_code=400, detail="Loai loi khong duoc de trong")
    time_bucket = (payload.time_bucket or "").strip()
    if not time_bucket:
        raise HTTPException(status_code=400, detail="Time bucket khong duoc de trong")
    ma_loi = (payload.ma_loi or "").strip() or None
    vi_tri = (payload.vi_tri or "").strip() or None
    station = (payload.station or "").strip() or None
    bo_phan = (payload.bo_phan or "").strip() or None

    with core.get_db_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT id
                FROM public.qc_error_dps
                WHERE plan_id = %s
                  AND date = %s
                  AND time_bucket = %s
                  AND COALESCE(station, '') = COALESCE(%s, '')
                  AND COALESCE(bo_phan, '') = COALESCE(%s, '')
                  AND loai_loi = %s
                  AND COALESCE(ma_loi, '') = COALESCE(%s, '')
                  AND COALESCE(vi_tri, '') = COALESCE(%s, '')
                """,
                (payload.plan_id, payload.date, time_bucket, station, bo_phan, loai_loi, ma_loi, vi_tri),
            )
            existing = cur.fetchone()

            if existing:
                cur.execute(
                    """
                    UPDATE public.qc_error_dps
                    SET nn_cong_nhan = %s,
                        nn_may_moc = %s,
                        nn_phuong_phap = %s,
                        nn_nguyen_phu_lieu = %s,
                        nn_moi_truong = %s,
                        mo_ta = %s,
                        giai_phap = %s,
                        tram_ap_dung = %s,
                        tien_do = %s,
                        ngay_hoan_thanh = %s,
                        ket_luan = %s,
                        ghi_chu = %s,
                        updated_at = NOW()
                    WHERE id = %s
                    RETURNING id
                    """,
                    (
                        payload.nn_cong_nhan,
                        payload.nn_may_moc,
                        payload.nn_phuong_phap,
                        payload.nn_nguyen_phu_lieu,
                        payload.nn_moi_truong,
                        payload.mo_ta,
                        payload.giai_phap,
                        payload.tram_ap_dung,
                        payload.tien_do,
                        payload.ngay_hoan_thanh,
                        payload.ket_luan,
                        payload.ghi_chu,
                        existing["id"],
                    ),
                )
                action_id = cur.fetchone()["id"]
            else:
                cur.execute(
                    """
                    INSERT INTO public.qc_error_dps (
                        plan_id, date, time_bucket, station, bo_phan, loai_loi, ma_loi, vi_tri,
                        nn_cong_nhan, nn_may_moc, nn_phuong_phap, nn_nguyen_phu_lieu, nn_moi_truong,
                        mo_ta, giai_phap, tram_ap_dung, tien_do, ngay_hoan_thanh, ket_luan, ghi_chu
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (
                        payload.plan_id,
                        payload.date,
                        time_bucket,
                        station,
                        bo_phan,
                        loai_loi,
                        ma_loi,
                        vi_tri,
                        payload.nn_cong_nhan,
                        payload.nn_may_moc,
                        payload.nn_phuong_phap,
                        payload.nn_nguyen_phu_lieu,
                        payload.nn_moi_truong,
                        payload.mo_ta,
                        payload.giai_phap,
                        payload.tram_ap_dung,
                        payload.tien_do,
                        payload.ngay_hoan_thanh,
                        payload.ket_luan,
                        payload.ghi_chu,
                    ),
                )
                action_id = cur.fetchone()["id"]
        conn.commit()

    return {"status": "ok", "id": action_id}


@router.get("/api/qc/cap/action")
def get_qc_cap_action(
    request: Request,
    plan_id: int = Query(...),
    date: str = Query(...),
    time_bucket: str = Query(...),
    station: Optional[str] = Query(None),
    bo_phan: Optional[str] = Query(None),
    loai_loi: str = Query(...),
    ma_loi: Optional[str] = Query(None),
    vi_tri: Optional[str] = Query(None),
):
    effective_don_vi, user = core.resolve_qc_don_vi_scope(request, None)
    loai_loi = normalize_qc_cap_loai_loi(loai_loi, ma_loi, vi_tri)
    with core.get_db_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            if core.is_qc_don_vi_scoped_role(user):
                cur.execute(
                    "SELECT 1 FROM public.prod_plan WHERE id = %s AND don_vi = %s",
                    (plan_id, effective_don_vi),
                )
                if not cur.fetchone():
                    raise HTTPException(status_code=403, detail="Không có quyền xem dữ liệu ngoài đơn vị được gán.")
            cur.execute(
                """
                SELECT *
                FROM public.qc_error_dps
                WHERE plan_id = %s
                  AND date = %s
                  AND time_bucket = %s
                  AND COALESCE(station, '') = COALESCE(%s, '')
                  AND COALESCE(bo_phan, '') = COALESCE(%s, '')
                  AND loai_loi = %s
                  AND COALESCE(ma_loi, '') = COALESCE(%s, '')
                  AND COALESCE(vi_tri, '') = COALESCE(%s, '')
                LIMIT 1
                """,
                (plan_id, date, time_bucket, station, bo_phan, loai_loi, ma_loi, vi_tri),
            )
            row = cur.fetchone()
    if not row:
        return {"status": "not_found"}
    row["date"] = str(row["date"]) if row.get("date") else None
    row["ngay_hoan_thanh"] = str(row["ngay_hoan_thanh"]) if row.get("ngay_hoan_thanh") else None
    return {"status": "ok", "row": row}

@router.get("/api/qc/cap")
def api_qc_cap(
    request: Request,
    date: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    don_vi: Optional[str] = Query(None),
    bo_phan: Optional[str] = Query(None),
    station: Optional[str] = Query(None),
):
    """Tổng hợp dữ liệu CAP theo ngày và mốc thời gian."""
    don_vi, _user = core.resolve_qc_don_vi_scope(request, don_vi)
    if date:
        date_from = date_to = date
    if not date_from or not date_to:
        today = datetime.now().strftime("%Y-%m-%d")
        date_from = date_from or today
        date_to = date_to or today

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

    with core.get_db_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            # Detect prod_plan.bo_phan type to avoid jsonb/text mismatch across deployments
            use_jsonb_bo_phan = core._detect_bo_phan_jsonb()

            bo_phan_expr = "bp.bo_phan_text" if use_jsonb_bo_phan else "p.bo_phan"
            bo_phan_join = (
                """
                LEFT JOIN LATERAL (
                    SELECT string_agg(value, ', ') AS bo_phan_text
                    FROM jsonb_array_elements_text(COALESCE(p.bo_phan, '[]'::jsonb)) AS t(value)
                ) bp ON true
                """
                if use_jsonb_bo_phan
                else ""
            )
            bo_phan_order = bo_phan_expr

            # Output tổng hợp theo mốc thời gian
            output_params = [date_from, date_to]
            output_where = []
            if station:
                output_where.append("o.station = %s")
                output_params.append(station)

            cur.execute(f"""
                WITH output_logs AS (
                    SELECT
                        o.plan_id,
                        o.date,
                        o.station,
                        COALESCE(qe.bo_phan, '') AS qc_bo_phan,
                        {_bucket_case("timezone('Asia/Bangkok', o.created_at)::time")} AS time_bucket,
                        SUM(o.delta) AS output_total,
                        SUM(CASE WHEN o.status = 'Failed' THEN o.delta ELSE 0 END) AS defect_total
                    FROM public.qc_output_sp_log o
                    LEFT JOIN public.quality_employees qe ON qe.ma_nv = o.ma_nv
                    WHERE o.date BETWEEN %s AND %s
                    {("AND " + " AND ".join(output_where)) if output_where else ""}
                    GROUP BY o.plan_id, o.date, o.station, qc_bo_phan, time_bucket
                )
                SELECT
                    o.*,
                    p.don_vi,
                    COALESCE(NULLIF(o.qc_bo_phan, ''), COALESCE({bo_phan_expr}, ''), '') AS bo_phan,
                    p.ke_hoach,
                    p.ma_hang,
                    p.ngay_rc,
                    p.san_luong,
                    p.loai_hang
                FROM output_logs o
                JOIN public.prod_plan p ON p.id = o.plan_id
                {bo_phan_join}
                WHERE 1=1
                {("AND p.don_vi = %s") if don_vi else ""}
                {("AND COALESCE(NULLIF(o.qc_bo_phan, ''), COALESCE(" + bo_phan_expr + ", ''), '') = %s") if bo_phan else ""}
                ORDER BY o.date, o.time_bucket, p.don_vi, COALESCE(NULLIF(o.qc_bo_phan, ''), {bo_phan_order}, ''), o.station
            """, tuple(output_params + ([don_vi] if don_vi else []) + ([bo_phan] if bo_phan else [])))
            output_rows = cur.fetchall()

            # Target theo loại hàng
            cur.execute("""
                SELECT lh.ten_loai, tgt.target_percent
                FROM public.dm_loai_hang lh
                LEFT JOIN public.dm_loai_hang_target tgt ON tgt.id_type = lh.id_type
            """)
            target_map = {r["ten_loai"]: r["target_percent"] for r in cur.fetchall() if r.get("ten_loai")}

            # Lỗi nghiêm trọng
            cur.execute(f"""
                SELECT
                    sp.plan_id,
                    sp.date,
                    sp.station,
                    COALESCE(qe.bo_phan, '') AS qc_bo_phan,
                    {_bucket_case("timezone('Asia/Bangkok', d.created_at)::time")} AS time_bucket,
                    COALESCE(ml.ten_ma, d.ma_loi_id::text) AS ma_loi,
                    COALESCE(bp.ten_bo_phan, '') AS bo_phan,
                    COALESCE(ct.ten_chi_tiet, '') AS chi_tiet,
                    COUNT(*) AS qty
                FROM public.qc_defect d
                JOIN public.qc_error_log_sp sp ON sp.id = d.error_log_sp_id
                LEFT JOIN public.quality_employees qe ON qe.ma_nv = sp.ma_nv
                LEFT JOIN public.dm_ma_loi ml ON ml.id = d.ma_loi_id
                LEFT JOIN public.dm_bo_phan bp ON bp.id = d.bo_phan_id
                LEFT JOIN public.dm_chi_tiet ct ON ct.id = d.chi_tiet_id
                WHERE sp.date BETWEEN %s AND %s
                  AND d.muc_do ILIKE '%%nghiêm%%'
                GROUP BY
                    sp.plan_id,
                    sp.date,
                    sp.station,
                    qc_bo_phan,
                    time_bucket,
                    COALESCE(ml.ten_ma, d.ma_loi_id::text),
                    COALESCE(bp.ten_bo_phan, ''),
                    COALESCE(ct.ten_chi_tiet, '')
                ORDER BY sp.date, time_bucket, sp.station
            """, (date_from, date_to))
            serious_rows = cur.fetchall()

            # Lỗi đại trà (mới): combo (Vị trí [Bộ phận - Chi tiết] + Mã lỗi) tính theo tỉ lệ trên tổng kiểm trong từng mốc thời gian.
            # Đếm theo số sản phẩm (DISTINCT error_log_sp_id + sp_index) mắc combo đó trong bucket.
            cur.execute(f"""
                SELECT
                    t.plan_id,
                    t.date,
                    t.station,
                    t.qc_bo_phan,
                    t.time_bucket,
                    t.ma_loi,
                    t.bo_phan,
                    t.chi_tiet,
                    COUNT(*) AS qty
                FROM (
                    SELECT DISTINCT
                        sp.plan_id,
                        sp.date,
                        sp.station,
                        COALESCE(qe.bo_phan, '') AS qc_bo_phan,
                        {_bucket_case("timezone('Asia/Bangkok', d.created_at)::time")} AS time_bucket,
                        COALESCE(ml.ten_ma, d.ma_loi_id::text) AS ma_loi,
                        COALESCE(bp.ten_bo_phan, '') AS bo_phan,
                        COALESCE(ct.ten_chi_tiet, '') AS chi_tiet,
                        d.error_log_sp_id,
                        d.sp_index
                    FROM public.qc_defect d
                    JOIN public.qc_error_log_sp sp ON sp.id = d.error_log_sp_id
                    LEFT JOIN public.quality_employees qe ON qe.ma_nv = sp.ma_nv
                    LEFT JOIN public.dm_ma_loi ml ON ml.id = d.ma_loi_id
                    LEFT JOIN public.dm_bo_phan bp ON bp.id = d.bo_phan_id
                    LEFT JOIN public.dm_chi_tiet ct ON ct.id = d.chi_tiet_id
                    WHERE sp.date BETWEEN %s AND %s
                      AND d.error_log_sp_id IS NOT NULL
                      AND d.sp_index IS NOT NULL
                ) t
                GROUP BY
                    t.plan_id,
                    t.date,
                    t.station,
                    t.qc_bo_phan,
                    t.time_bucket,
                    t.ma_loi,
                    t.bo_phan,
                    t.chi_tiet
                ORDER BY t.date, t.time_bucket, t.station
            """, (date_from, date_to))
            mass_combo_rows = cur.fetchall()

            # Ảnh lỗi theo plan/date/bucket/ma_loi/vi_tri
            cur.execute(f"""
                SELECT
                    sp.plan_id,
                    sp.date,
                    sp.station,
                    COALESCE(qe.bo_phan, '') AS qc_bo_phan,
                    {_bucket_case("timezone('Asia/Bangkok', d.created_at)::time")} AS time_bucket,
                    COALESCE(ml.ten_ma, d.ma_loi_id::text) AS ma_loi,
                    COALESCE(bp.ten_bo_phan, '') AS bo_phan,
                    COALESCE(ct.ten_chi_tiet, '') AS chi_tiet,
                    ARRAY_REMOVE(ARRAY_AGG(DISTINCT d.image_path), NULL) AS images
                FROM public.qc_defect d
                JOIN public.qc_error_log_sp sp ON sp.id = d.error_log_sp_id
                LEFT JOIN public.quality_employees qe ON qe.ma_nv = sp.ma_nv
                LEFT JOIN public.dm_ma_loi ml ON ml.id = d.ma_loi_id
                LEFT JOIN public.dm_bo_phan bp ON bp.id = d.bo_phan_id
                LEFT JOIN public.dm_chi_tiet ct ON ct.id = d.chi_tiet_id
                WHERE sp.date BETWEEN %s AND %s
                  AND d.image_path IS NOT NULL
                GROUP BY
                    sp.plan_id,
                    sp.date,
                    sp.station,
                    qc_bo_phan,
                    time_bucket,
                    COALESCE(ml.ten_ma, d.ma_loi_id::text),
                    COALESCE(bp.ten_bo_phan, ''),
                    COALESCE(ct.ten_chi_tiet, '')
            """, (date_from, date_to))
            image_rows = cur.fetchall()

            # Lỗi nguy cơ hàng loạt
            cur.execute(f"""
                SELECT
                    plan_id,
                    date,
                    qdm.station,
                    COALESCE(qe.bo_phan, '') AS qc_bo_phan,
                    {_bucket_case("qdm.time")} AS time_bucket,
                    COALESCE(ma_loi, '') AS ma_loi,
                    COALESCE(qdm.bo_phan, '') AS bo_phan,
                    COALESCE(qdm.chi_tiet, '') AS chi_tiet,
                    COUNT(*) AS occurrences
                FROM public.qc_defect_multi qdm
                LEFT JOIN public.quality_employees qe ON qe.ma_nv = qdm.ma_nv
                WHERE date BETWEEN %s AND %s
                GROUP BY plan_id, date, qdm.station, qc_bo_phan, time_bucket, ma_loi, qdm.bo_phan, qdm.chi_tiet
                ORDER BY date, time_bucket, qdm.station
            """, (date_from, date_to))
            multi_rows = cur.fetchall()

            # Rework verified count (#SP đã xác nhận)
            cur.execute(f"""
                SELECT
                    sp.plan_id,
                    sp.date,
                    sp.station,
                    COALESCE(qe.bo_phan, '') AS qc_bo_phan,
                    {_bucket_case("timezone('Asia/Bangkok', per_sp.first_created_at)::time")} AS time_bucket,
                    COUNT(*) FILTER (WHERE per_sp.done) AS rework_done_count
                FROM public.qc_error_log_sp sp
                LEFT JOIN public.quality_employees qe ON qe.ma_nv = sp.ma_nv
                JOIN (
                    SELECT
                        d.error_log_sp_id,
                        d.sp_index,
                        MIN(d.created_at) AS first_created_at,
                        BOOL_AND(COALESCE(d.rework_done, FALSE)) AS done
                    FROM public.qc_defect d
                    GROUP BY d.error_log_sp_id, d.sp_index
                ) per_sp ON per_sp.error_log_sp_id = sp.id
                WHERE sp.date BETWEEN %s AND %s
                GROUP BY sp.plan_id, sp.date, sp.station, qc_bo_phan, time_bucket
            """, (date_from, date_to))
            rework_rows = cur.fetchall()

    def _vi_tri(bo_phan: str, chi_tiet: str) -> str:
        parts = [p for p in [bo_phan, chi_tiet] if p]
        return " - ".join(parts) if parts else "--"

    def _cap_key(row):
        return (
            row["plan_id"],
            str(row["date"]),
            row["time_bucket"],
            row.get("station") or "",
            row.get("qc_bo_phan") or "",
        )

    serious_map = {}
    for r in serious_rows:
        key = _cap_key(r)
        serious_map.setdefault(key, []).append({
            "ma_loi": r["ma_loi"] or "--",
            "vi_tri": _vi_tri(r.get("bo_phan"), r.get("chi_tiet")),
            "qty": int(r["qty"] or 0)
        })

    image_map = {}
    for r in image_rows:
        key = (
            r["plan_id"],
            str(r["date"]),
            r["time_bucket"],
            r.get("station") or "",
            r.get("qc_bo_phan") or "",
            r["ma_loi"] or "--",
            _vi_tri(r.get("bo_phan"), r.get("chi_tiet")),
        )
        images = [f"/api/images/{p}" for p in (r.get("images") or []) if p]
        image_map[key] = images

    multi_map = {}
    for r in multi_rows:
        key = _cap_key(r)
        multi_map.setdefault(key, []).append({
            "ma_loi": r["ma_loi"] or "--",
            "vi_tri": _vi_tri(r.get("bo_phan"), r.get("chi_tiet")),
            "consecutive": 3,
            "occurrences": int(r["occurrences"] or 0)
        })

    mass_combo_map = {}
    for r in mass_combo_rows:
        key = _cap_key(r)
        mass_combo_map.setdefault(key, []).append({
            "ma_loi": r.get("ma_loi") or "--",
            "vi_tri": _vi_tri(r.get("bo_phan"), r.get("chi_tiet")),
            "qty": int(r.get("qty") or 0),
        })

    rework_map = {}
    for r in rework_rows:
        key = _cap_key(r)
        rework_map[key] = int(r.get("rework_done_count") or 0)

    # Group output rows by date/time bucket
    dates = {}
    for r in output_rows:
        date_key = str(r["date"])
        bucket = r["time_bucket"]
        plan_id = r["plan_id"]
        key = (plan_id, date_key, bucket, r.get("station") or "", r.get("qc_bo_phan") or "")

        output_total = int(r["output_total"] or 0)
        defect_total = int(r["defect_total"] or 0)
        rate = (defect_total / output_total * 100) if output_total > 0 else 0
        target_percent = target_map.get(r.get("loai_hang"))
        target_percent_float = float(target_percent) if target_percent is not None else None
        bucket_over_target = (
            output_total > 0
            and target_percent_float is not None
            and rate > target_percent_float
        )

        combo_items = list(mass_combo_map.get(key) or [])
        mass_list = []
        over_target_list = []
        for item in combo_items:
            qty = int(item.get("qty") or 0)
            if qty <= 0:
                continue
            combo_rate = (qty * 100.0 / output_total) if output_total > 0 else 0.0
            combo_entry = {
                "ma_loi": item.get("ma_loi") or "--",
                "vi_tri": item.get("vi_tri") or "--",
                "qty": qty,
                "rate_percent": combo_rate,
            }
            if output_total <= 0:
                continue
            if (qty / output_total) >= 0.15:
                mass_list.append(dict(combo_entry))
            if target_percent_float is not None and combo_rate > target_percent_float:
                over_target_list.append(dict(combo_entry))
        mass_list.sort(key=lambda x: (-int(x.get("qty") or 0), str(x.get("ma_loi") or ""), str(x.get("vi_tri") or "")))

        combo_rate_list = []
        if defect_total > 0:
            for item in combo_items:
                qty = int(item.get("qty") or 0)
                if qty <= 0:
                    continue
                combo_rate_list.append({
                    "ma_loi": item.get("ma_loi") or "--",
                    "vi_tri": item.get("vi_tri") or "--",
                    "qty": qty,
                    "total_qty": defect_total,
                    "ratio_percent": (qty * 100.0 / defect_total),
                    "product_rate_percent": rate,
                    "needs_cap": bucket_over_target,
                    "cap_status_text": "Cần làm CAP" if bucket_over_target else "Không cần làm CAP",
                })
        combo_rate_list.sort(key=lambda x: (-float(x.get("ratio_percent") or 0), -int(x.get("qty") or 0), str(x.get("ma_loi") or ""), str(x.get("vi_tri") or "")))
        combo_rate_top3 = combo_rate_list[:3]
        over_target_list.sort(key=lambda x: (-float(x.get("rate_percent") or 0), -int(x.get("qty") or 0), str(x.get("ma_loi") or ""), str(x.get("vi_tri") or "")))

        row = {
            "plan_id": plan_id,
            "date": date_key,
            "time_bucket": bucket,
            "don_vi": r.get("don_vi") or "--",
            "bo_phan": r.get("bo_phan") or "--",
            "qc_bo_phan": r.get("qc_bo_phan") or "",
            "station": r.get("station") or "",
            "ke_hoach": r.get("ke_hoach") or "--",
            "ke_hoach_hien_thi": core.build_prod_plan_display_name(r),
            "ma_hang": r.get("ma_hang") or "",
            "ngay_rc": str(r.get("ngay_rc")) if r.get("ngay_rc") else None,
            "san_luong": r.get("san_luong"),
            "output_total": output_total,
            "defect_total": defect_total,
            "rework_done_count": rework_map.get(key, 0),
            "rate_percent": rate,
            "target_percent": target_percent_float,
            "over_target": (len(over_target_list) > 0) or bucket_over_target,
            "over_target_list": over_target_list,
            "is_mass": len(mass_list) > 0,
            "mass_list": mass_list,
            "combo_rate_top3": combo_rate_top3,
            "serious_list": serious_map.get(key, []),
            "multi_list": multi_map.get(key, []),
            "has_serious": len(serious_map.get(key, [])) > 0,
            "has_multi": len(multi_map.get(key, [])) > 0,
        }

        dates.setdefault(date_key, {}).setdefault(bucket, []).append(row)

    # Sort buckets in desired order
    bucket_order = ["7H30 - 9H30", "9H30 - 11H30", "12H30 - 14H30", "14H30 - 16H30", "Sau 16H30"]
    result = []
    for date_key in sorted(dates.keys()):
        buckets = []
        for b in bucket_order:
            if b in dates[date_key]:
                buckets.append({"time_bucket": b, "rows": dates[date_key][b]})
        result.append({"date": date_key, "buckets": buckets})

    # Pre-create qc_error_dps records for rows that have errors
    precreate_keys = set()
    for date_key, buckets in dates.items():
        for bucket, rows in buckets.items():
            for r in rows:
                bo_phan_key = r.get("qc_bo_phan") or r.get("bo_phan") or ""
                for item in (r.get("serious_list") or []):
                    precreate_keys.add((
                        r["plan_id"],
                        date_key,
                        bucket,
                        r.get("station") or "",
                        bo_phan_key,
                        "Lỗi nghiêm trọng",
                        item.get("ma_loi") or None,
                        item.get("vi_tri") or None,
                    ))
                for item in (r.get("multi_list") or []):
                    precreate_keys.add((
                        r["plan_id"],
                        date_key,
                        bucket,
                        r.get("station") or "",
                        bo_phan_key,
                        "Lỗi nguy cơ hàng loạt",
                        item.get("ma_loi") or None,
                        item.get("vi_tri") or None,
                    ))
                for item in (r.get("over_target_list") or []):
                    precreate_keys.add((
                        r["plan_id"],
                        date_key,
                        bucket,
                        r.get("station") or "",
                        bo_phan_key,
                        "CAP theo combo lỗi",
                        item.get("ma_loi") or None,
                        item.get("vi_tri") or None,
                    ))
                for item in (r.get("mass_list") or []):
                    precreate_keys.add((
                        r["plan_id"],
                        date_key,
                        bucket,
                        r.get("station") or "",
                        bo_phan_key,
                        "CAP theo combo lỗi",
                        item.get("ma_loi") or None,
                        item.get("vi_tri") or None,
                    ))

    if precreate_keys:
        with core.get_db_connection() as conn:
            with conn.cursor() as cur:
                psycopg2.extras.execute_values(
                    cur,
                    """
                    INSERT INTO public.qc_error_dps
                        (plan_id, date, time_bucket, station, bo_phan, loai_loi, ma_loi, vi_tri)
                    VALUES %s
                    ON CONFLICT DO NOTHING
                    """,
                    list(precreate_keys),
                )
            conn.commit()

    # Mark which rows already have input data
    action_map = {}
    with core.get_db_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT
                    id,
                    plan_id,
                    date,
                    time_bucket,
                    station,
                    bo_phan,
                    loai_loi,
                    COALESCE(ma_loi, '') AS ma_loi,
                    COALESCE(vi_tri, '') AS vi_tri,
                    hdkp_pdf,
                    (
                        nn_cong_nhan OR nn_may_moc OR nn_phuong_phap OR nn_nguyen_phu_lieu OR nn_moi_truong
                        OR NULLIF(TRIM(COALESCE(mo_ta, '')), '') IS NOT NULL
                        OR NULLIF(TRIM(COALESCE(giai_phap, '')), '') IS NOT NULL
                        OR NULLIF(TRIM(COALESCE(tram_ap_dung, '')), '') IS NOT NULL
                        OR ngay_hoan_thanh IS NOT NULL
                        OR NULLIF(TRIM(COALESCE(ket_luan, '')), '') IS NOT NULL
                        OR NULLIF(TRIM(COALESCE(ghi_chu, '')), '') IS NOT NULL
                    ) AS has_input
                FROM public.qc_error_dps
                WHERE date BETWEEN %s AND %s
                """,
                (date_from, date_to),
            )
            for r in cur.fetchall():
                normalized_loai_loi = normalize_qc_cap_loai_loi(r["loai_loi"], r.get("ma_loi"), r.get("vi_tri"))
                key = (
                    r["plan_id"],
                    str(r["date"]),
                    r["time_bucket"],
                    r.get("station") or "",
                    r.get("bo_phan") or "",
                    normalized_loai_loi,
                    r.get("ma_loi") or "",
                    r.get("vi_tri") or "",
                )
                action_map[key] = {
                    "has_input": bool(r.get("has_input")),
                    "id": r.get("id"),
                    "hdkp_pdf": r.get("hdkp_pdf"),
                }

    # Attach action_done flags
    for date_key, buckets in dates.items():
        for bucket, rows in buckets.items():
            for row in rows:
                bo_phan_key = row.get("qc_bo_phan") or row.get("bo_phan") or ""
                for item in row.get("serious_list", []):
                    key = (
                        row["plan_id"],
                        date_key,
                        bucket,
                        row.get("station") or "",
                        bo_phan_key,
                        "Lỗi nghiêm trọng",
                        item.get("ma_loi") or "",
                        item.get("vi_tri") or "",
                    )
                    item["action_done"] = action_map.get(key, {}).get("has_input", False)
                    item["action_id"] = action_map.get(key, {}).get("id")
                    item["hdkp_pdf"] = action_map.get(key, {}).get("hdkp_pdf")
                    img_key = (
                        row["plan_id"],
                        date_key,
                        bucket,
                        row.get("station") or "",
                        bo_phan_key,
                        item.get("ma_loi") or "--",
                        item.get("vi_tri") or "--",
                    )
                    item["images"] = image_map.get(img_key, [])
                for item in row.get("multi_list", []):
                    key = (
                        row["plan_id"],
                        date_key,
                        bucket,
                        row.get("station") or "",
                        bo_phan_key,
                        "Lỗi nguy cơ hàng loạt",
                        item.get("ma_loi") or "",
                        item.get("vi_tri") or "",
                    )
                    item["action_done"] = action_map.get(key, {}).get("has_input", False)
                    item["action_id"] = action_map.get(key, {}).get("id")
                    item["hdkp_pdf"] = action_map.get(key, {}).get("hdkp_pdf")
                    img_key = (
                        row["plan_id"],
                        date_key,
                        bucket,
                        row.get("station") or "",
                        bo_phan_key,
                        item.get("ma_loi") or "--",
                        item.get("vi_tri") or "--",
                    )
                    item["images"] = image_map.get(img_key, [])
                for item in row.get("mass_list", []):
                    key = (
                        row["plan_id"],
                        date_key,
                        bucket,
                        row.get("station") or "",
                        bo_phan_key,
                        "CAP theo combo lỗi",
                        item.get("ma_loi") or "",
                        item.get("vi_tri") or "",
                    )
                    item["action_done"] = action_map.get(key, {}).get("has_input", False)
                    item["action_id"] = action_map.get(key, {}).get("id")
                    item["hdkp_pdf"] = action_map.get(key, {}).get("hdkp_pdf")
                    img_key = (
                        row["plan_id"],
                        date_key,
                        bucket,
                        row.get("station") or "",
                        bo_phan_key,
                        item.get("ma_loi") or "--",
                        item.get("vi_tri") or "--",
                    )
                    item["images"] = image_map.get(img_key, [])

                for item in row.get("over_target_list", []):
                    key = (
                        row["plan_id"],
                        date_key,
                        bucket,
                        row.get("station") or "",
                        bo_phan_key,
                        "CAP theo combo lỗi",
                        item.get("ma_loi") or "",
                        item.get("vi_tri") or "",
                    )
                    item["action_done"] = action_map.get(key, {}).get("has_input", False)
                    item["action_id"] = action_map.get(key, {}).get("id")
                    item["hdkp_pdf"] = action_map.get(key, {}).get("hdkp_pdf")
                    img_key = (
                        row["plan_id"],
                        date_key,
                        bucket,
                        row.get("station") or "",
                        bo_phan_key,
                        item.get("ma_loi") or "--",
                        item.get("vi_tri") or "--",
                    )
                    item["images"] = image_map.get(img_key, [])

                for item in row.get("combo_rate_top3", []):
                    key = (
                        row["plan_id"],
                        date_key,
                        bucket,
                        row.get("station") or "",
                        bo_phan_key,
                        "CAP theo combo lỗi",
                        item.get("ma_loi") or "",
                        item.get("vi_tri") or "",
                    )
                    item["action_done"] = action_map.get(key, {}).get("has_input", False)
                    item["action_id"] = action_map.get(key, {}).get("id")
                    item["hdkp_pdf"] = action_map.get(key, {}).get("hdkp_pdf")
                    img_key = (
                        row["plan_id"],
                        date_key,
                        bucket,
                        row.get("station") or "",
                        bo_phan_key,
                        item.get("ma_loi") or "--",
                        item.get("vi_tri") or "--",
                    )
                    item["images"] = image_map.get(img_key, [])

    return {"dates": result}


@router.get("/api/qc/cap/heartbeat")
def api_qc_cap_heartbeat(
    date: Optional[str] = Query(None),
):
    """Return latest update marker for QC output (SP) on a date."""
    if not date:
        date = datetime.now().strftime("%Y-%m-%d")
    with core.get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT MAX(created_at) AS latest
                FROM public.qc_output_sp_log
                WHERE date = %s
                """,
                (date,),
            )
            row = cur.fetchone()
            latest = row[0] if row else None
    return {"date": date, "latest": latest.isoformat() if latest else None}

@router.get("/api/qc/cap/filters")
def api_qc_cap_filters(request: Request, don_vi: Optional[str] = Query(None)):
    """Return filter options for QC CAP (don_vi, bo_phan, station)."""
    don_vi, _user = core.resolve_qc_don_vi_scope(request, don_vi)
    with core.get_db_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            use_jsonb_bo_phan = core._detect_bo_phan_jsonb()

            # don_vi options
            don_vi_filter_params: List[Any] = []
            don_vi_filter_sql = ""
            if don_vi:
                don_vi_filter_sql = "AND don_vi = %s"
                don_vi_filter_params.append(don_vi)
            cur.execute(
                f"""
                SELECT DISTINCT don_vi
                FROM public.prod_plan
                WHERE don_vi IS NOT NULL AND don_vi <> ''
                  {don_vi_filter_sql}
                ORDER BY don_vi
                """,
                tuple(don_vi_filter_params),
            )
            don_vi_options = [r["don_vi"] for r in cur.fetchall()]

            # station options
            station_params: List[Any] = []
            station_scope_sql = ""
            if don_vi:
                station_scope_sql = "JOIN public.prod_plan p ON p.id = o.plan_id AND p.don_vi = %s"
                station_params.append(don_vi)
            cur.execute(
                f"""
                SELECT DISTINCT o.station
                FROM public.qc_output_sp_log o
                {station_scope_sql}
                WHERE o.station IS NOT NULL AND o.station <> ''
                ORDER BY o.station
                """,
                tuple(station_params),
            )
            station_options = [r["station"] for r in cur.fetchall()]

            # bo_phan options (child of don_vi if provided)
            if use_jsonb_bo_phan:
                if don_vi:
                    cur.execute("""
                        SELECT DISTINCT value AS bo_phan
                        FROM public.prod_plan p,
                             jsonb_array_elements_text(COALESCE(p.bo_phan, '[]'::jsonb)) AS t(value)
                        WHERE p.don_vi = %s AND value <> ''
                        ORDER BY value
                    """, (don_vi,))
                else:
                    cur.execute("""
                        SELECT DISTINCT value AS bo_phan
                        FROM public.prod_plan p,
                             jsonb_array_elements_text(COALESCE(p.bo_phan, '[]'::jsonb)) AS t(value)
                        WHERE value <> ''
                        ORDER BY value
                    """)
            else:
                if don_vi:
                    cur.execute("""
                        SELECT DISTINCT bo_phan
                        FROM public.prod_plan
                        WHERE don_vi = %s AND bo_phan IS NOT NULL AND bo_phan <> ''
                        ORDER BY bo_phan
                    """, (don_vi,))
                else:
                    cur.execute("""
                        SELECT DISTINCT bo_phan
                        FROM public.prod_plan
                        WHERE bo_phan IS NOT NULL AND bo_phan <> ''
                        ORDER BY bo_phan
                    """)

            bo_phan_options = [r["bo_phan"] for r in cur.fetchall()]

    return {
        "don_vi": don_vi_options,
        "bo_phan": bo_phan_options,
        "station": station_options,
    }


@router.post("/api/qc/cap/backfill", dependencies=[Depends(core.require_qa_admin_api_user)])
def backfill_qc_cap(
    request: Request,
    date: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
):
    """Backfill qc_error_dps from existing CAP data."""
    _ = api_qc_cap(request=request, date=date, date_from=date_from, date_to=date_to)
    return {"status": "ok", "date_from": date_from or date, "date_to": date_to or date}
