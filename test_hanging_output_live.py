"""Sản lượng chuyền treo trên trang nhập liệu QC: QLCL kéo trực tiếp từ app chuyền treo XN.
Dữ liệu DB được rollback; app chuyền treo được giả lập bằng HTTP server cục bộ.

Run: .venv/Scripts/python.exe -m unittest test_hanging_output_live -v
"""
import json
import logging
import threading
import time
from datetime import datetime, timedelta, timezone
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

import psycopg2
from fastapi.testclient import TestClient

import hanging_output_live
import main
from test_qc_roles import TransactionConnection

logging.getLogger('httpx').setLevel(logging.WARNING)
logging.getLogger('main').setLevel(logging.ERROR)

PLAN_ID = -927001
MONO = 'PL-LIVE-TEST-016'
DAY = '2026-11-26'
KEY = 'live-output-test-key'


class FakeHangingApp:
    """HTTP server giả app chuyền treo: GET /api/qlcl/hanging-output."""

    def __init__(self):
        self.qty = 182
        self.status = 200
        self.delay = 0
        self.calls = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                url = urlparse(self.path)
                if outer.delay:
                    time.sleep(outer.delay)
                outer.calls.append({'path': url.path, 'query': parse_qs(url.query),
                                    'key': self.headers.get('X-API-Key'),
                                    'ua': self.headers.get('User-Agent')})
                body = json.dumps({'mono': outer.calls[-1]['query'].get('mono', [''])[0], 'qty': outer.qty}).encode()
                self.send_response(outer.status)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.url = f'http://127.0.0.1:{self.server.server_address[1]}'
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


class HangingOutputLiveTest(unittest.TestCase):
    def setUp(self):
        hanging_output_live.clear_cache()
        self.addCleanup(hanging_output_live.clear_cache)
        self.connection = psycopg2.connect(main.DATABASE_URL)
        self.addCleanup(self.connection.close)
        self.addCleanup(self.connection.rollback)
        for target, value in (('get_db_connection', None), ('_PUSH_API_KEY', KEY)):
            p = (patch.object(main, target, return_value=TransactionConnection(self.connection))
                 if value is None else patch.object(main, target, value))
            p.start()
            self.addCleanup(p.stop)
        self.fake = FakeHangingApp()
        self.addCleanup(self.fake.close)
        self.urls_patch = patch.object(main, 'HANGING_APP_URLS', {'XN2': self.fake.url})
        self.urls_patch.start()
        self.addCleanup(self.urls_patch.stop)
        self.client = TestClient(main.app)
        self.addCleanup(self.client.close)
        with self.connection.cursor() as cur:
            cur.execute("SELECT ma_nv FROM quality_employees WHERE qc_role = 'QC' AND don_vi = 'XN2' LIMIT 1")
            self.qc = cur.fetchone()[0]
            cur.execute("""INSERT INTO prod_plan (id, ke_hoach, don_vi, bo_phan, is_active, mono, source_system)
                           VALUES (%s, 'LIVE TEST', 'XN2', '[]', TRUE, %s, 'hanging_line')""", (PLAN_ID, MONO))
            cur.execute("""INSERT INTO qc_hanging_output (don_vi, mono, report_date, qty, synced_at)
                           VALUES ('XN2', %s, %s, 71, '2026-11-26 16:02:20+07')""", (MONO, DAY))
        self.client.cookies.set('ma_nv', main.encode_ma_nv_cookie(self.qc))

    def get(self, **params):
        query = {'plan_id': PLAN_ID, 'date': DAY, **params}
        response = self.client.get('/api/qc/hanging-output', params=query)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def stored_qty(self):
        with self.connection.cursor() as cur:
            cur.execute("SELECT qty FROM qc_hanging_output WHERE don_vi='XN2' AND mono=%s AND report_date=%s",
                        (MONO, DAY))
            return cur.fetchone()[0]

    # --- Kéo trực tiếp ---
    def test_live_value_replaces_stale_pushed_value(self):
        data = self.get()
        self.assertEqual((data['qty'], data['available'], data['source']), (182, True, 'live'))
        self.assertIsNone(data['live_error'])
        self.assertTrue(data['live_configured'])
        self.assertEqual(self.stored_qty(), 182)  # lưu lại để dùng khi XN mất kết nối

    def test_request_carries_key_mono_date_and_browser_agent(self):
        self.get()
        call = self.fake.calls[0]
        self.assertEqual(call['path'], '/api/qlcl/hanging-output')
        self.assertEqual(call['query'], {'mono': [MONO], 'date': [DAY]})
        self.assertEqual(call['key'], KEY)
        self.assertIn('Mozilla', call['ua'])  # Cloudflare chặn UA mặc định của urllib

    def test_cache_shares_one_call_and_refresh_bypasses_it(self):
        self.get()
        self.fake.qty = 190
        self.assertEqual(self.get()['qty'], 182)
        self.assertEqual(len(self.fake.calls), 1)
        self.assertEqual(self.get(refresh='true')['qty'], 190)
        self.assertEqual(len(self.fake.calls), 2)

    def test_cache_expires(self):
        self.get()
        self.fake.qty = 200
        with patch.object(main, 'HANGING_OUTPUT_CACHE_SECONDS', 0):
            self.assertEqual(self.get()['qty'], 200)
        self.assertEqual(len(self.fake.calls), 2)

    def test_cache_is_per_date(self):
        self.get()
        self.get(date='2026-11-25')
        self.assertEqual([c['query']['date'][0] for c in self.fake.calls], [DAY, '2026-11-25'])

    def test_concurrent_requests_make_single_call(self):
        """Nhiều máy QC hỏi cùng lúc khi cache hết hạn → chỉ 1 lần gọi sang XN."""
        self.fake.delay = 0.5
        results, errors = [], []

        def worker(force):
            try:
                results.append(hanging_output_live.get_live_output('XN2', MONO, DAY, force=force)['qty'])
            except Exception as exc:  # pragma: no cover - báo lỗi qua errors
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(i % 5 == 0,)) for i in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(10)
        self.assertEqual(errors, [])
        self.assertEqual(results, [182] * 20)
        self.assertEqual(len(self.fake.calls), 1)

    def test_concurrent_requests_share_one_error(self):
        self.fake.delay = 0.3
        self.fake.status = 502
        errors = []

        def worker():
            try:
                hanging_output_live.get_live_output('XN2', MONO, DAY)
            except hanging_output_live.LiveOutputError as exc:
                errors.append(str(exc))

        threads = [threading.Thread(target=worker) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(10)
        self.assertEqual(len(errors), 10)
        self.assertEqual(len(self.fake.calls), 1)

    # --- Lỗi → số đã lưu ---
    def test_hanging_app_error_falls_back_to_stored_value(self):
        self.fake.status = 500
        data = self.get()
        self.assertEqual((data['qty'], data['source']), (71, 'stored'))
        self.assertIn('500', data['live_error'])
        self.assertEqual(datetime.fromisoformat(data['synced_at']),
                         datetime(2026, 11, 26, 16, 2, 20, tzinfo=timezone(timedelta(hours=7))))
        self.assertEqual(self.stored_qty(), 71)

    def test_error_is_cached_briefly_then_refresh_retries(self):
        self.fake.status = 403
        self.get()
        self.get()
        self.assertEqual(len(self.fake.calls), 1)
        self.fake.status = 200
        self.assertEqual(self.get(refresh='true')['source'], 'live')

    def test_unreachable_app_falls_back(self):
        port_closed = 'http://127.0.0.1:9'
        with patch.object(main, 'HANGING_APP_URLS', {'XN2': port_closed}), \
                patch.object(main, 'HANGING_OUTPUT_TIMEOUT_SECONDS', 2):
            data = self.get()
        self.assertEqual((data['qty'], data['source']), (71, 'stored'))
        self.assertIn('không kết nối', data['live_error'])

    def test_bad_payload_falls_back(self):
        with patch.object(hanging_output_live, '_fetch', side_effect=hanging_output_live.LiveOutputError('thiếu qty')):
            data = self.get()
        self.assertEqual((data['qty'], data['source'], data['live_error']), (71, 'stored', 'thiếu qty'))

    def test_unit_without_url_uses_pushed_value_without_calling(self):
        with patch.object(main, 'HANGING_APP_URLS', {}):
            data = self.get()
        self.assertEqual((data['qty'], data['source'], data['live_configured']), (71, 'stored', False))
        self.assertIsNone(data['live_error'])
        self.assertEqual(self.fake.calls, [])

    def test_no_stored_value_and_no_url_returns_zero(self):
        with patch.object(main, 'HANGING_APP_URLS', {}):
            data = self.get(date='2026-11-20')
        self.assertEqual((data['qty'], data['synced_at']), (0, None))

    # --- Kiểm tra đầu vào / phạm vi ---
    def test_invalid_date_is_rejected_without_calling(self):
        response = self.client.get('/api/qc/hanging-output', params={'plan_id': PLAN_ID, 'date': '26/11/2026'})
        self.assertEqual(response.status_code, 422)
        self.assertEqual(self.fake.calls, [])

    def test_non_hanging_plan_is_unchanged(self):
        with self.connection.cursor() as cur:
            cur.execute("UPDATE prod_plan SET source_system = NULL WHERE id = %s", (PLAN_ID,))
        self.assertEqual(self.get(), {'qty': 0, 'available': False})
        self.assertEqual(self.fake.calls, [])

    def test_other_factory_plan_is_forbidden(self):
        with self.connection.cursor() as cur:
            cur.execute("UPDATE prod_plan SET don_vi = 'XN3' WHERE id = %s", (PLAN_ID,))
        response = self.client.get('/api/qc/hanging-output', params={'plan_id': PLAN_ID, 'date': DAY})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.fake.calls, [])

    # --- Cấu hình + giao diện ---
    def test_unit_url_parsing(self):
        urls = main._parse_unit_urls(' XN2 = xn2.example.com/ ,XN3=http://10.0.0.3:8000,bad, =x,XN1-V1=')
        self.assertEqual(urls, {'XN2': 'https://xn2.example.com', 'XN3': 'http://10.0.0.3:8000'})

    def test_page_has_refresh_control(self):
        html = Path('templates/qc_input_sp.html').read_text(encoding='utf-8')
        js = Path('assets/qc_input/output.js').read_text(encoding='utf-8')
        self.assertIn('id="hlOutputMeta"', html)
        self.assertIn('onclick="refreshHangingOutput()"', html)
        self.assertIn('async function refreshHangingOutput()', js)
        self.assertIn("params.append('refresh', 'true')", js)


if __name__ == '__main__':
    unittest.main()
