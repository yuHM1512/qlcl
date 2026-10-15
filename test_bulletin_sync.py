import unittest
from datetime import date
from decimal import Decimal

from bulletin_sync import (
    is_done,
    parse_date,
    parse_decimal,
    parse_source_rows,
    previous_report_period,
    kpi_report_period,
)


class BulletinSyncTests(unittest.TestCase):
    def test_previous_report_period_is_monday_to_saturday(self):
        self.assertEqual(
            previous_report_period(date(2026, 10, 14)),
            (date(2026, 10, 5), date(2026, 10, 10)),
        )

    def test_kpi_period_always_uses_current_month(self):
        self.assertEqual(
            kpi_report_period(date(2026, 10, 5), date(2026, 10, 10)),
            (date(2026, 10, 1), date(2026, 10, 10)),
        )
        self.assertEqual(
            kpi_report_period(date(2026, 10, 12), date(2026, 10, 17)),
            (date(2026, 10, 1), date(2026, 10, 17)),
        )
        self.assertEqual(
            previous_report_period(date(2026, 10, 12)),
            (date(2026, 10, 5), date(2026, 10, 10)),
        )

    def test_parses_vietnamese_dates_and_percentages(self):
        self.assertEqual(parse_date("05/10/2026 08:30"), date(2026, 10, 5))
        self.assertEqual(parse_date("2026-10-05"), date(2026, 10, 5))
        self.assertEqual(parse_decimal("3,50%", percent=True), Decimal("3.50"))
        self.assertEqual(parse_decimal(0.03, percent=True), Decimal("3.00"))

    def test_hsx_code_is_classified_as_production_meeting(self):
        values = [
            ["ID", "No", "Ngày", "Đơn vị phát sinh", "what", "problem_status"],
            ["problem-29", "HSX0029.1", "06/10/2026", "P. QLCL", "Nút lưng lệch", "Đang thực hiện"],
        ]
        rows = parse_source_rows("problem_raw", values, "sheet-id", 123)
        self.assertEqual(rows[0]["source_type"], "production_meeting")
        self.assertEqual(rows[0]["source_no"], "HSX0029.1")

    def test_cap_final_keeps_row_target_and_source_status(self):
        values = [
            ["ID", "No", "Thời gian", "Xí nghiệp", "Loại hàng", "Tỉ lê Final", "Target", "CAP_status"],
            ["f-1", "F001", "08/10/2026", "XN2", "Thường", "4.5%", "3%", "Đang thực hiện"],
        ]
        row = parse_source_rows("final", values, "sheet-id", 10)[0]
        self.assertEqual(row["rate"], Decimal("4.5"))
        self.assertEqual(row["target"], Decimal("3"))
        self.assertEqual(row["source_status"], "Đang thực hiện")

    def test_done_status_normalization(self):
        self.assertTrue(is_done("Hoàn thành"))
        self.assertTrue(is_done("ĐÃ ĐÓNG"))
        self.assertFalse(is_done("Đang thực hiện"))


if __name__ == "__main__":
    unittest.main()
