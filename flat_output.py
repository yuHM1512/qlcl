"""Receive mother-demand production snapshots from factory dashboards."""
import json
import math
from datetime import date
from contextlib import asynccontextmanager
from fastapi import APIRouter, HTTPException, Request

DDL = """CREATE TABLE IF NOT EXISTS public.qc_flat_output (
    don_vi TEXT NOT NULL, source_record_id TEXT NOT NULL, report_date DATE NOT NULL,
    qty NUMERIC, slots JSONB NOT NULL, synced_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY(don_vi, source_record_id, report_date)
)"""


def validate(payload):
    unit = str(payload.get('don_vi') or '').strip()
    if unit not in ('XN1-V1', 'XN2', 'XN3'):
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
    cur.execute("SELECT COUNT(*) AS records, COALESCE(SUM(defect_count),0) AS defects FROM public.qc_error_log_sp WHERE plan_id=%s AND date=%s AND BTRIM(station)='Trạm cuối chuyền'", (plan['id'],day))
    summary = cur.fetchone()
    defects = int(summary['defects'])
    qty = float(row['qty']) if row and row['qty'] is not None else None
    return dict(source='flat_line_sheet',qty=qty,available=qty is not None,defects=defects,records=summary['records'],
        rate=round(defects/qty*100,1) if summary['records'] and qty and qty>0 else None,
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

    app.include_router(router)
