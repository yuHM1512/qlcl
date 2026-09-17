"""Receive mother-demand production snapshots from factory dashboards."""
import json
import math
from datetime import date
from contextlib import asynccontextmanager
from fastapi import APIRouter, HTTPException, Request, Query
import psycopg2.extras

DDL = """CREATE TABLE IF NOT EXISTS public.qc_flat_output (
    don_vi TEXT NOT NULL, source_record_id TEXT NOT NULL, report_date DATE NOT NULL,
    qty NUMERIC, slots JSONB NOT NULL, synced_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY(don_vi, source_record_id, report_date)
)"""


def validate(payload):
    unit = str(payload.get('don_vi') or '').strip()
    if unit not in ('XN1-V1', 'XN2', 'XN3', 'XNDT'):
        raise HTTPException(422, 'Đơn vị không hợp lệ')
    rows = payload.get('outputs')
    if not isinstance(rows, list):
        raise HTTPException(422, 'outputs phải là danh sách')
    seen = set()
    for r in rows:
        try:
            identity = (r['source_record_id'], date.fromisoformat(r['date']))
            if not identity[0].startswith(unit+':') or identity in seen:
                raise ValueError()
            seen.add(identity)
            slots = r['slots']
            if len(slots) != 5 or [s['slot'] for s in slots] != [1,2,3,4,5]:
                raise ValueError()
            values = [r['qty']] + [s[k] for s in slots for k in ('qty','cumulative')]
            if any(v is not None and (isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v)) for v in values):
                raise ValueError()
            known = [s['cumulative'] for s in slots if s['cumulative'] is not None]
            if r['qty'] != (known[-1] if known else None):
                raise ValueError()
        except (KeyError,TypeError,ValueError,AttributeError):
            raise HTTPException(422, 'Dữ liệu nhu cầu/ngày/5 mốc không hợp lệ')
    return unit, rows


def get_output(cur, plan, day):
    cur.execute('SELECT qty,slots,synced_at FROM public.qc_flat_output WHERE don_vi=%s AND source_record_id=%s AND report_date=%s',
                (plan['don_vi'],plan['source_record_id'],day))
    row = cur.fetchone()
    cur.execute("SELECT COUNT(*) AS records, COALESCE(SUM(defect_count),0) AS defects FROM public.qc_error_log_sp WHERE plan_id=%s AND date=%s AND BTRIM(station)='QC kiểm thành phẩm'", (plan['id'],day))
    summary = cur.fetchone()
    defects = int(summary['defects'])
    qty = float(row['qty']) if row and row['qty'] is not None else None
    inspected = qty + defects if qty is not None else None
    return dict(source='flat_line_sheet',qty=qty,available=qty is not None,defects=defects,records=summary['records'],
        rate=round(defects/inspected*100,1) if summary['records'] and inspected and inspected>0 else None,
        slots=row['slots'] if row else [],synced_at=row['synced_at'].isoformat() if row else None)


def register(app, connect, api_key):
    @asynccontextmanager
    async def lifespan(app):
        with connect() as conn:
            with conn.cursor() as cur:
                cur.execute(DDL)
            conn.commit()
        yield

    router = APIRouter(lifespan=lifespan)

    @router.post('/api/qc/flat-output/push')
    def push(request: Request, payload: dict):
        if not api_key or request.headers.get('X-API-Key') != api_key:
            raise HTTPException(403,'API key không hợp lệ')
        unit, rows = validate(payload)
        # One complete factory snapshot, atomically replaced; includes corrections/deletions.
        with connect() as conn:
            with conn.cursor() as cur:
                cur.execute('SELECT pg_advisory_xact_lock(hashtext(%s))',('flat-output:'+unit,))
                cur.execute('DELETE FROM public.qc_flat_output WHERE don_vi=%s',(unit,))
                for r in rows:
                    cur.execute('INSERT INTO public.qc_flat_output(don_vi,source_record_id,report_date,qty,slots) VALUES(%s,%s,%s,%s,%s::jsonb)',
                        (unit,r['source_record_id'],r['date'],r['qty'],json.dumps(r['slots'])))
                cur.execute("SELECT source_record_id FROM public.prod_plan WHERE source_system='flat_line_sheet' AND don_vi=%s",(unit,))
                known={r[0] for r in cur.fetchall()}
            conn.commit()
        missing=sorted({r['source_record_id'] for r in rows}-known)
        return dict(status='ok',upserted=len(rows),missing_plans=missing)

    @router.get('/api/tv3/flat-qc-data')
    def flat_quality(request: Request, demand: str, don_vi: str,
                     day: date = Query(..., alias='date')):
        if not api_key or request.headers.get('X-API-Key') != api_key:
            raise HTTPException(403, 'API key không hợp lệ')
        qlcl_unit = 'XN1-V1' if don_vi == 'XN1' else don_vi
        if qlcl_unit not in ('XN1-V1', 'XN2', 'XN3', 'XNDT'):
            raise HTTPException(422, 'Đơn vị không hợp lệ')
        with connect() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute('SET LOCAL statement_timeout=4000')
                cur.execute("SELECT id FROM public.prod_plan WHERE source_system='flat_line_sheet' AND source_record_id=%s AND don_vi=%s", (f"{qlcl_unit}:{demand}", qlcl_unit))
                plan = cur.fetchone()
                if not plan:
                    return {"status": "empty", "message": "Chưa có kế hoạch mẹ trong QLCL"}
                cur.execute("SELECT COUNT(*) AS records, COALESCE(SUM(defect_count),0) AS defects FROM public.qc_error_log_sp WHERE plan_id=%s AND date=%s AND BTRIM(station)='QC kiểm thành phẩm'", (plan['id'], day))
                summary = dict(cur.fetchone())
                cur.execute("""SELECT COALESCE(bp.ten_bo_phan,'Chưa phân loại') AS department,
                    COALESCE(ct.ten_chi_tiet,'') AS detail, COALESCE(ml.ten_ma,'Chưa phân loại') AS defect, COUNT(*) AS quantity
                    FROM public.qc_defect d JOIN public.qc_error_log_sp sp ON sp.id=d.error_log_sp_id
                    LEFT JOIN public.dm_bo_phan bp ON bp.id=d.bo_phan_id
                    LEFT JOIN public.dm_chi_tiet ct ON ct.id=d.chi_tiet_id
                    LEFT JOIN public.dm_ma_loi ml ON ml.id=d.ma_loi_id
                    WHERE sp.plan_id=%s AND sp.date=%s AND BTRIM(sp.station)='QC kiểm thành phẩm' GROUP BY bp.ten_bo_phan,ct.ten_chi_tiet,ml.ten_ma ORDER BY COUNT(*) DESC""", (plan['id'], day))
                details = [dict(r) for r in cur.fetchall()]
                cur.execute("""WITH garments AS (
                    SELECT d.error_log_sp_id, d.sp_index, MIN(d.created_at) AS created_at
                    FROM public.qc_defect d JOIN public.qc_error_log_sp sp ON sp.id=d.error_log_sp_id
                    WHERE sp.plan_id=%s AND sp.date=%s AND BTRIM(sp.station)='QC kiểm thành phẩm'
                    GROUP BY d.error_log_sp_id,d.sp_index
                ) SELECT CASE
                    WHEN timezone('Asia/Ho_Chi_Minh',created_at)::time < '09:30' THEN 1
                    WHEN timezone('Asia/Ho_Chi_Minh',created_at)::time < '11:30' THEN 2
                    WHEN timezone('Asia/Ho_Chi_Minh',created_at)::time < '14:30' THEN 3
                    WHEN timezone('Asia/Ho_Chi_Minh',created_at)::time < '16:30' THEN 4 ELSE 5 END AS slot,
                    COUNT(*) AS defects FROM garments GROUP BY slot""", (plan['id'], day))
                slots = [dict(r) for r in cur.fetchall()]
                cur.execute("SELECT time,bo_phan,chi_tiet,ma_loi FROM public.qc_defect_multi WHERE plan_id=%s AND date=%s AND BTRIM(station)='QC kiểm thành phẩm' ORDER BY time", (plan['id'], day))
                alerts = [dict(time=str(r['time'])[:5], text=' · '.join(str(r[k]) for k in ('bo_phan','chi_tiet','ma_loi') if r[k])) for r in cur.fetchall()]
                return dict(status="ok" if summary['records'] else "empty", **summary,
                    plan_id=plan['id'], details=details, slots=slots, alerts=alerts)

    app.include_router(router)
