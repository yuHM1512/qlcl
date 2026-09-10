"""Export the reviewed Co-2 picker rows as a portable, ID-free deploy bundle.

This maintainer tool reads the local database and runtime image store. The
generated JSON and image assets are committed; production never needs Co-2.pdf.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
from pathlib import Path

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
BUNDLE_PATH = ROOT / "scripts/data/co2_visual_catalog.json"
ASSET_ROOT = ROOT / "scripts/assets/visual_picker"
PRODUCTS = [
    "Áo đồng phục y tế",
    "Quần đồng phục y tế",
    "Quần thể thao",
    "Yếm thể thao",
]
EXPECTED = {
    "Áo đồng phục y tế": (4, 50),
    "Quần đồng phục y tế": (3, 37),
    "Quần thể thao": (11, 137),
    "Yếm thể thao": (12, 155),
}


def main() -> None:
    load_dotenv(ROOT / ".env")
    image_store = Path(os.environ["IMAGES_STORAGE_DIR"])
    bundle = {"format_version": 1, "source_file": "Co-2.pdf", "products": []}
    with psycopg2.connect(os.environ["DATABASE_URL"]) as conn:
        conn.set_session(readonly=True)
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            for product_name in PRODUCTS:
                cur.execute(
                    "SELECT id, id_type FROM dm_loai_hang WHERE ten_loai = %s",
                    (product_name,),
                )
                product_rows = cur.fetchall()
                if len(product_rows) != 1:
                    raise ValueError(f"Expected one local product: {product_name}")
                product = product_rows[0]
                cur.execute(
                    """
                    SELECT id, ten_bo_phan, nhom, image_png, image_svg, sort_order
                    FROM dm_bo_phan
                    WHERE loai_hang_id = %s
                      AND nhom IS NOT NULL
                      AND image_png IS NOT NULL
                    ORDER BY sort_order, id
                    """,
                    (product["id"],),
                )
                block_rows = cur.fetchall()
                blocks = []
                spot_count = 0
                for block in block_rows:
                    cur.execute(
                        """
                        SELECT ma_vi_tri, ten_chi_tiet, x_pct, y_pct,
                               w_pct, h_pct, rotation
                        FROM dm_chi_tiet
                        WHERE bo_phan_id = %s
                        ORDER BY id
                        """,
                        (block["id"],),
                    )
                    spots = []
                    for spot in cur.fetchall():
                        spots.append({
                            "code": spot["ma_vi_tri"],
                            "label": spot["ten_chi_tiet"],
                            "x_pct": float(spot["x_pct"]),
                            "y_pct": float(spot["y_pct"]),
                            "w_pct": float(spot["w_pct"]),
                            "h_pct": float(spot["h_pct"]),
                            "rotation": float(spot["rotation"] or 0),
                        })
                    spot_count += len(spots)
                    image_path = block["image_png"]
                    source = image_store / image_path
                    if not source.is_file():
                        raise FileNotFoundError(source)
                    content = source.read_bytes()
                    target = ASSET_ROOT / image_path
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(source, target)
                    blocks.append({
                        "name": block["ten_bo_phan"],
                        "group": block["nhom"],
                        "sort_order": block["sort_order"],
                        "image_png": image_path,
                        "image_sha256": hashlib.sha256(content).hexdigest(),
                        "image_svg": block["image_svg"],
                        "hotspots": spots,
                    })
                expected = EXPECTED[product_name]
                actual = (len(blocks), spot_count)
                if actual != expected:
                    raise ValueError(f"Unexpected {product_name} counts: {actual}, expected {expected}")
                bundle["products"].append({
                    "name": product_name,
                    "id_type": product["id_type"],
                    "version_code": "co2-v1",
                    "version_name": "Visual Co-2 lần 1",
                    "blocks": blocks,
                })
    BUNDLE_PATH.parent.mkdir(parents=True, exist_ok=True)
    BUNDLE_PATH.write_text(json.dumps(bundle, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {BUNDLE_PATH}: 4 products, 30 blocks, 379 hotspots")
    print(f"Copied deploy assets to {ASSET_ROOT}")


if __name__ == "__main__":
    main()
