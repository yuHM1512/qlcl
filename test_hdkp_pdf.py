import os
import tempfile
import unittest
from pathlib import Path

import pymupdf

from hdkp_pdf import render_hdkp_pdf

LONG_CAUSE = ("-Do máy móc hỏng đến thời điểm, chân vịt mòn dẫn đến vắt sổ bỏ mũi "
              "trên sản phẩm, cần thay thế linh kiện và hiệu chỉnh lại thiết bị")
LONG_ACTION = ("-Tổ trưởng họp quán triệt CN thực hiện việc may xong kiểm tra trước "
               "khi chuyển sang công đoạn tiếp theo, ghi nhận vào sổ theo dõi")

SAMPLE = {
    "ma_nv": "V0866",
    "ngay_ghi_nhan": "2026-09-30",
    "created_at": "30/09/2026",
    "ho_ten": "Nguyễn Thị Tuyết",
    "vd_what": "Vắt sổ bỏ mũi trên sản phẩm",
    "vd_how": "Kiểm tra ngẫu nhiên 13 mẫu trong lô 208 chiếc",
    "a_root_cause_1": LONG_CAUSE,
    "a_hd_phong_ngua_1": LONG_ACTION,
    "a_tg_theo_doi_1": "1 tháng",
    "b_root_cause_1": "- QA không kiểm soát xuất hàng đạt của QC thường xuyên",
    "cong_viec_1": "Kiểm tra toàn bộ lô hàng tồn kho",
    "ket_qua_dat_1": "x",
}


def _render(data):
    out = os.path.join(tempfile.mkdtemp(), "hdkp.pdf")
    render_hdkp_pdf(data, out, logo_path=str(Path("templates/Logo.png").resolve()))
    doc = pymupdf.open(out)
    text = " ".join(" ".join(page.get_text().split()) for page in doc)
    return out, doc, text


class HdkpPdfTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.path, cls.doc, cls.text = _render(SAMPLE)

    def test_pdf_is_written(self):
        self.assertGreater(os.path.getsize(self.path), 10000)
        self.assertGreaterEqual(self.doc.page_count, 1)

    def test_long_cell_text_is_not_clipped(self):
        # the tail of each long string is what the Excel export used to cut off
        for needle in ("cần thay thế linh kiện và hiệu chỉnh lại thiết bị",
                       "ghi nhận vào sổ theo dõi"):
            self.assertIn(" ".join(needle.split()), self.text)

    def test_form_headings_match_the_iso_template(self):
        for needle in ("BÁO CÁO HÀNH ĐỘNG", "Kí mã hiệu: Hachiba-QT-10.1/BM1",
                       "Lần soát xét 01/02", "Ngày hiệu lực: 10/6/2022",
                       "I. Mô tả vấn đề", "II. Kế hoạch khắc phục, phòng ngừa",
                       "III: Chi tiết kế hoạch khắc phục phòng ngừa (To Do List)",
                       "A/ Tại sao vấn đề này xảy ra",
                       "B/ Tại sao vấn đề này không được phát hiện từ trước",
                       "Thời gian thực hiện (từ…đến)", "Võ Thị Tuyết An"):
            self.assertIn(" ".join(needle.split()), self.text)

    def test_filled_values_reach_the_pdf(self):
        for needle in ("Vắt sổ bỏ mũi trên sản phẩm", "Nguyễn Thị Tuyết",
                       "30/09/2026", "Kiểm tra toàn bộ lô hàng tồn kho"):
            self.assertIn(" ".join(needle.split()), self.text)

    def test_blank_form_still_renders(self):
        _, doc, text = _render({"ma_nv": "X", "ngay_ghi_nhan": "2026-01-01"})
        self.assertGreaterEqual(doc.page_count, 1)
        self.assertIn("I. Mô tả vấn đề", text)

    def test_pdf_generation_does_not_need_excel(self):
        source = Path("main.py").read_text(encoding="utf-8-sig")
        start = source.index("def create_hdkp_pdf")
        body = source[start:source.index("\ndef ", start + 10)]
        self.assertIn("render_hdkp_pdf", body)
        self.assertNotIn("fill_excel_template", body)
        self.assertNotIn("excel_to_pdf", body)


if __name__ == "__main__":
    unittest.main()
