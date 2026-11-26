"""Kế hoạch chuyền treo: chỉ nhận qua PUSH (push-from-hl) + PULL XNV2; API pull cục bộ đã bỏ.
Mọi dữ liệu test được rollback.

Run: .venv/Scripts/python.exe -m unittest test_hanging_line_plan_sync -v
"""
import datetime
import logging
import unittest
from pathlib import Path
from unittest.mock import patch

import psycopg2
import psycopg2.extras
from fastapi.testclient import TestClient

import main
import prod_plan_sync
from test_qc_roles import TransactionConnection

logging.getLogger('httpx').setLevel(logging.WARNING)

KEY = 'hl-plan-test-key'
GUID = '11111111-2222-3333-4444-555555555555'
MONO = 'HL-PLAN-TEST #001'


class FakeSqlServerCursor:
    """Giả lập pyodbc cursor: query đầu trả tPlanMaster, query sau trả tổng PO."""

    def __init__(self, plans, po_totals):
        self.plans, self.po_totals = plans, po_totals
        self.description = None
        self._rows = []

    def execute(self, sql):
        if 'tPlanPO' in sql:
            self.description = [('PlanMaster_guid',), ('TotalQty',)]
            self._rows = self.po_totals
        else:
            cols = list(self.plans[0].keys()) if self.plans else ['PlanMaster_guid']
            self.description = [(c,) for c in cols]
            self._rows = [tuple(p[c] for c in cols) for p in self.plans]

    def fetchall(self):
        return self._rows


class FakeSqlServerConnection:
    def __init__(self, plans, po_totals=()):
        self._cursor = FakeSqlServerCursor(plans, list(po_totals))
        self.closed = False

    def cursor(self):
        return self._cursor

    def close(self):
        self.closed = True


class HangingLinePlanSyncTest(unittest.TestCase):
    def setUp(self):
        self.connection = psycopg2.connect(main.DATABASE_URL)
        self.addCleanup(self.connection.close)
        self.addCleanup(self.connection.rollback)
        db_patch = patch.object(main, 'get_db_connection', return_value=TransactionConnection(self.connection))
        db_patch.start()
        self.addCleanup(db_patch.stop)
        key_patch = patch.object(main, '_PUSH_API_KEY', KEY)
        key_patch.start()
        self.addCleanup(key_patch.stop)
        self.client = TestClient(main.app)
        self.addCleanup(self.client.close)
        with self.connection.cursor() as cur:
            cur.execute("SELECT ma_nv FROM quality_employees WHERE qc_role = 'QA_ADMIN' ORDER BY ma_nv LIMIT 1")
            self.qa = cur.fetchone()[0]
            cur.execute("SELECT ma_nv FROM quality_employees WHERE qc_role = 'QC' AND don_vi = 'XN2' LIMIT 1")
            self.qc_xn2 = cur.fetchone()[0]
            cur.execute("SELECT ten_loai FROM dm_loai_hang ORDER BY ten_loai LIMIT 1")
            self.loai_hang = cur.fetchone()[0]

    def login(self, employee):
        self.client.cookies.set('ma_nv', main.encode_ma_nv_cookie(employee))

    def plan_row(self, mono=MONO):
        with self.connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT * FROM prod_plan WHERE mono = %s", (mono,))
            return cur.fetchall()

    def push(self, don_vi='XN2', **overrides):
        plan = {'guid': GUID, 'mono': MONO, 'ke_hoach': f'HL-{MONO}', 'line_no': 5,
                'style_no': 'STYLE-A', 'customer': 'CUST', 'loai_hang': self.loai_hang,
                'first_hang': '2026-11-20', 'san_luong': 1200}
        plan.update(overrides)
        return self.client.post('/api/prod-plan/push-from-hl', headers={'X-API-Key': KEY},
                                json={'don_vi': don_vi, 'plans': [plan]})

    # --- API pull cục bộ đã bỏ ---
    def test_local_pull_endpoint_is_removed(self):
        paths = {r.path for r in main.app.routes}
        self.assertNotIn('/api/prod-plan/sync-hanging-line', paths)
        self.login(self.qa)
        response = self.client.post('/api/prod-plan/sync-hanging-line')
        self.assertIn(response.status_code, (404, 405), response.text)
        for name in ('HANGING_LINE_DON_VI', 'HANGING_LINE_SQL_SERVER', 'get_hanging_line_connection'):
            self.assertFalse(hasattr(main, name), name)

    def test_other_sync_endpoints_still_registered(self):
        paths = {r.path for r in main.app.routes}
        for path in ('/api/prod-plan/push-from-hl', '/api/qc/hanging-output/push',
                     '/api/qc/employees/push-from-hl', '/api/qc/flat-output/push',
                     '/api/prod-plan/sync-qtcn', '/api/prod-plan/sync-xndt',
                     '/api/prod-plan/sync-flat-line'):
            self.assertIn(path, paths)

    def test_frontend_no_longer_calls_removed_endpoint(self):
        sources = [Path('templates/qc_input_sp.html'), Path('templates/qc.html')]
        sources += sorted(Path('assets/qc_input').glob('*.js'))
        for source in sources:
            text = source.read_text(encoding='utf-8')
            self.assertNotIn('sync-hanging-line', text, source)
            self.assertNotIn('syncHangingLinePlans', text, source)

    # --- PUSH từ app chuyền treo (luồng production) ---
    def test_push_inserts_then_updates_same_plan(self):
        first = self.push()
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual((first.json()['inserted'], first.json()['updated']), (1, 0))
        again = self.push(san_luong=1500, line_no=6)
        self.assertEqual((again.json()['inserted'], again.json()['updated']), (0, 1))
        rows = self.plan_row()
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row['don_vi'], 'XN2')
        self.assertEqual(row['source_system'], 'hanging_line')
        self.assertEqual(row['source_record_id'], GUID)
        self.assertEqual(row['bo_phan'], ['Tổ 6'])
        self.assertEqual(row['san_luong'], 1500)
        self.assertEqual(row['ma_hang'], 'STYLE-A')
        self.assertEqual(str(row['ngay_rc']), '2026-11-20')

    def test_push_keeps_manual_finish(self):
        self.push()
        with self.connection.cursor() as cur:
            cur.execute("UPDATE prod_plan SET is_finished = TRUE WHERE mono = %s", (MONO,))
        self.push(san_luong=999)
        row = self.plan_row()[0]
        self.assertTrue(row['is_finished'])
        self.assertTrue(row['is_active'])
        self.assertEqual(row['san_luong'], 999)

    def test_pushed_plan_is_visible_to_qc_of_same_factory_only(self):
        self.push()
        plan_id = self.plan_row()[0]['id']
        self.login(self.qc_xn2)
        rows = self.client.get('/api/prod-plan', params={'only_active': 'true'}).json()['rows']
        self.assertIn(plan_id, [r['id'] for r in rows])
        with self.connection.cursor() as cur:
            cur.execute("UPDATE prod_plan SET don_vi = 'XN3' WHERE id = %s", (plan_id,))
        rows = self.client.get('/api/prod-plan', params={'only_active': 'true'}).json()['rows']
        self.assertNotIn(plan_id, [r['id'] for r in rows])

    def test_push_rejects_wrong_key_and_missing_unit(self):
        response = self.client.post('/api/prod-plan/push-from-hl', headers={'X-API-Key': 'wrong'},
                                    json={'don_vi': 'XN2', 'plans': []})
        self.assertEqual(response.status_code, 403)
        response = self.client.post('/api/prod-plan/push-from-hl', headers={'X-API-Key': KEY},
                                    json={'plans': []})
        self.assertEqual(response.status_code, 422)

    def test_push_skips_plan_without_mono(self):
        response = self.push(mono='')
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual((response.json()['inserted'], response.json()['skipped']), (0, 1))

    # --- PULL XNV2 vẫn dùng sync_hanging_line_prod_plan ---
    def xnv2_source(self, line_no=3):
        return [{
            'PlanMaster_guid': GUID, 'MONo': MONO, 'SoDonHang': 'SO1', 'StyleNo': 'STYLE-X',
            'NhuCauMe': 'NC1', 'LineNo': line_no, 'FirstHangDate': datetime.date(2026, 11, 21),
            'SLKH': 800, 'Customer': 'CUST-X', 'LoaiHang': self.loai_hang, 'DMKT': None, 'LDBienChe': None,
        }]

    def test_xnv2_pull_upserts_with_given_unit(self):
        conn = FakeSqlServerConnection(self.xnv2_source(), [(GUID, 950)])
        result = prod_plan_sync.sync_hanging_line_prod_plan(conn_override=conn, don_vi_override='XNV2')
        self.assertEqual((result['status'], result['inserted']), ('ok', 1))
        self.assertTrue(conn.closed)
        row = self.plan_row()[0]
        self.assertEqual((row['don_vi'], row['bo_phan'], row['san_luong']), ('XNV2', ['Tổ 3'], 950))
        conn = FakeSqlServerConnection(self.xnv2_source(line_no=4))
        result = prod_plan_sync.sync_hanging_line_prod_plan(conn, 'XNV2')
        self.assertEqual((result['inserted'], result['updated']), (0, 1))
        row = self.plan_row()[0]
        self.assertEqual((row['bo_phan'], row['san_luong']), (['Tổ 4'], 800))

    def test_xnv2_pull_requires_connection_and_unit(self):
        with self.assertRaises(TypeError):
            prod_plan_sync.sync_hanging_line_prod_plan()

    def test_xnv2_auto_sync_passes_connection_and_unit(self):
        conn = object()
        calls = []

        def fake_sync(conn_override, don_vi_override):
            calls.append((conn_override, don_vi_override))
            raise KeyboardInterrupt  # thoát vòng lặp vô hạn sau lần gọi đầu

        with patch.object(prod_plan_sync.time, 'sleep'), \
                patch.object(prod_plan_sync, 'get_xnv2_connection', return_value=conn), \
                patch.object(prod_plan_sync, 'sync_hanging_line_prod_plan', side_effect=fake_sync):
            with self.assertRaises(KeyboardInterrupt):
                prod_plan_sync.run_xnv2_auto_sync_loop()
        self.assertEqual(calls, [(conn, main.XNV2_DON_VI)])


if __name__ == '__main__':
    unittest.main()
