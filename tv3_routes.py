"""Tích hợp TV-3 (chuyền treo) — endpoint dữ liệu QC.

Tách từ main.py. Hàm/biến dùng chung (DB, đăng nhập, phân quyền, template, cấu hình...) vẫn ở main.py
và được gọi qua `core.<tên>` lúc chạy, nên test patch `main.<tên>` vẫn có hiệu lực.
"""
import psycopg2
import psycopg2.extras
import psycopg2.pool
from fastapi import APIRouter, HTTPException, Query, Request

from app_core import core

router = APIRouter()


# ============================================================
# TV-3 Integration — QC data endpoint cho chuyền treo TV
# ============================================================

_TV3_SLOT_BUCKET_MAP = [
    # (bucket_label từ SQL, slot_number, label hiển thị TV)
    ("7H30 - 9H30",   1, "7:30–9:30"),
    ("9H30 - 11H30",  2, "9:30–11:30"),
    ("12H30 - 14H30", 3, "12:30–14:30"),
    ("14H30 - 16H30", 4, "14:30–16:30"),
    ("Sau 16H30",      5, "Sau 16:30"),
]

def _tv3_bucket_sql(time_expr: str) -> str:
    """CASE expression phân loại time → bucket label."""
    return f"""
        CASE
            WHEN {time_expr} < '09:30:00' THEN '7H30 - 9H30'
            WHEN {time_expr} < '11:30:00' THEN '9H30 - 11H30'
            WHEN {time_expr} < '14:30:00' THEN '12H30 - 14H30'
            WHEN {time_expr} < '16:30:00' THEN '14H30 - 16H30'
            ELSE 'Sau 16H30'
        END
    """


@router.get("/api/tv3/qc-data")
def api_tv3_qc_data(
    request: Request,
    mono: str = Query(..., description="MONo từ chuyền treo (prod_plan.mono)"),
    date: str = Query(..., description="Ngày YYYY-MM-DD"),
):
    """Trả về toàn bộ QC defect data cho TV-3 chuyền treo.

    Lọc theo MONo (qua prod_plan.mono) + date.
    Endpoint này được gọi từ hanging line app backend.
    """
    # Backend integrations use the shared key; browser requests follow account scope.
    scoped_factory = None
    if not (core._PUSH_API_KEY and request.headers.get("X-API-Key") == core._PUSH_API_KEY):
        scoped_factory, _ = core.resolve_qc_don_vi_scope(request, None)
    try:
        with core.get_db_connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:

                # ── 1. Resolve plan_id từ mono ──────────────────────────
                cur.execute(
                    "SELECT id FROM public.prod_plan WHERE mono = %s AND (%s IS NULL OR don_vi = %s) LIMIT 1",
                    (mono, scoped_factory, scoped_factory),
                )
                plan_row = cur.fetchone()
                if not plan_row:
                    return {"found": False, "mono": mono}
                plan_id = int(plan_row["id"])

                # Timezone expression — dùng Asia/Ho_Chi_Minh
                time_expr = "timezone('Asia/Ho_Chi_Minh', sp.created_at)::time"
                bucket_sql = _tv3_bucket_sql(time_expr)

                # ── 2. Tổng kiểm + tổng lỗi (từ cached columns) ────────
                cur.execute(
                    """
                    SELECT
                        COALESCE(SUM(output), 0)       AS total_kiem,
                        COALESCE(SUM(defect_count), 0) AS total_loi
                    FROM public.qc_error_log_sp
                    WHERE plan_id = %s AND date = %s
                    """,
                    (plan_id, date),
                )
                agg = cur.fetchone() or {}
                total_kiem = int(agg.get("total_kiem") or 0)
                total_loi  = int(agg.get("total_loi")  or 0)
                ty_le_loi  = round(total_loi / total_kiem * 100, 1) if total_kiem > 0 else 0.0

                # ── 3. Tổng kiểm theo slot (dùng created_at của sp) ─────
                cur.execute(
                    f"""
                    SELECT {bucket_sql} AS bucket,
                           COALESCE(SUM(sp.output), 0)       AS kiem,
                           COALESCE(SUM(sp.defect_count), 0) AS loi
                    FROM public.qc_error_log_sp sp
                    WHERE sp.plan_id = %s AND sp.date = %s
                    GROUP BY bucket
                    """,
                    (plan_id, date),
                )
                bucket_rows = {r["bucket"]: r for r in cur.fetchall()}
                slots = []
                for bkey, slot_num, slot_label in _TV3_SLOT_BUCKET_MAP:
                    row  = bucket_rows.get(bkey, {})
                    kiem = int(row.get("kiem", 0) or 0)
                    loi  = int(row.get("loi", 0)  or 0)
                    pct  = round(loi / kiem * 100, 1) if kiem > 0 else 0.0
                    slots.append({
                        "slot":  slot_num,
                        "label": slot_label,
                        "kiem":  kiem,
                        "loi":   loi,
                        "pct":   pct,
                    })

                # ── 4. Phân bổ lỗi theo bộ phận (donut) ────────────────
                cur.execute(
                    """
                    SELECT
                        COALESCE(NULLIF(bp.ten_bo_phan, ''), '(Không rõ)') AS bp_name,
                        COUNT(*) AS n
                    FROM public.qc_defect d
                    JOIN public.qc_error_log_sp sp ON sp.id = d.error_log_sp_id
                    LEFT JOIN public.dm_bo_phan bp ON bp.id = d.bo_phan_id
                    WHERE sp.plan_id = %s AND sp.date = %s
                    GROUP BY bp_name
                    ORDER BY n DESC
                    """,
                    (plan_id, date),
                )
                bo_phan = [
                    {"name": r["bp_name"], "count": int(r["n"])}
                    for r in cur.fetchall()
                ]

                # ── 5. Top 3 mã lỗi (column chart) ─────────────────────
                cur.execute(
                    """
                    SELECT
                        COALESCE(NULLIF(ml.ten_ma, ''), d.ma_loi_id::text, '(Không rõ)') AS ma_loi,
                        COUNT(*) AS n
                    FROM public.qc_defect d
                    JOIN public.qc_error_log_sp sp ON sp.id = d.error_log_sp_id
                    LEFT JOIN public.dm_ma_loi ml ON ml.id = d.ma_loi_id
                    WHERE sp.plan_id = %s AND sp.date = %s
                    GROUP BY ma_loi
                    ORDER BY n DESC
                    LIMIT 3
                    """,
                    (plan_id, date),
                )
                top3 = [
                    {"ma_loi": r["ma_loi"], "n": int(r["n"])}
                    for r in cur.fetchall()
                ]

                # ── 6. Combo table (bp + ct + ma_loi + count) ───────────
                cur.execute(
                    """
                    SELECT
                        COALESCE(NULLIF(bp.ten_bo_phan, ''), '(Không rõ)') AS bp,
                        COALESCE(NULLIF(ct.ten_chi_tiet, ''), '(Không rõ)') AS ct,
                        COALESCE(NULLIF(ml.ten_ma, ''), d.ma_loi_id::text, '(Không rõ)') AS ma_loi,
                        COUNT(*) AS n
                    FROM public.qc_defect d
                    JOIN public.qc_error_log_sp sp ON sp.id = d.error_log_sp_id
                    LEFT JOIN public.dm_bo_phan  bp ON bp.id = d.bo_phan_id
                    LEFT JOIN public.dm_chi_tiet ct ON ct.id = d.chi_tiet_id
                    LEFT JOIN public.dm_ma_loi   ml ON ml.id = d.ma_loi_id
                    WHERE sp.plan_id = %s AND sp.date = %s
                    GROUP BY bp, ct, ma_loi
                    ORDER BY n DESC
                    """,
                    (plan_id, date),
                )
                combo = [
                    {"bp": r["bp"], "ct": r["ct"], "ma_loi": r["ma_loi"], "n": int(r["n"])}
                    for r in cur.fetchall()
                ]

                # ── 7. Cảnh báo hàng loạt (qc_defect_multi) ────────────
                cur.execute(
                    """
                    SELECT time, bo_phan, chi_tiet, ma_loi
                    FROM public.qc_defect_multi
                    WHERE plan_id = %s AND date = %s
                    ORDER BY time
                    """,
                    (plan_id, date),
                )
                canh_bao = []
                for r in cur.fetchall():
                    t = r.get("time")
                    time_str = t.strftime("%H:%M") if hasattr(t, "strftime") else str(t)[:5]
                    parts = [p for p in [r.get("bo_phan"), r.get("chi_tiet"), r.get("ma_loi")] if p]
                    canh_bao.append({"time": time_str, "text": " · ".join(parts)})

                return {
                    "found":      True,
                    "plan_id":    plan_id,
                    "total_kiem": total_kiem,
                    "total_loi":  total_loi,
                    "ty_le_loi":  ty_le_loi,
                    "slots":      slots,
                    "bo_phan":    bo_phan,
                    "top3":       top3,
                    "combo":      combo,
                    "canh_bao":   canh_bao,
                }

    except Exception as e:
        core.logger.error("api_tv3_qc_data error: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Lỗi truy vấn QC data: {str(e)}")
