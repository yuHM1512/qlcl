"""Pull the atomic plan/output snapshot published by the b_line application."""
import logging
import os
import re
import threading
from contextlib import closing

import psycopg2
from psycopg2.extras import Json, RealDictCursor
from flat_output import DDL, validate

UNIT = 'XNDT'
SOURCE = 'flat_line_sheet'  # Shared identity with b_line's direct publisher.
_started = False
_lock = threading.Lock()


def normalize_teams(raw):
    """Map b_line's XNDT line codes to QLCL team labels, preserving unknowns."""
    values = raw if isinstance(raw, list) else [raw]
    result = []
    for value in values:
        for part in re.split(r'[;,+]', str(value or '')):
            part = part.strip()
            match = re.fullmatch(r'(?:UDT\s*-\s*L|Tổ\s*|To\s*)?0*(\d+)', part, re.I)
            team = f'Tổ {int(match.group(1))}' if match else part
            if team and team not in result:
                result.append(team)
    return result


def source_connection(target_dsn):
    # PostgreSQL databases need separate connections even on the same server.
    dsn = os.getenv('B_LINE_DATABASE_URL')
    if dsn:
        return psycopg2.connect(dsn, connect_timeout=10)
    return psycopg2.connect(target_dsn, dbname='b_line', connect_timeout=10)


def sync(connect, target_dsn):
    with closing(connect()) as conn, conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SET LOCAL lock_timeout='10s'")
            cur.execute("SET LOCAL statement_timeout='60s'")
            # Serialize with the source app's publisher BEFORE reading its snapshot.
            cur.execute('SELECT pg_advisory_xact_lock(hashtext(%s))', ('flat-output:'+UNIT,))
            with closing(source_connection(target_dsn)) as source, source:
                source.set_session(readonly=True)
                with source.cursor(cursor_factory=RealDictCursor) as src:
                    src.execute("SET LOCAL statement_timeout='15s'")
                    src.execute('''SELECT s.payload AS snapshot, o.payload AS outputs, s.synced_at
                        FROM public.qlcl_outbox o JOIN public.source_snapshot s
                        ON s.id=o.snapshot_id AND s.unit=o.unit WHERE o.unit=%s''', (UNIT,))
                    row = src.fetchone()
            if not row:
                raise ValueError('b_line chưa có dữ liệu XNDT. Hãy đồng bộ dữ liệu trong app Chuyền bệt trước.')
            snapshot = row['snapshot']
            unit, outputs = validate(row['outputs'])
            if unit != UNIT or not isinstance(snapshot.get('plans'), list):
                raise ValueError('Snapshot b_line không hợp lệ cho XNDT')
            plans = snapshot['plans']
            ids = [UNIT+':'+p['demand'] for p in plans]
            if len(ids) != len(set(ids)) or any(not p['demand'].strip() for p in plans):
                raise ValueError('Snapshot có nhu cầu rỗng hoặc trùng')
            if any(o['source_record_id'] not in ids for o in outputs):
                raise ValueError('Sản lượng không thuộc nhu cầu trong cùng snapshot')
            warnings = list(snapshot.get('warnings') or [])
            cur.execute('SELECT ten_loai FROM public.dm_loai_hang')
            known = {r['ten_loai'] for r in cur.fetchall()}
            inserted = updated = skipped = deactivated = 0
            for p, identity in zip(plans, ids):
                if p.get('product_type') not in known:
                    warnings.append(f"{p['demand']}: loại hàng chưa có trong QLCL: {p.get('product_type')}")
                    skipped += 1
                    continue
                cur.execute('''INSERT INTO public.prod_plan
                    (ke_hoach,don_vi,bo_phan,khach_hang,ma_hang,loai_hang,ngay_rc,san_luong,
                     mau,size,po_info,source_system,source_record_id,source_status,is_active,last_synced_at)
                    VALUES(%s,%s,%s,%s,%s,%s,%s,%s,'','','[]'::jsonb,%s,%s,'active',true,now())
                    ON CONFLICT(source_system,source_record_id)
                      WHERE source_system IS NOT NULL AND source_record_id IS NOT NULL
                    DO UPDATE SET ke_hoach=excluded.ke_hoach,bo_phan=excluded.bo_phan,
                        khach_hang=excluded.khach_hang,ma_hang=excluded.ma_hang,
                        loai_hang=excluded.loai_hang,ngay_rc=excluded.ngay_rc,san_luong=excluded.san_luong,
                        source_status='active',is_active=true,last_synced_at=now(),updated_at=now()
                    RETURNING (xmax=0) AS inserted''',
                    (p['demand'],UNIT,Json(normalize_teams(p.get('teams') or [p['team']])),p['customer'],p['style'],
                     p['product_type'],p['first'],p['quantity'],SOURCE,identity))
                if cur.fetchone()['inserted']:
                    inserted += 1
                else:
                    updated += 1
            if not warnings:
                cur.execute('''UPDATE public.prod_plan SET is_active=false,source_status='inactive',
                    last_synced_at=now(),updated_at=now() WHERE source_system=%s AND don_vi=%s
                    AND NOT(source_record_id=ANY(%s)) AND is_active=true''', (SOURCE,UNIT,ids))
                deactivated = cur.rowcount
            cur.execute(DDL)
            cur.execute('DELETE FROM public.qc_flat_output WHERE don_vi=%s', (UNIT,))
            for output in outputs:
                cur.execute('''INSERT INTO public.qc_flat_output
                    (don_vi,source_record_id,report_date,qty,slots) VALUES(%s,%s,%s,%s,%s)''',
                    (UNIT,output['source_record_id'],output['date'],output['qty'],Json(output['slots'])))
    return dict(status='partial' if warnings else 'ok', don_vi=UNIT, inserted=inserted,
                updated=updated, skipped=skipped, deactivated=deactivated,
                outputs=len(outputs), warnings=warnings[:20], source_synced_at=row['synced_at'].isoformat())


def start_auto_sync(connect, target_dsn):
    global _started
    if os.getenv('B_LINE_AUTO_SYNC_ENABLED', 'false').lower() not in ('true', '1', 'yes'):
        return
    interval = max(1, int(os.getenv('B_LINE_AUTO_SYNC_INTERVAL_MINUTES', '2')))
    def run():
        while True:
            try:
                result = sync(connect, target_dsn)
                logging.getLogger(__name__).info('XNDT sync: %s', result)
            except Exception:
                logging.getLogger(__name__).exception('XNDT sync failed')
            threading.Event().wait(interval * 60)
    with _lock:
        if not _started:
            threading.Thread(target=run, name='xndt-auto-sync', daemon=True).start()
            _started = True
