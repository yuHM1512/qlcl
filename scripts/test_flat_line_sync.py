"""Regression tests for parsing flat-line production plans from Google Sheets."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from flat_line_sync import parse_flat_line_plans, parse_sheet_date, parse_unit_and_teams


HEADERS = [
    "STT", "Mã hàng", "Nhu cầu bắt đầu", "Sản lượng KH", "ĐMKT",
    "Phân loại ĐH", "Tổ", "LĐ biên chế", "Đơn giá", "Loại hàng",
    "Loại chuyền", "Ngày rải chuyền", "Khách hàng",
]


class FlatLineParserTests(unittest.TestCase):
    def test_parse_xn3_flat_line_row(self):
        values = [HEADERS, [
            "73", "339909", "PL-26-339909-AW26-004", "9608", "5.4",
            "Lặp lại", "U3 - L7", "60", "", "Yếm thể thao",
            "Chuyền bệt", "29/7/2026", "DECATHLON",
        ]]
        plans, warnings, matched = parse_flat_line_plans(values, "XN3", 3)
        self.assertEqual(warnings, [])
        self.assertEqual(matched, 1)
        self.assertEqual(plans, [{
            "source_record_id": "XN3:PL-26-339909-AW26-004",
            "ke_hoach": "PL-26-339909-AW26-004",
            "don_vi": "XN3",
            "bo_phan": ["Tổ 7"],
            "khach_hang": "DECATHLON",
            "ma_hang": "339909",
            "loai_hang": "Yếm thể thao",
            "ngay_rc": parse_sheet_date("29/7/2026"),
            "san_luong": 9608,
            "sheet_row": 3,
        }])

    def test_only_flat_line_rows_are_selected(self):
        values = [HEADERS,
            ["1", "A", "NC-1", "10", "", "", "U3-L1", "", "", "Áo vest", "Chuyền treo", "1/9/2026", "KH"],
            ["2", "B", "NC-2", "20", "", "", "U3-L2", "", "", "Quần tây", " Chuyền bệt ", "2/9/2026", "KH"],
        ]
        plans, warnings, matched = parse_flat_line_plans(values, "XN3", 3)
        self.assertEqual(warnings, [])
        self.assertEqual(matched, 1)
        self.assertEqual([plan["ke_hoach"] for plan in plans], ["NC-2"])

    def test_multiple_lines_and_wrong_unit(self):
        self.assertEqual(parse_unit_and_teams("U3 - L1+8"), (3, ["Tổ 1", "Tổ 8"]))
        self.assertEqual(parse_unit_and_teams("XN1-V1-L2"), (1, ["Tổ 2"]))
        values = [HEADERS, [
            "1", "A", "NC-1", "10", "", "", "U2-L1", "", "",
            "Áo vest", "Chuyền bệt", "1/9/2026", "KH",
        ]]
        plans, warnings, matched = parse_flat_line_plans(values, "XN3", 3)
        self.assertEqual(plans, [])
        self.assertEqual(matched, 1)
        self.assertIn("không thuộc U3", warnings[0])


if __name__ == "__main__":
    unittest.main()
