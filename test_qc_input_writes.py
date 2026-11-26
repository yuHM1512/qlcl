"""Integration checks for QC input write endpoints; all test data is rolled back.

Run: .venv/Scripts/python.exe -m unittest test_qc_input_writes -v
"""
import logging
import unittest
import uuid
from unittest.mock import patch

import psycopg2
from fastapi.testclient import TestClient

import main
from test_qc_roles import TransactionConnection

logging.getLogger('httpx').setLevel(logging.WARNING)

PLAN_ID = -925001
DAY = '2026-09-16'


class QCInputWritesTest(unittest.TestCase):
    def setUp(self):
        self.connection = psycopg2.connect(main.DATABASE_URL)
        self.addCleanup(self.connection.close)
        self.addCleanup(self.connection.rollback)
        db_patch = patch.object(main, 'get_db_connection', return_value=TransactionConnection(self.connection))
        db_patch.start()
        self.addCleanup(db_patch.stop)
        self.client = TestClient(main.app)
        self.addCleanup(self.client.close)
        with self.connection.cursor() as cur:
            cur.execute("SELECT ma_nv FROM quality_employees WHERE qc_role = 'QC' AND don_vi = 'XN2' LIMIT 1")
            self.qc = cur.fetchone()[0]
            cur.execute("""INSERT INTO prod_plan (id, ke_hoach, don_vi, bo_phan, is_active)
                           VALUES (%s, 'INPUT TEST XN2', 'XN2', '[]', TRUE)""", (PLAN_ID,))
            cur.execute("SELECT id FROM dm_bo_phan ORDER BY id LIMIT 1")
            self.bo_phan_id = cur.fetchone()[0]
            cur.execute("SELECT id FROM dm_chi_tiet ORDER BY id LIMIT 1")
            self.chi_tiet_id = cur.fetchone()[0]
            cur.execute("SELECT id, ma_loi_id FROM dm_mo_ta_loi WHERE ma_loi_id IS NOT NULL ORDER BY id LIMIT 1")
            self.mo_ta_loi_id, self.ma_loi_id = cur.fetchone()
        self.client.cookies.set('ma_nv', main.encode_ma_nv_cookie(self.qc))

    def product(self):
        return {'defects': [{
            'bo_phan_id': self.bo_phan_id, 'chi_tiet_id': self.chi_tiet_id,
            'ma_loi_id': self.ma_loi_id, 'mo_ta_loi_id': self.mo_ta_loi_id, 'muc_do': 'Nhẹ',
        }]}

    def error_body(self, n=1, pending=None, request_id=None):
        body = {'plan_id': PLAN_ID, 'date': DAY, 'station': 'TEST',
                'defect_products': [self.product() for _ in range(n)],
                'pending_failed_count': n if pending is None else pending, 'append_only': True}
        if request_id:
            body['client_request_id'] = request_id
        return body

    def scalar(self, sql, params=()):
        with self.connection.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchone()[0]

    def failed_rows(self):
        return self.scalar("SELECT COUNT(*) FROM qc_output_sp_log WHERE plan_id=%s AND status='Failed'", (PLAN_ID,))

    def test_retry_with_same_request_id_is_ignored(self):
        rid = uuid.uuid4().hex
        first = self.client.post('/api/qc/error-log-sp', json=self.error_body(2, request_id=rid))
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(first.json()['last_sp_index'], 2)
        again = self.client.post('/api/qc/error-log-sp', json=self.error_body(2, request_id=rid))
        self.assertEqual(again.status_code, 200, again.text)
        self.assertEqual(again.json(), first.json())
        self.assertEqual(self.failed_rows(), 2)
        self.assertEqual(self.scalar(
            "SELECT COUNT(*) FROM qc_defect d JOIN qc_error_log_sp s ON s.id=d.error_log_sp_id WHERE s.plan_id=%s",
            (PLAN_ID,)), 2)

    def test_retry_after_plan_closed_returns_original_result(self):
        rid = uuid.uuid4().hex
        first = self.client.post('/api/qc/error-log-sp', json=self.error_body(1, request_id=rid))
        self.assertEqual(first.status_code, 200, first.text)
        with self.connection.cursor() as cur:
            cur.execute('UPDATE prod_plan SET is_finished=TRUE WHERE id=%s', (PLAN_ID,))
        again = self.client.post('/api/qc/error-log-sp', json=self.error_body(1, request_id=rid))
        self.assertEqual(again.status_code, 200, again.text)
        self.assertEqual(again.json(), first.json())
        # A brand-new request on the closed plan is still rejected.
        self.assertEqual(self.client.post('/api/qc/error-log-sp', json=self.error_body(1)).status_code, 409)

    def test_sp_index_continues_and_single_log_row(self):
        self.assertEqual(self.client.post('/api/qc/error-log-sp', json=self.error_body(1)).json()['last_sp_index'], 1)
        self.assertEqual(self.client.post('/api/qc/error-log-sp', json=self.error_body(2)).json()['last_sp_index'], 3)
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM qc_error_log_sp WHERE plan_id=%s", (PLAN_ID,)), 1)

    def test_pending_failed_count_is_clamped_to_products(self):
        response = self.client.post('/api/qc/error-log-sp', json=self.error_body(1, pending=1000000))
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.failed_rows(), 1)

    def test_invalid_inputs_are_rejected(self):
        body = self.error_body(1)
        body['date'] = 'not-a-date'
        self.assertEqual(self.client.post('/api/qc/error-log-sp', json=body).status_code, 400)
        body = self.error_body(1)
        body['date'] = '2099-01-01'
        self.assertEqual(self.client.post('/api/qc/error-log-sp', json=body).status_code, 400)
        body = self.error_body(1)
        body['append_only'] = False
        self.assertEqual(self.client.post('/api/qc/error-log-sp', json=body).status_code, 400)
        body = self.error_body(1, request_id='bad id!')
        self.assertEqual(self.client.post('/api/qc/error-log-sp', json=body).status_code, 400)

    def test_minus_one_only_undoes_passed(self):
        self.client.post('/api/qc/error-log-sp', json=self.error_body(1))
        base = {'plan_id': PLAN_ID, 'date': DAY, 'station': 'TEST'}
        rid = uuid.uuid4().hex
        r1 = self.client.post('/api/qc/output-sp-log', json={**base, 'delta': 1, 'client_request_id': rid})
        r2 = self.client.post('/api/qc/output-sp-log', json={**base, 'delta': 1, 'client_request_id': rid})
        self.assertEqual(r1.json()['total'], 2)
        self.assertEqual(r2.json()['total'], 2)  # duplicate ignored
        self.assertEqual(self.client.post('/api/qc/output-sp-log', json={**base, 'delta': -1}).json()['total'], 1)
        # No Passed left: -1 must not delete the Failed row linked to a defect product.
        after = self.client.post('/api/qc/output-sp-log', json={**base, 'delta': -1}).json()
        self.assertEqual(after['total'], 1)
        self.assertEqual(after['failed_count'], 1)

    def test_rework_scoped_by_plan_and_patch_404(self):
        log_id = self.client.post('/api/qc/error-log-sp', json=self.error_body(1)).json()['id']
        # Another QC of the same factory saved first: still visible when filtering by plan.
        with self.connection.cursor() as cur:
            cur.execute("UPDATE qc_error_log_sp SET ma_nv='SOMEONE-ELSE' WHERE id=%s", (log_id,))
        rows = self.client.get(f'/api/qc/rework-2?date_str={DAY}&plan_id={PLAN_ID}&station=TEST').json()['rows']
        self.assertEqual([r['sp_index'] for r in rows], [1])
        self.assertEqual(self.client.get(f'/api/qc/rework-2?date_str={DAY}&plan_id={PLAN_ID}&station=OTHER').json()['rows'], [])
        ok = self.client.patch(f'/api/qc/rework-2/{log_id}/1', json={'rework_done': True})
        self.assertEqual(ok.status_code, 200, ok.text)
        self.assertEqual(self.client.patch(f'/api/qc/rework-2/{log_id}/99', json={'rework_done': True}).status_code, 404)

    def test_qc_login_lands_on_input_page(self):
        self.client.cookies.clear()
        for path in ('/login', '/qc-login'):
            res = self.client.post(path, data={'ma_nv': self.qc}, follow_redirects=False)
            self.assertEqual((res.status_code, res.headers['location']), (303, '/qc-input'), path)
        # An explicit next target still wins.
        res = self.client.post('/login', data={'ma_nv': self.qc, 'next_url': '/qc/cap'}, follow_redirects=False)
        self.assertEqual(res.headers['location'], '/qc/cap')
        self.client.cookies.set('ma_nv', main.encode_ma_nv_cookie(self.qc))
        for path in ('/', '/login', '/qc-login'):
            res = self.client.get(path, follow_redirects=False)
            self.assertEqual((res.status_code, res.headers['location']), (303, '/qc-input'), path)

    def test_input_page_loads_split_assets(self):
        page = self.client.get('/qc-input')
        self.assertEqual(page.status_code, 200, page.text[:200])
        import re
        urls = re.findall(r'(?:src|href)="(/assets/qc_input/[^"]+)"', page.text)
        self.assertGreaterEqual(len(urls), 10)  # 1 CSS + 9 JS
        for url in urls:
            self.assertRegex(url, r'\?v=\d+$')
            self.assertEqual(self.client.get(url).status_code, 200, url)

    def test_non_qc_login_still_goes_home(self):
        with self.connection.cursor() as cur:
            cur.execute("SELECT ma_nv FROM quality_employees WHERE COALESCE(qc_role, '') <> 'QC' LIMIT 1")
            other = cur.fetchone()[0]
        self.client.cookies.clear()
        res = self.client.post('/login', data={'ma_nv': other}, follow_redirects=False)
        self.assertEqual(res.headers['location'], '/')

    def test_quick_defect_combos_still_works(self):
        self.client.post('/api/qc/error-log-sp', json=self.error_body(1))
        response = self.client.get(f'/api/qc/input/quick-defect-combos?plan_id={PLAN_ID}&station=TEST&date={DAY}')
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn('rows', response.json())


if __name__ == '__main__':
    unittest.main()
