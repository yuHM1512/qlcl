"""Dựng lại các PDF HĐKP đã sinh ra bằng đường Excel cũ.

Những file tạo trước khi chuyển sang reportlab bị Excel cắt mất phần chữ không
vừa chiều cao dòng cố định của biểu mẫu. Nội dung vẫn nằm nguyên trong CSDL nên
chỉ cần dựng lại file từ đó.

    python scripts/regenerate_hdkp_pdfs.py               # chỉ liệt kê, không ghi
    python scripts/regenerate_hdkp_pdfs.py --apply       # ghi đè file PDF
    python scripts/regenerate_hdkp_pdfs.py --apply --flow final

Chạy từ thư mục gốc của dự án.
"""
import argparse
import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Console Windows mặc định là cp1252, in tiếng Việt ra sẽ vỡ
for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8")
    except Exception:
        pass

import psycopg2.extras  # noqa: E402

import main  # noqa: E402

FINAL_TABLES = ("qa_final_hdkp_mota", "qa_final_hdkp_kehoach", "qa_final_hdkp_chitiet")


class Job:
    """Một PDF cần dựng lại, kèm cách ghi URL mới trở lại CSDL."""

    def __init__(self, flow, label, old_url, build_data, store_sql, store_key):
        self.flow = flow
        self.label = label
        self.old_url = old_url
        self.build_data = build_data
        self.store_sql = store_sql
        self.store_key = store_key


def _collect_final(cur):
    cur.execute("""
        SELECT h.id AS hdkp_id, h.inspection_id, h.pdf_url, h.completed_by, h.created_by,
               i.po_code, i.qa_check_date
        FROM public.qa_final_hdkp h
        JOIN public.qa_final_inspection i ON i.id = h.inspection_id
        WHERE h.pdf_url IS NOT NULL
        ORDER BY h.id
    """)
    jobs = []
    for row in cur.fetchall():
        hdkp_id = row["hdkp_id"]
        inspection_id = row["inspection_id"]

        def build(hdkp_id=hdkp_id, inspection_id=inspection_id, row=row):
            with main.get_db_connection() as conn:
                with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as c:
                    c.execute("SELECT * FROM public.qa_final_inspection WHERE id = %s",
                              (inspection_id,))
                    inspection = c.fetchone()
            source = dict(inspection)
            source["ma_nv"] = row["completed_by"] or row["created_by"]
            source["ngay_ghi_nhan"] = inspection.get("qa_check_date")
            data = main.prepare_hdkp_data_for_pdf(hdkp_id, source, FINAL_TABLES, "hdkp_id")
            return inspection_id, data

        jobs.append(Job(
            "final", f"Final nội bộ · PO {row['po_code']} · {row['qa_check_date']}",
            row["pdf_url"], build,
            "UPDATE public.qa_final_hdkp SET pdf_url = %s WHERE id = %s", hdkp_id))
    return jobs


def _collect_error(cur):
    cur.execute("""
        SELECT id, cap_form, ngay_ghi_nhan, ma_nv
        FROM public.input_error
        WHERE cap_form IS NOT NULL
        ORDER BY id
    """)
    jobs = []
    for row in cur.fetchall():
        error_id = row["id"]

        def build(error_id=error_id):
            with main.get_db_connection() as conn:
                with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as c:
                    c.execute("SELECT * FROM public.input_error WHERE id = %s", (error_id,))
                    error_row = c.fetchone()
            return error_id, main.prepare_hdkp_data_for_pdf(error_id, error_row)

        jobs.append(Job(
            "error", f"HĐKP lỗi #{error_id} · {row['ngay_ghi_nhan']} · {row['ma_nv']}",
            row["cap_form"], build,
            "UPDATE public.input_error SET cap_form = %s WHERE id = %s", error_id))
    return jobs


def _collect_endline(cur):
    cur.execute("""
        SELECT id, hdkp_pdf, date
        FROM public.qc_error_dps
        WHERE hdkp_pdf IS NOT NULL
        ORDER BY id
    """)
    jobs = []
    for row in cur.fetchall():
        dps_id = row["id"]

        def build(dps_id=dps_id):
            with main.get_db_connection() as conn:
                with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as c:
                    c.execute("SELECT * FROM public.qc_error_dps WHERE id = %s", (dps_id,))
                    dps_row = c.fetchone()
            return dps_id, main.prepare_qc_hdkp_data_for_pdf(dps_id, dps_row)

        jobs.append(Job(
            "endline", f"Endline #{dps_id} · {row['date']}",
            row["hdkp_pdf"], build,
            "UPDATE public.qc_error_dps SET hdkp_pdf = %s WHERE id = %s", dps_id))
    return jobs


COLLECTORS = {"final": _collect_final, "error": _collect_error, "endline": _collect_endline}


def collect(flow):
    wanted = COLLECTORS if flow == "all" else {flow: COLLECTORS[flow]}
    jobs = []
    with main.get_db_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            for name, collector in wanted.items():
                try:
                    jobs.extend(collector(cur))
                except Exception as exc:
                    print(f"  ! Không đọc được luồng {name}: {exc}")
    return jobs


def run(jobs, apply_changes):
    done = failed = relinked = 0
    for job in jobs:
        try:
            record_id, data = job.build_data()
            if not apply_changes:
                print(f"  [sẽ dựng lại] {job.label}  ->  {job.old_url}")
                done += 1
                continue
            new_url = main.create_hdkp_pdf(record_id, data)
            note = ""
            if new_url != job.old_url:
                with main.get_db_connection() as conn:
                    with conn.cursor() as cur:
                        cur.execute(job.store_sql, (new_url, job.store_key))
                        conn.commit()
                relinked += 1
                note = f"  (đổi tên file, đã cập nhật CSDL: {job.old_url} -> {new_url})"
            print(f"  [xong] {job.label}{note}")
            done += 1
        except Exception as exc:
            failed += 1
            print(f"  [LỖI] {job.label}: {exc}")
            traceback.print_exc(limit=2)
    return done, failed, relinked


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true",
                        help="thực sự ghi đè file PDF; mặc định chỉ liệt kê")
    parser.add_argument("--flow", choices=("all", "final", "error", "endline"),
                        default="all", help="chỉ xử lý một luồng")
    return parser.parse_args()


def cli():
    args = parse_args()
    print(f"Thư mục PDF: {main.PDF_STORAGE_DIR}")
    jobs = collect(args.flow)
    if not jobs:
        print("Không có PDF nào cần dựng lại.")
        return 0

    print(f"Tìm thấy {len(jobs)} file PDF HĐKP:")
    done, failed, relinked = run(jobs, args.apply)

    if args.apply:
        print(f"\nĐã dựng lại {done}, lỗi {failed}, đổi tên {relinked}.")
    else:
        print(f"\n{done} file sẽ được dựng lại (chưa ghi gì).")
        print("Chạy lại với --apply để thực hiện.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(cli())
