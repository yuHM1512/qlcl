"""Import visual_picker.json into DB and copy images to IMAGES_STORAGE_DIR.

Generic version of the old `import_aovest_to_db.py`. Supports multiple loại hàng
in a single JSON (produced by parse_visual_picker_excel.py).

For each loại hàng (slug) found in JSON:
  1. Look up dm_loai_hang by SLUG_TO_TEN_LOAI[slug]. INSERT if missing.
  2. SET NULL on qc_defect.bo_phan_id / chi_tiet_id where they reference this loại hàng.
  3. DELETE FROM dm_bo_phan WHERE loai_hang_id = ... (cascades to dm_chi_tiet).
  4. INSERT new bo_phan + chi_tiet from JSON, image paths stored as relative
     "positions/<slug>/<nhom>/<file>.png" — UI prepends "/api/images/".
  5. Copy scripts/out/positions/<slug>/ -> IMAGES_STORAGE_DIR/positions/<slug>/.

Everything runs inside a single transaction.
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

# Maps loại hàng slug (used in image paths and JSON keys) -> dm_loai_hang.ten_loai.
# Extend this when adding a new loại hàng with visual picker.
SLUG_TO_TEN_LOAI: dict[str, str] = {
    "aovest":  "Áo vest",
    "quantay": "Quần tây",
}

SRC_JSON = Path(__file__).resolve().parent / "out" / "visual_picker.json"
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


def ensure_loai_hang(cur, ten_loai: str) -> int:
    """Look up or create dm_loai_hang row. Returns id."""
    cur.execute("SELECT id FROM public.dm_loai_hang WHERE ten_loai = %s", (ten_loai,))
    row = cur.fetchone()
    if row:
        return row["id"]
    cur.execute(
        "INSERT INTO public.dm_loai_hang (ten_loai) VALUES (%s) RETURNING id",
        (ten_loai,),
    )
    new_id = cur.fetchone()["id"]
    print(f"  ↳ INSERTED dm_loai_hang ten_loai={ten_loai!r} id={new_id}")
    return new_id


def wipe_old_bo_phan(cur, loai_hang_id: int) -> None:
    """SET NULL on qc_defect FKs that point into this loại hàng, then DELETE bo_phan."""
    cur.execute(
        "SELECT id FROM public.dm_bo_phan WHERE loai_hang_id = %s",
        (loai_hang_id,),
    )
    old_bp_ids = [r["id"] for r in cur.fetchall()]
    if not old_bp_ids:
        return
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
    print(f"  qc_defect rows neutralized (bo_phan_id/chi_tiet_id -> NULL): {cur.rowcount}")
    cur.execute("DELETE FROM public.dm_bo_phan WHERE id = ANY(%s)", (old_bp_ids,))
    print(f"  Deleted dm_bo_phan (cascade chi_tiet): {cur.rowcount} bo_phan rows")


def insert_loai_hang_data(cur, loai_hang_id: int, nhoms: list[dict]) -> tuple[int, int]:
    """Insert dm_bo_phan + dm_chi_tiet for one loại hàng. Returns (n_bp, n_ct)."""
    sort_counter = 0
    total_bp = 0
    total_ct = 0
    for nhom_entry in nhoms:
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
    return total_bp, total_ct


def copy_images(slug: str) -> None:
    """Copy scripts/out/positions/<slug> -> IMAGES_STORAGE_DIR/positions/<slug>.

    Wipes the destination slug folder first so removed khois don't linger.
    """
    src = SRC_IMG_BASE / "positions" / slug
    if not src.exists():
        print(f"  ⚠ No images found at {src}, skipping copy")
        return
    dst_parent = IMAGES_STORAGE_DIR / "positions"
    dst_parent.mkdir(parents=True, exist_ok=True)
    dst = dst_parent / slug
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)
    print(f"  Copied images: {src} -> {dst}")


def main() -> None:
    if not SRC_JSON.exists():
        print(f"Missing {SRC_JSON} — run parse_visual_picker_excel.py first", file=sys.stderr)
        sys.exit(1)

    data = json.loads(SRC_JSON.read_text(encoding="utf-8"))
    loai_hangs = data.get("loai_hangs") or {}
    if not loai_hangs:
        print("No loại hàng found in JSON.", file=sys.stderr)
        sys.exit(1)

    # Validate slugs up-front so we fail fast before any DB writes.
    unknown = [s for s in loai_hangs.keys() if s not in SLUG_TO_TEN_LOAI]
    if unknown:
        print(
            f"✗ Unknown slugs in JSON: {unknown}. "
            f"Add them to SLUG_TO_TEN_LOAI in this script.",
            file=sys.stderr,
        )
        sys.exit(1)

    conn = psycopg2.connect(DATABASE_URL)
    conn.autocommit = False
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            # Drop legacy UNIQUE(bo_phan_id, ten_chi_tiet) — visual picker uses ma_vi_tri
            # as the real per-bo_phan key. Idempotent.
            cur.execute(
                "ALTER TABLE public.dm_chi_tiet "
                "DROP CONSTRAINT IF EXISTS dm_chi_tiet_bo_phan_id_ten_chi_tiet_key"
            )

            for slug, entry in loai_hangs.items():
                ten_loai = SLUG_TO_TEN_LOAI[slug]
                print(f"\n=== {slug} ({ten_loai}) ===")
                loai_hang_id = ensure_loai_hang(cur, ten_loai)
                print(f"  loai_hang_id = {loai_hang_id}")
                wipe_old_bo_phan(cur, loai_hang_id)
                reset_serial_sequence(cur, "public.dm_bo_phan")
                reset_serial_sequence(cur, "public.dm_chi_tiet")
                n_bp, n_ct = insert_loai_hang_data(cur, loai_hang_id, entry["nhoms"])
                print(f"  Inserted: {n_bp} bo_phan, {n_ct} chi_tiet")
                copy_images(slug)

        conn.commit()
        print("\n✓ Committed.")
    except Exception:
        conn.rollback()
        print("\n✗ Rolled back due to error.", file=sys.stderr)
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()
