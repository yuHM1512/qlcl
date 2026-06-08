"""Wipe old Áo vest bo_phan/chi_tiet and import from aovest_visual_picker.json.

Steps (all inside a single transaction):
  1. SET NULL on qc_defect.bo_phan_id / chi_tiet_id where they reference Áo vest data.
  2. DELETE FROM dm_bo_phan WHERE loai_hang_id = (Áo vest)  -- cascades to dm_chi_tiet.
  3. INSERT new bo_phan + chi_tiet from JSON.

Images are copied to IMAGES_STORAGE_DIR/positions/aovest/<nhom>/...
Stored DB paths are relative: "positions/aovest/<nhom>/<file>.png" — UI prepends "/api/images/".
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

DATABASE_URL = os.getenv("DATABASE_URL")
IMAGES_STORAGE_DIR = Path(os.getenv("IMAGES_STORAGE_DIR") or "images")

LOAI_HANG_NAME = "Áo vest"

SRC_JSON = Path(__file__).resolve().parent / "out" / "aovest_visual_picker.json"
SRC_IMG_BASE = Path(__file__).resolve().parent / "out"


def reset_serial_sequence(cur, table_name: str, id_column: str = "id") -> None:
    cur.execute("SELECT pg_get_serial_sequence(%s, %s) AS seq_name", (table_name, id_column))
    row = cur.fetchone()
    seq_name = row["seq_name"] if row else None
    if not seq_name:
        return
    cur.execute(
        f"""
        SELECT setval(
            %s,
            COALESCE((SELECT MAX({id_column}) FROM {table_name}), 0) + 1,
            false
        )
        """,
        (seq_name,),
    )


def main() -> None:
    if not SRC_JSON.exists():
        print(f"Missing {SRC_JSON} — run parse_aovest_excel.py first", file=sys.stderr)
        sys.exit(1)

    data = json.loads(SRC_JSON.read_text(encoding="utf-8"))

    # Copy images from scripts/out/positions/... to IMAGES_STORAGE_DIR/positions/...
    src_positions = SRC_IMG_BASE / "positions"
    dst_positions = IMAGES_STORAGE_DIR / "positions"
    if dst_positions.exists():
        shutil.rmtree(dst_positions / "aovest", ignore_errors=True)
    dst_positions.mkdir(parents=True, exist_ok=True)
    aovest_src = src_positions / "aovest"
    aovest_dst = dst_positions / "aovest"
    shutil.copytree(aovest_src, aovest_dst)
    print(f"Copied images: {aovest_src} -> {aovest_dst}")

    conn = psycopg2.connect(DATABASE_URL)
    conn.autocommit = False
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            # 1. Get loai_hang id
            cur.execute("SELECT id FROM public.dm_loai_hang WHERE ten_loai = %s", (LOAI_HANG_NAME,))
            row = cur.fetchone()
            if not row:
                raise RuntimeError(f"Loại hàng {LOAI_HANG_NAME!r} không tồn tại")
            loai_hang_id = row["id"]
            print(f"loai_hang_id = {loai_hang_id}")

            # 2. SET NULL on qc_defect FKs that point into Áo vest bo_phan/chi_tiet
            cur.execute(
                """
                SELECT id FROM public.dm_bo_phan WHERE loai_hang_id = %s
                """,
                (loai_hang_id,),
            )
            old_bp_ids = [r["id"] for r in cur.fetchall()]
            if old_bp_ids:
                cur.execute(
                    """
                    UPDATE public.qc_defect
                       SET bo_phan_id = NULL, chi_tiet_id = NULL
                     WHERE bo_phan_id = ANY(%s) OR chi_tiet_id IN (
                         SELECT id FROM public.dm_chi_tiet WHERE bo_phan_id = ANY(%s)
                     )
                    """,
                    (old_bp_ids, old_bp_ids),
                )
                print(f"qc_defect rows neutralized (bo_phan_id/chi_tiet_id -> NULL): {cur.rowcount}")

                # 3. Delete old bo_phan (cascade to chi_tiet)
                cur.execute(
                    "DELETE FROM public.dm_bo_phan WHERE id = ANY(%s)",
                    (old_bp_ids,),
                )
                print(f"Deleted dm_bo_phan (cascade chi_tiet): {cur.rowcount} bo_phan rows")

            reset_serial_sequence(cur, "public.dm_bo_phan")
            reset_serial_sequence(cur, "public.dm_chi_tiet")

            # 4. Insert new bo_phan + chi_tiet from JSON
            sort_counter = 0
            total_bp = 0
            total_ct = 0
            for nhom_entry in data["nhoms"]:
                nhom_key = nhom_entry["nhom"]
                for khoi in nhom_entry["khoi"]:
                    sort_counter += 1
                    cur.execute(
                        """
                        INSERT INTO public.dm_bo_phan
                            (loai_hang_id, ten_bo_phan, nhom, image_png, image_svg, sort_order)
                        VALUES (%s, %s, %s, %s, %s, %s)
                        RETURNING id
                        """,
                        (
                            loai_hang_id,
                            khoi["ten_khoi"],
                            nhom_key,
                            khoi.get("image_png"),
                            khoi.get("image_svg"),
                            sort_counter,
                        ),
                    )
                    bp_id = cur.fetchone()["id"]
                    total_bp += 1

                    for h in khoi["hotspots"]:
                        cur.execute(
                            """
                            INSERT INTO public.dm_chi_tiet
                                (bo_phan_id, ten_chi_tiet, ma_vi_tri, x_pct, y_pct, w_pct, h_pct, rotation)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                            """,
                            (
                                bp_id,
                                h["label"],
                                h["ma"],
                                h["x_pct"],
                                h["y_pct"],
                                h["w_pct"],
                                h["h_pct"],
                                h["rotation"],
                            ),
                        )
                        total_ct += 1

            print(f"Inserted: {total_bp} bo_phan, {total_ct} chi_tiet")

        conn.commit()
        print("✓ Committed.")
    except Exception:
        conn.rollback()
        print("✗ Rolled back due to error.", file=sys.stderr)
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()
