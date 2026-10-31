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

    def test_accepts_both_spellings_of_the_action_columns(self):
        # prepare_hdkp_data_for_pdf (Final nội bộ, HĐKP thường) spells these
        # with đ; prepare_qc_hdkp_data_for_pdf (endline) spells them with d.
        for key_action, key_prevent in (
            ("a_hdkp_tuc_thoi_1", "a_hd_phong_ngua_1"),
            ("a_hđkp_tuc_thoi_1", "a_hđ_phong_ngua_1"),
        ):
            data = {"ma_nv": "X", "ngay_ghi_nhan": "2026-01-01",
                    "a_root_cause_1": "Nguyên nhân",
                    key_action: "Kiểm tra lại toàn bộ lô hàng",
                    key_prevent: "Quán triệt công nhân kiểm tra trước khi chuyển"}
            _, _, text = _render(data)
            self.assertIn("Kiểm tra lại toàn bộ lô hàng", text, key_action)
            self.assertIn("Quán triệt công nhân kiểm tra trước khi chuyển",
                          text, key_prevent)

    def test_blank_form_still_renders(self):
        _, doc, text = _render({"ma_nv": "X", "ngay_ghi_nhan": "2026-01-01"})
        self.assertGreaterEqual(doc.page_count, 1)
        self.assertIn("I. Mô tả vấn đề", text)

    def test_served_pdf_must_be_revalidated(self):
        # the file behind a given URL is rebuilt whenever the HĐKP changes,
        # so neither the browser nor Cloudflare may hand out a stale copy
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        import main

        served = os.path.join(main.PDF_STORAGE_DIR, "_cache_header_check.pdf")
        with open(served, "wb") as handle:
            handle.write(b"%PDF-1.4\n%check\n")
        try:
            app = FastAPI()
            app.mount("/api/pdf",
                      main.RevalidatedStaticFiles(directory=main.PDF_STORAGE_DIR),
                      name="pdf")
            response = TestClient(app).get("/api/pdf/_cache_header_check.pdf")
            self.assertEqual(response.status_code, 200)
            self.assertIn("no-cache", response.headers.get("cache-control", ""))
            self.assertTrue(response.headers.get("etag"))
        finally:
            os.remove(served)

    def test_pdf_generation_does_not_need_excel(self):
        source = Path("main.py").read_text(encoding="utf-8-sig")
        start = source.index("def create_hdkp_pdf")
        body = source[start:source.index("\ndef ", start + 10)]
        self.assertIn("render_hdkp_pdf", body)
        self.assertNotIn("fill_excel_template", body)
        self.assertNotIn("excel_to_pdf", body)


if __name__ == "__main__":
    unittest.main()
