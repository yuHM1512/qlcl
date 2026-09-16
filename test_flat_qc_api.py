import unittest
from unittest.mock import MagicMock
from datetime import date
from fastapi import FastAPI
from fastapi.testclient import TestClient
from flat_output import register


class FlatQCAPIEndpointTests(unittest.TestCase):
    def client(self, key='test-key'):
        connect = MagicMock()
        cur = connect.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value
        app = FastAPI()
        register(app, connect, key)
        return TestClient(app), connect, cur

    def test_auth_and_validation_before_database(self):
        for key, header, unit, day, status in [
            ('test-key', '', 'XN2', '2026-09-15', 403),
            ('', '', 'XN2', '2026-09-15', 403),
            ('test-key', 'test-key', 'XN9', '2026-09-15', 422),
            ('test-key', 'test-key', 'XN2', 'invalid', 422),
        ]:
            client, connect, _ = self.client(key)
            r = client.get('/api/tv3/flat-qc-data', params=dict(demand='mother', don_vi=unit, date=day), headers={'X-API-Key': header})
            self.assertEqual(r.status_code, status)
            connect.assert_not_called()

    def test_mother_resolution_factory_alias_and_empty_plan(self):
        client, _, cur = self.client()
        cur.fetchone.return_value = None
        r = client.get('/api/tv3/flat-qc-data', params=dict(demand='mother', don_vi='XN1', date='2026-09-15'), headers={'X-API-Key': 'test-key'})
        self.assertEqual(r.json()['status'], 'empty')
        query, params = cur.execute.call_args.args
        self.assertIn('don_vi=%s', query)
        self.assertEqual(params, ('XN1-V1:mother', 'XN1-V1'))

    def test_summary_details_slots_and_alerts_use_final_station(self):
        client, _, cur = self.client()
        cur.fetchone.side_effect = [{'id': 22}, {'records': 1, 'defects': 2}]
        cur.fetchall.side_effect = [[dict(department='A', detail='B', defect='C', quantity=3)], [dict(slot=1, defects=2)], [dict(time='08:30:00', bo_phan='A', chi_tiet='B', ma_loi='C')]]
        r = client.get('/api/tv3/flat-qc-data', params=dict(demand='mother', don_vi='XN2', date='2026-09-15'), headers={'X-API-Key': 'test-key'})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()['defects'], 2)
        self.assertEqual(r.json()['details'][0]['quantity'], 3)
        self.assertEqual(r.json()['slots'], [dict(slot=1, defects=2)])
        self.assertEqual(r.json()['alerts'][0]['time'], '08:30')
        queries = cur.execute.call_args_list[2:]
        self.assertEqual(len(queries), 4)
        for call in queries:
            self.assertIn("='Trạm cuối chuyền'", call.args[0])
            self.assertEqual(call.args[1], (22, date(2026, 9, 15)))
        self.assertIn('GROUP BY d.error_log_sp_id,d.sp_index', queries[2].args[0])
        self.assertIn('Asia/Ho_Chi_Minh', queries[2].args[0])
