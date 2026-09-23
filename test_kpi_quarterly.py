import unittest
import platform
from unittest.mock import MagicMock, patch

# Avoid a slow Windows WMI lookup while SQLAlchemy is imported in test runs.
with patch.object(platform, "machine", return_value="AMD64"):
    import main


class KPIQuarterlySummaryTests(unittest.TestCase):
    def test_quarterly_summary_merges_completed_work_and_errors(self):
        connection = MagicMock()
        cursor = connection.__enter__.return_value.cursor.return_value.__enter__.return_value
        cursor.fetchall.side_effect = [
            [{"task_name": "Gemba"}, {"task_name": "Pre-final"}],
            [
                {
                    "year_key": 2026,
                    "quarter_key": 1,
                    "ma_nv": "QA01",
                    "ho_ten": "Nguyen Van A",
                    "task_name": "Gemba",
                    "thuc_hien": 12,
                }
            ],
            [
                {
                    "year_key": 2026,
                    "quarter_key": 1,
                    "ma_nv": "QA01",
                    "ho_ten": "Nguyen Van A",
                    "task_name": "Gemba",
                    "sai_sot": 2,
                },
                {
                    "year_key": 2026,
                    "quarter_key": 1,
                    "ma_nv": "QA02",
                    "ho_ten": "Tran Thi B",
                    "task_name": "Pre-final",
                    "sai_sot": 1,
                },
            ],
        ]

        with patch.object(main, "get_db_connection", return_value=connection):
            result = main.api_summary_quarterly("QAQT", quarter=1, year=2026)

        self.assertEqual(result["tasks"], ["Gemba", "Pre-final"])
        self.assertEqual(len(result["rows"]), 2)
        first, second = result["rows"]
        self.assertEqual(first["quarter_year"], "Q1-2026")
        self.assertEqual(first["metrics"]["Gemba"], {"thuc_hien": 12, "sai_sot": 2})
        self.assertEqual(second["ho_ten"], "Tran Thi B")
        self.assertEqual(second["metrics"]["Pre-final"], {"thuc_hien": 0, "sai_sot": 1})

        qa_query, qa_params = cursor.execute.call_args_list[1].args
        error_query, error_params = cursor.execute.call_args_list[2].args
        self.assertIn("EXTRACT(QUARTER FROM from_date) = %s", qa_query)
        self.assertEqual(qa_params, ("QAQT", 1, 2026, "QAQT"))
        self.assertIn("EXTRACT(QUARTER FROM ngay_ghi_nhan) = %s", error_query)
        self.assertEqual(error_params, ("QAQT", 1, 2026))

    def test_quarterly_tab_is_wired_to_api(self):
        with open("templates/view_kpi.html", encoding="utf-8") as template:
            html = template.read()

        self.assertIn('id="tab-summary-quarter"', html)
        self.assertIn('id="summaryQuarterTable"', html)
        self.assertIn("async function loadSummaryQuarter()", html)
        self.assertIn("/api/summary/quarterly?", html)


if __name__ == "__main__":
    unittest.main()
