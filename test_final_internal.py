from pathlib import Path
import unittest

from final_internal_sync import ORDER_TYPE_LABELS, _inspector_name


class FinalInternalTests(unittest.TestCase):
    def test_final_inspector_name_removes_date_suffix(self):
        self.assertEqual(_inspector_name({"name": "QUYENQA-01/07/2026"}), "QUYENQA")
        self.assertEqual(_inspector_name({"name": "QA-NOI-BO-01/07/2026"}), "QA-NOI-BO")

    def test_final_order_type_labels_match_source_choices(self):
        self.assertEqual(ORDER_TYPE_LABELS["0"], "Replenishment (Lặp lại)")
        self.assertEqual(ORDER_TYPE_LABELS["1"], "Implantation (Đầu tiên)")

    def test_final_migration_only_requires_cap_for_fail(self):
        sql = Path("db/create_qa_final_internal.sql").read_text(encoding="utf-8")
        migration = Path("db/migrate_qa_final_cap_fail_only.sql").read_text(encoding="utf-8")
        self.assertIn("final_status_code = '0'", sql)
        self.assertNotIn("final_status_code IN ('0', '2')", sql)
        self.assertIn("SET cap_required = (final_status_code = '0')", migration)

    def test_final_cap_endpoint_and_sync_require_fail_only(self):
        app_source = Path("main.py").read_text(encoding="utf-8")
        sync_source = Path("final_internal_sync.py").read_text(encoding="utf-8")
        self.assertIn('final_status_code") or "") != "0"', app_source)
        self.assertIn('detail="Chỉ kết quả FAIL mới cần HĐKP 10.1"', app_source)
        self.assertIn('status_code == "0"', sync_source)

    def test_final_cap_editors_are_factory_scoped(self):
        app_source = Path("main.py").read_text(encoding="utf-8")
        migration = Path("db/migrate_final_cap_editors.sql").read_text(encoding="utf-8")
        self.assertIn('FINAL_CAP_ROLE = "FINAL_CAP"', app_source)
        self.assertIn('"XN1-V1": "XN01"', app_source)
        self.assertIn('"XN2": "XN02"', app_source)
        self.assertIn('"XN3": "XN03"', app_source)
        self.assertIn('"XNDT": "DT01"', app_source)
        for employee_code in ("H3853", "X0066", "Đ0051", "D9022", "L9003"):
            self.assertIn(employee_code, migration)

    def test_final_ui_contains_cap_and_sync_flows(self):
        html = Path("templates/final_internal.html").read_text(encoding="utf-8")
        self.assertIn("Final nội bộ", html)
        self.assertIn("/api/final-internal/sync", html)
        self.assertIn("/api/final-internal/${id}/cap", html)
        self.assertIn("Điền HĐKP 10.1", html)


if __name__ == "__main__":
    unittest.main()
