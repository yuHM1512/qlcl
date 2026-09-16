import unittest
from unittest.mock import Mock
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from flat_output import validate, register


class FlatOutputTests(unittest.TestCase):
    def data(self):
        return dict(don_vi='XN2',outputs=[dict(source_record_id='XN2:mother',date='2026-09-12',qty=80,
            slots=[dict(slot=i+1,qty=v,cumulative=c) for i,(v,c) in enumerate([(100,100),(-20,80),(None,None),(None,None),(None,None)])])])

    def test_corrections_and_missing_slots(self):
        self.assertEqual(validate(self.data())[1][0]['qty'],80)

    def test_cross_unit_duplicate_and_bad_totals_rejected(self):
        for change in ('unit','duplicate','total'):
            p=self.data()
            if change=='unit': p['outputs'][0]['source_record_id']='XN3:mother'
            if change=='duplicate': p['outputs']*=2
            if change=='total': p['outputs'][0]['qty']=900
            with self.assertRaises(HTTPException): validate(p)

    def test_auth_rejected_before_database(self):
        app=FastAPI()
        connect=Mock()
        register(app,connect,'test-key')
        response=TestClient(app).post('/api/qc/flat-output/push',json=self.data())
        self.assertEqual(response.status_code,403)
        connect.assert_not_called()

if __name__=='__main__': unittest.main()
