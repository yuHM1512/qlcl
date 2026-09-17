"""Integration checks against the configured database; all test data is rolled back.

Run: .venv/Scripts/python.exe -m unittest test_qc_roles -v
Requires httpx for FastAPI's TestClient. Apply the role migration first.
"""
import logging
import unittest
from pathlib import Path
from unittest.mock import patch

import psycopg2
from fastapi.testclient import TestClient
import main

logging.getLogger('httpx').setLevel(logging.WARNING)


class TransactionConnection:
    def __init__(self, connection):
        self.connection = connection

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def cursor(self, *args, **kwargs):
        return self.connection.cursor(*args, **kwargs)

    def commit(self):
        pass  # The test owns the outer transaction.


class QCRolesTest(unittest.TestCase):
    def setUp(self):
        self.connection = psycopg2.connect(main.DATABASE_URL)
        self.addCleanup(self.connection.close)
        self.addCleanup(self.connection.rollback)
        self.db_patch = patch.object(main, 'get_db_connection', return_value=TransactionConnection(self.connection))
        self.db_patch.start()
        self.addCleanup(self.db_patch.stop)
        self.client = TestClient(main.app)
        self.addCleanup(self.client.close)
        with self.connection.cursor() as cur:
            cur.execute("SELECT ma_nv FROM quality_employees WHERE qc_role = 'QA_ADMIN' ORDER BY ma_nv LIMIT 1")
            self.qa = cur.fetchone()[0]
            cur.execute("SELECT ma_nv FROM quality_employees WHERE qc_role = 'QC' AND don_vi = 'XN2' LIMIT 1")
            self.qc = cur.fetchone()[0]
            cur.execute("SELECT ma_nv FROM quality_employees WHERE qc_role IS NULL LIMIT 1")
            self.no_role = cur.fetchone()[0]
            cur.execute("""INSERT INTO prod_plan (id, ke_hoach, don_vi, bo_phan, is_active)
                        VALUES (-916001, 'ROLE TEST XN2', 'XN2', '[]', TRUE),
                               (-916002, 'ROLE TEST XN3', 'XN3', '[]', TRUE)""")

    def login(self, employee):
        self.client.cookies.set('ma_nv', main.encode_ma_nv_cookie(employee))

    def test_seed_accounts_and_positions(self):
        with self.connection.cursor() as cur:
            cur.execute("SELECT ma_nv, chuc_vu, qc_role, don_vi FROM quality_employees WHERE ma_nv IN ('B0443','H1289') ORDER BY ma_nv")
            self.assertEqual(cur.fetchall(), [('B0443','Điều độ','FACTORY_ADMIN','XN3'), ('H1289','Điều độ','FACTORY_ADMIN','XN2')])
            cur.execute("SELECT chuc_vu FROM quality_employees WHERE ma_nv = %s", (self.qa,))
            self.assertEqual(cur.fetchone()[0], 'QAQT')

    def test_migration_rerun_does_not_restore_revoked_role(self):
        with self.connection.cursor() as cur:
            cur.execute("UPDATE quality_employees SET qc_role = NULL WHERE ma_nv = 'B0443'")
            sql = Path('db/migrate_qc_roles_20260916.sql').read_text(encoding='utf-8')
            sql = sql.replace('BEGIN;\n', '', 1).removesuffix('COMMIT;\n')
            cur.execute(sql)
            cur.execute("SELECT qc_role FROM quality_employees WHERE ma_nv = 'B0443'")
            self.assertIsNone(cur.fetchone()[0])

    def test_all_catalog_writes_require_qa(self):
        paths = [(route.path, method) for route in main.app.routes
                 if route.path.startswith('/api/dm/')
                 for method in route.methods if method in {'POST','PATCH','DELETE','PUT'}]
        self.assertGreater(len(paths), 10)
        for account, expected in [(None,401), (self.qc,403), ('H1289',403), (self.no_role,403)]:
            self.client.cookies.clear()
            if account:
                self.login(account)
            for path, method in paths:
                with self.subTest(account=account, path=path):
                    response = self.client.request(method, path.replace('{id}','-916001'), json={})
                    self.assertEqual(response.status_code, expected, response.text)

    def test_qa_can_edit_catalog(self):
        self.login(self.qa)
        response = self.client.post('/api/dm/khach-hang', json={'ten_khach_hang':'ROLE TEST CUSTOMER'})
        self.assertEqual(response.status_code, 200, response.text)

    def test_factory_manages_local_qc_but_not_admin_roles_or_visuals(self):
        self.login('H1289')
        local_qc = {'ma_nv':'ROLE_TEST_QC','ho_ten':'Role Test QC','chuc_vu':'QC',
                    'don_vi':'XN2','bo_phan':'1','station':['QC kiểm thành phẩm'],'qc_role':'QC'}
        response = self.client.post('/api/qc/employees', json=local_qc)
        self.assertEqual(response.status_code, 200, response.text)

        for changes in [
            {**local_qc, 'don_vi':'XN3'},
            {**local_qc, 'qc_role':'FACTORY_ADMIN'},
            {**local_qc, 'qc_role':'QA_ADMIN'},
        ]:
            response = self.client.post('/api/qc/employees', json=changes)
            self.assertEqual(response.status_code, 403, response.text)

        response = self.client.patch('/api/qc/visual-picker/hotspots-batch', json={})
        self.assertEqual(response.status_code, 403, response.text)

    def test_factory_plan_list_ignores_other_factory_filter(self):
        for account, factory in [('B0443','XN3'),('H1289','XN2'),(self.qc,'XN2')]:
            self.login(account)
            response=self.client.get('/api/prod-plan?don_vi=XNV2')
            self.assertEqual(response.status_code,200,response.text)
            self.assertTrue(response.json()['rows'])
            self.assertTrue(all(row['don_vi']==factory for row in response.json()['rows']))

    def test_factory_plan_crud(self):
        self.login('H1289')
        body={'don_vi':'XN2','bo_phan':'1','ke_hoach':'ROLE TEST CREATED'}
        response=self.client.post('/api/prod-plan',json=body)
        self.assertEqual(response.status_code,200,response.text)
        plan_id=response.json()['id']
        self.assertEqual(self.client.patch(f'/api/prod-plan/{plan_id}',json={'ke_hoach':'UPDATED'}).status_code,200)
        self.assertEqual(self.client.delete(f'/api/prod-plan/{plan_id}').status_code,200)
        body['don_vi']='XN3'
        self.assertEqual(self.client.post('/api/prod-plan',json=body).status_code,403)

    def test_factory_cannot_edit_delete_or_move_other_plans(self):
        self.login('H1289')
        self.assertEqual(self.client.patch('/api/prod-plan/-916002',json={'ke_hoach':'NO'}).status_code,403)
        self.assertEqual(self.client.delete('/api/prod-plan/-916002').status_code,403)
        self.assertEqual(self.client.patch('/api/prod-plan/-916001',json={'don_vi':'XN3'}).status_code,403)
        self.assertEqual(self.client.patch('/api/prod-plan/-916001',json={'don_vi':None}).status_code,400)

    def test_qa_manages_all_factory_plans(self):
        self.login(self.qa)
        for plan_id in [-916001,-916002]:
            self.assertEqual(self.client.patch(f'/api/prod-plan/{plan_id}',json={'ke_hoach':'QA EDIT'}).status_code,200)

    def test_qc_cannot_manage_plans(self):
        self.login(self.qc)
        for method,path in [('POST','/api/prod-plan'),('PATCH','/api/prod-plan/-916001'),('DELETE','/api/prod-plan/-916001'),('POST','/api/prod-plan/sync-qtcn'),('POST','/api/prod-plan/sync-flat-line?don_vi=XN2')]:
            self.assertEqual(self.client.request(method,path,json={}).status_code,403)

    def test_sync_is_scoped(self):
        self.login('H1289')
        self.assertEqual(self.client.post('/api/prod-plan/sync-qtcn').status_code,403)
        self.assertEqual(self.client.post('/api/prod-plan/sync-flat-line?don_vi=XN3').status_code,403)
        with patch.object(main,'sync_flat_line_prod_plan',return_value={'status':'ok'}) as sync:
            self.assertEqual(self.client.post('/api/prod-plan/sync-flat-line?don_vi=XN2').status_code,200)
            sync.assert_called_once_with('XN2')

    def test_qa_syncs_all_flat_line_sources(self):
        self.login(self.qa)
        result = {
            'status':'ok', 'factories':[{'don_vi':'XN1-V1'},{'don_vi':'XN2'},{'don_vi':'XN3'}],
            'errors':[], 'inserted':3, 'updated':4, 'deactivated':0, 'skipped':0,
        }
        with patch.object(main,'sync_all_flat_line_prod_plans',return_value=result) as sync:
            response=self.client.post('/api/prod-plan/sync-flat-line?all_factories=true')
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json()['inserted'],3)
        sync.assert_called_once_with()

    def test_factory_cannot_sync_all_flat_line_sources(self):
        self.login('H1289')
        response=self.client.post('/api/prod-plan/sync-flat-line?all_factories=true')
        self.assertEqual(response.status_code,403,response.text)

    def test_xnv2_sync_is_only_qa_or_xnv2_factory_admin(self):
        self.login('H1289')
        self.assertEqual(self.client.post('/api/prod-plan/sync-qtcn').status_code,403)
        with self.connection.cursor() as cur:
            cur.execute("UPDATE quality_employees SET don_vi='XNV2' WHERE ma_nv='H1289'")
        page=self.client.get('/qc').text
        self.assertIn('Sync XNV2',page)
        self.assertNotIn('onclick="syncFlatLinePlans(',page)
        self.assertNotIn('onclick="syncAllFlatLinePlans()"',page)
        with patch.object(main,'sync_qtcn_prod_plan',return_value={'status':'ok'}) as sync:
            response=self.client.post('/api/prod-plan/sync-qtcn')
        self.assertEqual(response.status_code,200,response.text)
        sync.assert_called_once_with()

    def test_plan_reports_cannot_cross_factory(self):
        self.login(self.qc)
        for path in ['/api/qc/output-sp','/api/qc/error-log-sp','/api/qc/hanging-output','/api/qc/input/pos-summary','/api/qc/input/quick-defect-combos','/api/qc/input/quick-defect-combos-today']:
            response=self.client.get(path,params={'plan_id':-916002,'date':'2026-09-16','station':'QC sau seam'})
            self.assertEqual(response.status_code,403,response.text)

    def test_integration_report_follows_scope(self):
        with self.connection.cursor() as cur:
            cur.execute("UPDATE prod_plan SET mono='ROLE-TEST-MONO' WHERE id=-916002")
        response=self.client.get('/api/tv3/qc-data?mono=ROLE-TEST-MONO&date=2026-09-16')
        self.assertEqual(response.status_code,401)
        self.login(self.qc)
        response=self.client.get('/api/tv3/qc-data?mono=ROLE-TEST-MONO&date=2026-09-16')
        self.assertEqual(response.status_code,200,response.text)
        self.assertFalse(response.json()['found'])
        with patch.object(main,'_PUSH_API_KEY','role-test-key'):
            response=self.client.get('/api/tv3/qc-data?mono=ROLE-TEST-MONO&date=2026-09-16',headers={'X-API-Key':'role-test-key'})
            self.assertEqual(response.status_code,200,response.text)
            self.assertTrue(response.json()['found'])

    def test_push_requires_configured_key(self):
        with patch.object(main,'_PUSH_API_KEY',''):
            for path in ['/api/prod-plan/push-from-hl','/api/qc/employees/push-from-hl','/api/qc/hanging-output/push']:
                self.assertEqual(self.client.post(path,json={}).status_code,403)

    def test_hanging_output_same_mono_is_scoped(self):
        with self.connection.cursor() as cur:
            cur.execute("UPDATE prod_plan SET mono='ROLE-TEST-MONO',source_system='hanging_line' WHERE id=-916001")
            cur.execute("""INSERT INTO qc_hanging_output(don_vi,mono,report_date,qty,synced_at)
                VALUES ('XN2','ROLE-TEST-MONO','2026-09-16',10,NOW()),
                       ('XN3','ROLE-TEST-MONO','2026-09-16',999,NOW()+INTERVAL '1 second')""")
        self.login(self.qc)
        response=self.client.get('/api/qc/hanging-output?plan_id=-916001&date=2026-09-16')
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json()['qty'],10)

    def test_input_uses_role_instead_of_position(self):
        with self.connection.cursor() as cur:
            cur.execute("UPDATE quality_employees SET chuc_vu='Công nhân' WHERE ma_nv=%s",(self.qc,))
        self.login(self.qc)
        self.assertEqual(self.client.get('/qc-input').status_code,200)
        response=self.client.post('/api/qc/output-sp-log',json={'plan_id':-916001,'delta':1})
        self.assertEqual(response.status_code,200,response.text)

    def test_employee_sync_preserves_admin_role_and_position(self):
        payload={'don_vi':'XN2','employees':[{'ma_nv':'H1289','ho_ten':'DO NOT CHANGE','bo_phan':'1'}]}
        with patch.object(main,'_PUSH_API_KEY','role-test-key'):
            response=self.client.post('/api/qc/employees/push-from-hl',json=payload,headers={'X-API-Key':'role-test-key'})
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json()['skipped'],1)
        with self.connection.cursor() as cur:
            cur.execute("SELECT qc_role,chuc_vu FROM quality_employees WHERE ma_nv='H1289'")
            self.assertEqual(cur.fetchone(),('FACTORY_ADMIN','Điều độ'))

    def test_qc_input_is_scoped_and_records_employee(self):
        self.login(self.qc)
        body={'plan_id':-916001,'date':'2026-09-16','delta':1,'status':'Passed'}
        response=self.client.post('/api/qc/output-sp-log',json=body)
        self.assertEqual(response.status_code,200,response.text)
        with self.connection.cursor() as cur:
            cur.execute('SELECT ma_nv FROM qc_output_sp_log WHERE plan_id=-916001')
            self.assertEqual(cur.fetchone()[0],self.qc)
        body['plan_id']=-916002
        self.assertEqual(self.client.post('/api/qc/output-sp-log',json=body).status_code,403)
        self.assertEqual(self.client.post('/api/qc/error-log-sp',json=body).status_code,403)

    def test_missing_factory_denies_access(self):
        with self.connection.cursor() as cur:
            cur.execute('UPDATE quality_employees SET don_vi=NULL WHERE ma_nv=%s',(self.qc,))
        self.login(self.qc)
        for path in ['/api/prod-plan','/api/qc/dashboard/filters','/qc-input']:
            self.assertEqual(self.client.get(path).status_code,403)

    def test_role_assignment_and_self_demotion(self):
        self.login(self.qa)
        body={'ma_nv':self.no_role,'ho_ten':'ROLE TEST','chuc_vu':'Điều độ','don_vi':'XN3','bo_phan':'Điều độ','qc_role':'FACTORY_ADMIN'}
        response=self.client.post('/api/qc/employees',json=body)
        self.assertEqual(response.status_code,200,response.text)
        body['don_vi']=''
        self.assertEqual(self.client.post('/api/qc/employees',json=body).status_code,422)
        body.update(ma_nv=self.qa,qc_role=None)
        self.assertEqual(self.client.post('/api/qc/employees',json=body).status_code,400)

    def test_dashboard_scope_for_qc(self):
        self.login(self.qc)
        response=self.client.get('/api/qc/dashboard/filters?don_vi=XN3')
        self.assertEqual(response.status_code,200,response.text)
        self.assertTrue(all(unit=='XN2' for unit in response.json().get('don_vi',[])))
        response=self.client.get('/api/qc/dashboard',params={'date_from':'2026-09-16','date_to':'2026-09-16','don_vi':'XN3'})
        self.assertEqual(response.status_code,200,response.text)

    def test_pages_and_navigation(self):
        for account in [self.qa,'B0443',self.qc]:
            self.login(account)
            self.assertEqual(self.client.get('/qc/dashboard').status_code,200)
        self.login('B0443')
        page=self.client.get('/qc').text
        self.assertIn('Tổng quan Kế hoạch',page)
        self.assertIn('Sync bệt XN3',page)
        self.assertNotIn('Sync XNV2',page)
        self.assertNotIn('onclick="syncAllFlatLinePlans()"',page)
        self.assertNotIn('href="/qc/settings/customer"',page)
        self.login(self.qa)
        page=self.client.get('/qc').text
        self.assertIn('Sync XNV2',page)
        self.assertIn('Sync bệt',page)
        self.assertNotIn('Sync bệt XN1-V1',page)
        self.assertNotIn('Sync bệt XN2',page)
        self.assertNotIn('Sync bệt XN3',page)
        page=self.client.get('/qc/settings/qc-list').text
        self.assertIn('id="fQCRole"',page)
        self.assertIn('FACTORY_ADMIN',page)
        self.login(self.qc)
        self.assertIn('href="/qc/dashboard"',self.client.get('/qc-input').text)
        self.assertNotIn('onclick="syncQtcnPlans()"',self.client.get('/qc-input').text)


if __name__ == '__main__':
    unittest.main()
