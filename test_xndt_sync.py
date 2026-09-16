"""Database integration checks; target writes are always rolled back."""
import unittest
from unittest.mock import patch, MagicMock
import psycopg2
from fastapi.testclient import TestClient
import main
import xndt_sync


class RollbackConnection:
    def __init__(self, conn):
        self.conn = conn
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return False
    def cursor(self, *args, **kwargs):
        return self.conn.cursor(*args, **kwargs)
    def close(self):
        pass


class XndtSyncTests(unittest.TestCase):
    def test_team_mapping(self):
        self.assertEqual(xndt_sync.normalize_teams(['UDT-L1', 'UDT - L01', 'UDT - L5']), ['Tổ 1', 'Tổ 5'])
        self.assertEqual(xndt_sync.normalize_teams('UDT - L5 + UDT - L1'), ['Tổ 5', 'Tổ 1'])
        self.assertEqual(xndt_sync.normalize_teams(['1', 'Tổ 1', 'UDT-L11', 'U3-L1']), ['Tổ 1', 'Tổ 11', 'U3-L1'])

    def test_qc_team_filter_accepts_legacy_and_normalized_codes(self):
        conn = psycopg2.connect(main.DATABASE_URL)
        try:
            with conn.cursor() as cur:
                for identity, unit, teams in [(-916101, 'XNDT', '["UDT - L1"]'),
                        (-916102, 'XNDT', '["Tổ 1"]'),
                        (-916103, 'XNDT', '["UDT-L11"]'),
                        (-916104, 'XN2', '["UDT-L1"]'),
                        (-916105, 'XNDT', '["UDT - L5", "UDT-L1"]')]:
                    cur.execute('INSERT INTO prod_plan(id,don_vi,bo_phan,is_active) VALUES(%s,%s,%s::jsonb,true)', (identity,unit,teams))
            with patch.object(main, 'get_db_connection', return_value=RollbackConnection(conn)), \
                 patch.object(main, 'get_authenticated_user', return_value=dict(qc_role='QC',don_vi='XNDT',bo_phan='1')):
                response = TestClient(main.app).get('/api/prod-plan?don_vi=XNDT&bo_phan=1&only_active=true')
            self.assertEqual(response.status_code, 200, response.text)
            rows = {r['id']:r for r in response.json()['rows']}
            for identity in (-916101,-916102,-916105):
                self.assertIn(identity, rows)
                self.assertIn('Tổ 1', rows[identity]['bo_phan'])
            for identity in (-916103,-916104):
                self.assertNotIn(identity, rows)
        finally:
            conn.rollback()
            conn.close()

    def test_real_snapshot_is_idempotent_and_preserves_other_units(self):
        conn = psycopg2.connect(main.DATABASE_URL)
        try:
            def state():
                with conn.cursor() as cur:
                    cur.execute("SELECT id,source_record_id FROM prod_plan WHERE don_vi='XNDT' ORDER BY id")
                    plans = cur.fetchall()
                    cur.execute("SELECT * FROM qc_flat_output WHERE don_vi<>'XNDT' ORDER BY don_vi,source_record_id,report_date")
                    return plans, cur.fetchall()
            before = state()
            first = xndt_sync.sync(lambda: RollbackConnection(conn), main.DATABASE_URL)
            after = state()
            second = xndt_sync.sync(lambda: RollbackConnection(conn), main.DATABASE_URL)
            self.assertEqual(after, state())
            self.assertEqual(before[1], after[1])
            self.assertEqual(second['inserted'], 0)
            self.assertEqual(first['outputs'], second['outputs'])
            with conn.cursor() as cur:
                cur.execute("SELECT count(*) FROM qc_flat_output WHERE don_vi='XNDT'")
                self.assertEqual(cur.fetchone()[0], first['outputs'])
        finally:
            conn.rollback()
            conn.close()

    def test_factory_permissions(self):
        client = TestClient(main.app)
        for role, unit, expected in [('QA_ADMIN', '', 200), ('FACTORY_ADMIN', 'XNDT', 200),
                                     ('FACTORY_ADMIN', 'XN2', 403), ('QC', 'XNDT', 403)]:
            user = dict(qc_role=role, don_vi=unit)
            with patch.object(main, 'get_authenticated_user', return_value=user), \
                 patch.object(xndt_sync, 'sync', return_value={'status':'ok'}) as sync:
                response = client.post('/api/prod-plan/sync-xndt')
                self.assertEqual(response.status_code, expected, response.text)
                self.assertEqual(sync.called, expected == 200)

    def test_missing_snapshot_does_not_delete(self):
        target = MagicMock()
        source = MagicMock()
        source.cursor.return_value.__enter__.return_value.fetchone.return_value = None
        with patch.object(xndt_sync, 'source_connection', return_value=source):
            with self.assertRaises(ValueError):
                xndt_sync.sync(lambda: target, 'unused')
        calls = target.cursor.return_value.__enter__.return_value.execute.call_args_list
        self.assertFalse(any('DELETE' in c.args[0] or 'INSERT' in c.args[0] for c in calls))


if __name__ == '__main__':
    unittest.main()
