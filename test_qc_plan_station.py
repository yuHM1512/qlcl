"""Phân công QC theo MONo (push từ chuyền treo) + kết thúc kế hoạch từ chuyền treo.
Mọi dữ liệu test được rollback.

Run: .venv/Scripts/python.exe -m unittest test_qc_plan_station -v
"""
import json
import logging
import unittest
from unittest.mock import patch

import psycopg2
import psycopg2.extras
from fastapi.testclient import TestClient

import main
from test_qc_roles import TransactionConnection

logging.getLogger('httpx').setLevel(logging.WARNING)

KEY = 'qc-plan-station-test-key'
UNIT = 'XN2'
QC_A, QC_B = 'ZZTEST-QCA', 'ZZTEST-QCB'
MONO_A, MONO_B, MONO_C, MONO_D = 'ZZTEST-MO-A', 'ZZTEST-MO-B', 'ZZTEST-MO-C', 'ZZTEST-MO-D'
S16, S18 = 'Odr 16 - QC kiểm TP', 'Odr 18 - QC Kiểm TP'


class QcPlanStationTest(unittest.TestCase):
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
            cur.execute("SELECT ten_loai FROM dm_loai_hang ORDER BY ten_loai LIMIT 1")
            self.loai_hang = cur.fetchone()[0]
            cur.execute("DELETE FROM qc_employee_plan_station WHERE don_vi = %s", (UNIT,))

    # --- helpers ---
    def login(self, employee):
        self.client.cookies.set('ma_nv', main.encode_ma_nv_cookie(employee))

    def push_plan(self, mono, line_no=5, **overrides):
        plan = {'guid': f'guid-{mono}', 'mono': mono, 'ke_hoach': f'HL-{mono}', 'line_no': line_no,
                'style_no': mono, 'customer': 'CUST', 'loai_hang': self.loai_hang,
                'first_hang': '2026-11-20', 'san_luong': 100}
        plan.update(overrides)
        response = self.client.post('/api/prod-plan/push-from-hl', headers={'X-API-Key': KEY},
                                    json={'don_vi': UNIT, 'plans': [plan]})
        self.assertEqual(response.status_code, 200, response.text)
        return self.plan(mono)

    def plan(self, mono):
        with self.connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT * FROM prod_plan WHERE mono = %s", (mono,))
            return cur.fetchone()

    def push_employees(self, employees, **extra):
        body = {'don_vi': UNIT, 'employees': employees}
        body.update(extra)
        response = self.client.post('/api/qc/employees/push-from-hl', headers={'X-API-Key': KEY}, json=body)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    @staticmethod
    def emp(ma_nv, plans, bo_phan='5'):
        stations = sorted({s for p in plans for s in p['station']})
        return {'ma_nv': ma_nv, 'ho_ten': f'Test {ma_nv}', 'bo_phan': bo_phan, 'station': stations, 'plans': plans}

    def plan_stations(self):
        with self.connection.cursor() as cur:
            cur.execute("SELECT mono, ma_nv, station FROM qc_employee_plan_station WHERE don_vi = %s "
                        "ORDER BY mono, ma_nv, station", (UNIT,))
            return cur.fetchall()

    # --- kết thúc / mở lại từ chuyền treo ---
    def test_hl_finish_then_reopen(self):
        row = self.push_plan(MONO_A, is_finished=True)
        self.assertTrue(row['is_finished'])
        row = self.push_plan(MONO_A, is_finished=False)
        self.assertFalse(row['is_finished'])

    def test_hl_reopen_keeps_manual_qa_finish(self):
        self.push_plan(MONO_A, is_finished=False)
        with self.connection.cursor() as cur:
            cur.execute("UPDATE prod_plan SET is_finished = TRUE WHERE mono = %s", (MONO_A,))
        row = self.push_plan(MONO_A, is_finished=False)
        self.assertTrue(row['is_finished'])

    # --- công đoạn theo MONo ---
    def test_full_then_per_plan_sync_only_replaces_that_mono(self):
        self.push_employees(
            [self.emp(QC_A, [{'mono': MONO_A, 'station': [S16]}, {'mono': MONO_B, 'station': [S18]}])],
            replace_station_scope=True, plan_monos=[MONO_A, MONO_B])
        self.assertEqual(self.plan_stations(), [(MONO_A, QC_A, S16), (MONO_B, QC_A, S18)])

        self.push_employees([self.emp(QC_B, [{'mono': MONO_B, 'station': [S16]}])],
                            replace_station_scope=False, plan_monos=[MONO_B])
        self.assertEqual(self.plan_stations(), [(MONO_A, QC_A, S16), (MONO_B, QC_B, S16)])

        # MONo không còn ai → vẫn xoá phân công cũ của MONo đó
        self.push_employees([], replace_station_scope=False, plan_monos=[MONO_A])
        self.assertEqual(self.plan_stations(), [(MONO_B, QC_B, S16)])

    def test_legacy_payload_without_plan_monos_leaves_table(self):
        self.push_employees([self.emp(QC_A, [{'mono': MONO_A, 'station': [S16]}])],
                            replace_station_scope=True, plan_monos=[MONO_A])
        legacy = {'ma_nv': QC_A, 'ho_ten': 'Test', 'bo_phan': '5', 'station': [S18]}
        self.push_employees([legacy], replace_station_scope=True)
        self.assertEqual(self.plan_stations(), [(MONO_A, QC_A, S16)])

    # --- TV-3: chỉ lấy trạm cụm 6 theo odrs ---
    def test_tv3_qc_data_filters_by_station_odr(self):
        plan_id = self.push_plan(MONO_A)['id']
        day = '2026-11-27'
        with self.connection.cursor() as cur:
            for station, output, defects in ((S16, 40, 4), (S18, 100, 3), ('Odr 1 - Cắt', 10, 9)):
                cur.execute("INSERT INTO qc_error_log_sp (plan_id, date, station, output, defect_count) "
                            "VALUES (%s, %s, %s, %s, %s)", (plan_id, day, station, output, defects))
            for station in (S16, S18):
                cur.execute("INSERT INTO qc_defect_multi (plan_id, date, station, time, bo_phan, chi_tiet, ma_loi) "
                            "VALUES (%s, %s, %s, '10:00', 'BP', 'CT', 'ML')", (plan_id, day, station))
        get = lambda **p: self.client.get('/api/tv3/qc-data', headers={'X-API-Key': KEY},
                                          params={'mono': MONO_A, 'date': day, **p})

        only18 = get(odrs='18').json()
        self.assertEqual((only18['total_kiem'], only18['total_loi'], only18['odrs']), (100, 3, [18]))
        self.assertEqual(sum(s['loi'] for s in only18['slots']), 3)
        self.assertEqual(len(only18['canh_bao']), 1)

        both = get(odrs='16,18').json()
        self.assertEqual((both['total_kiem'], both['total_loi']), (140, 7))

        everything = get().json()  # không truyền odrs → mọi trạm như cũ
        self.assertEqual((everything['total_kiem'], everything['total_loi']), (150, 16))

        self.assertEqual(get(odrs='18,x').status_code, 422)

    # --- danh sách kế hoạch + trạm trên trang nhập liệu ---
    def test_qc_sees_assigned_monos_and_unassigned_same_line(self):
        ids = {m: self.push_plan(m, line_no=line)['id']
               for m, line in ((MONO_A, 5), (MONO_B, 5), (MONO_C, 6), (MONO_D, 5))}
        self.push_employees([
            self.emp(QC_A, [{'mono': MONO_A, 'station': [S18]}, {'mono': MONO_C, 'station': [S16]}]),
            self.emp(QC_B, [{'mono': MONO_B, 'station': [S16]}]),
        ], replace_station_scope=True, plan_monos=[MONO_A, MONO_B, MONO_C])

        self.login(QC_A)
        rows = self.client.get('/api/prod-plan', params={'don_vi': UNIT, 'bo_phan': 'Tổ 5', 'only_active': 'true'})
        self.assertEqual(rows.status_code, 200, rows.text)
        seen = {r['id'] for r in rows.json()['rows']}
        self.assertIn(ids[MONO_A], seen)      # được phân công
        self.assertIn(ids[MONO_C], seen)      # được phân công ở tổ khác
        self.assertIn(ids[MONO_D], seen)      # cùng tổ, chưa có phân công
        self.assertNotIn(ids[MONO_B], seen)   # đã phân cho QC khác

        page = self.client.get('/qc-input')
        self.assertEqual(page.status_code, 200, page.text)
        start = page.text.index('id="pageContext"')
        ctx = json.loads(page.text[page.text.index('>', start) + 1:page.text.index('</script>', start)])
        self.assertEqual(ctx['plan_stations'], {MONO_A: [S18], MONO_C: [S16]})


if __name__ == '__main__':
    unittest.main()
