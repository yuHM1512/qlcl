"""Verify Co-2 visual versioning in the database and, optionally, the live app."""
from __future__ import annotations

import argparse
import json
import os
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_CURRENT = {
    "Áo đồng phục y tế": (4, 50),
    "Quần đồng phục y tế": (3, 37),
    "Quần thể thao": (11, 137),
    "Yếm thể thao": (12, 155),
    "Áo vest": (12, 132),
    "Áo khoác thể thao nhiều lớp": (17, 147),
    "Quần tây": (7, 84),
}


def fetch_json(base_url: str, path: str, params: dict) -> dict:
    url = f"{base_url}{path}?{urlencode(params)}"
    with urlopen(url, timeout=30) as response:
        return json.loads(response.read())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--effective-from", required=True, type=date.fromisoformat)
    parser.add_argument("--base-url", help="Also verify the running app, e.g. http://localhost:8008")
    args = parser.parse_args()
    before_date = args.effective_from - timedelta(days=1)
    load_dotenv(ROOT / ".env")

    product_ids: dict[str, int] = {}
    with psycopg2.connect(os.environ["DATABASE_URL"]) as conn:
        conn.set_session(readonly=True)
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT id, ten_loai FROM dm_loai_hang WHERE ten_loai = ANY(%s)",
                (list(EXPECTED_CURRENT),),
            )
            product_ids = {row["ten_loai"]: row["id"] for row in cur.fetchall()}
            if set(product_ids) != set(EXPECTED_CURRENT):
                raise AssertionError(f"Missing products: {set(EXPECTED_CURRENT) - set(product_ids)}")

            for name, expected in EXPECTED_CURRENT.items():
                cur.execute(
                    """
                    SELECT count(DISTINCT bp.id) AS blocks, count(ct.id) AS spots
                    FROM dm_visual_catalog vc
                    LEFT JOIN dm_bo_phan bp ON bp.visual_catalog_id=vc.id
                    LEFT JOIN dm_chi_tiet ct ON ct.bo_phan_id=bp.id
                    WHERE vc.loai_hang_id=%s
                      AND vc.effective_from <= %s
                      AND (vc.effective_to IS NULL OR vc.effective_to >= %s)
                    """,
                    (product_ids[name], args.effective_from, args.effective_from),
                )
                row = cur.fetchone()
                actual = (row["blocks"], row["spots"])
                if actual != expected:
                    raise AssertionError(f"{name}: {actual}, expected {expected}")

            cur.execute(
                """
                SELECT count(DISTINCT bp.id) AS blocks
                FROM dm_visual_catalog vc
                LEFT JOIN dm_bo_phan bp ON bp.visual_catalog_id=vc.id
                WHERE vc.loai_hang_id=%s
                  AND vc.effective_from <= %s
                  AND (vc.effective_to IS NULL OR vc.effective_to >= %s)
                """,
                (product_ids["Yếm thể thao"], before_date, before_date),
            )
            if cur.fetchone()["blocks"] != 10:
                raise AssertionError("The historical Yếm catalog must keep its 10 old blocks")

            cur.execute(
                """
                SELECT count(*) AS broken
                FROM qc_defect d
                LEFT JOIN dm_bo_phan bp ON bp.id=d.bo_phan_id
                LEFT JOIN dm_chi_tiet ct ON ct.id=d.chi_tiet_id
                WHERE (d.bo_phan_id IS NOT NULL AND bp.id IS NULL)
                   OR (d.chi_tiet_id IS NOT NULL AND ct.id IS NULL)
                """
            )
            if cur.fetchone()["broken"]:
                raise AssertionError("Broken QC defect references found")

    image_urls: set[str] = set()
    if args.base_url:
        base_url = args.base_url.rstrip("/")
        for name, (expected_blocks, expected_spots) in EXPECTED_CURRENT.items():
            data = fetch_json(base_url, "/api/qc/visual-picker", {
                "loai_hang_id": product_ids[name], "date": args.effective_from.isoformat()
            })
            blocks = [block for group in data["nhoms"] for block in group["khoi"]]
            actual = (len(blocks), sum(len(block["hotspots"]) for block in blocks))
            if not data["has_visual_picker"] or actual != (expected_blocks, expected_spots):
                raise AssertionError(f"Live API {name}: {actual}")
            image_urls.update(block["image_png"] for block in blocks if block["image_png"])

        old_picker = fetch_json(base_url, "/api/qc/visual-picker", {
            "loai_hang_id": product_ids["Yếm thể thao"], "date": before_date.isoformat()
        })
        old_blocks = fetch_json(base_url, "/api/dm/bo-phan", {
            "loai_hang_id": product_ids["Yếm thể thao"], "date": before_date.isoformat()
        })
        if old_picker["has_visual_picker"] or len(old_blocks["rows"]) != 10:
            raise AssertionError("Live API did not select the historical Yếm catalog")

        for image_url in image_urls:
            with urlopen(base_url + image_url, timeout=30) as response:
                if not response.read(8).startswith(b"\x89PNG"):
                    raise AssertionError(f"Invalid image: {image_url}")

    print("PASS database: 7 products, effective-date boundary, QC references")
    if args.base_url:
        print(f"PASS app: {args.base_url.rstrip('/')}, {len(image_urls)} PNG images")


if __name__ == "__main__":
    main()
