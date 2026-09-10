"""Safely deploy the portable Co-2 visual catalog bundle.

Dry-run is the default. Pass --apply only after reviewing the preflight output.
Existing QC defects and the old Yếm catalog are never deleted or reassigned.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
BUNDLE_PATH = ROOT / "scripts/data/co2_visual_catalog.json"
ASSET_ROOT = ROOT / "scripts/assets/visual_picker"
BACKUP_ROOT = ROOT / "scripts/out/deploy_backups"
UNCHANGED_PRODUCTS = ["Áo vest", "Áo khoác thể thao nhiều lớp", "Quần tây"]
YEM = "Yếm thể thao"


def json_default(value):
    if isinstance(value, (date, datetime, Decimal)):
        return str(value)
    raise TypeError(type(value).__name__)


def reset_sequence(cur, table: str) -> None:
    cur.execute("SELECT pg_get_serial_sequence(%s, 'id') AS seq", (f"public.{table}",))
    seq = cur.fetchone()["seq"]
    if seq:
        cur.execute(f"SELECT setval(%s, COALESCE((SELECT MAX(id) FROM public.{table}), 0) + 1, false)", (seq,))


def one(cur, sql: str, params: tuple, description: str):
    cur.execute(sql, params)
    rows = cur.fetchall()
    if len(rows) != 1:
        raise ValueError(f"Expected one {description}, found {len(rows)}")
    return rows[0]


def ensure_product(cur, name: str, id_type):
    cur.execute("SELECT id, id_type FROM dm_loai_hang WHERE ten_loai = %s", (name,))
    rows = cur.fetchall()
    if len(rows) > 1:
        raise ValueError(f"Duplicate product: {name}")
    if rows:
        return rows[0]["id"], False
    cur.execute(
        "INSERT INTO dm_loai_hang (ten_loai, id_type) VALUES (%s, %s) RETURNING id",
        (name, id_type),
    )
    return cur.fetchone()["id"], True


def ensure_catalog(cur, product_id: int, code: str, name: str,
                   effective_from: date, effective_to: date | None, source_file: str | None):
    cur.execute(
        "SELECT * FROM dm_visual_catalog WHERE loai_hang_id=%s AND version_code=%s",
        (product_id, code),
    )
    rows = cur.fetchall()
    if len(rows) > 1:
        raise ValueError(f"Duplicate visual version: product={product_id}, code={code}")
    if rows:
        row = rows[0]
        if row["effective_from"] != effective_from or row["effective_to"] != effective_to:
            raise ValueError(
                f"Visual version {code} already has range "
                f"{row['effective_from']}..{row['effective_to']}; requested "
                f"{effective_from}..{effective_to}"
            )
        return row["id"], False
    cur.execute(
        """
        INSERT INTO dm_visual_catalog
            (loai_hang_id, version_code, name, effective_from, effective_to, source_file)
        VALUES (%s,%s,%s,%s,%s,%s)
        RETURNING id
        """,
        (product_id, code, name, effective_from, effective_to, source_file),
    )
    return cur.fetchone()["id"], True


def validate_bundle(bundle: dict) -> None:
    expected = {
        "Áo đồng phục y tế": (4, 50),
        "Quần đồng phục y tế": (3, 37),
        "Quần thể thao": (11, 137),
        "Yếm thể thao": (12, 155),
    }
    actual_names = {p["name"] for p in bundle["products"]}
    if actual_names != set(expected):
        raise ValueError(f"Unexpected bundle products: {sorted(actual_names)}")
    for product in bundle["products"]:
        blocks = product["blocks"]
        spots = sum(len(b["hotspots"]) for b in blocks)
        if (len(blocks), spots) != expected[product["name"]]:
            raise ValueError(f"Unexpected counts for {product['name']}")
        block_keys = [(b["group"], b["name"]) for b in blocks]
        if len(block_keys) != len(set(block_keys)):
            raise ValueError(f"Duplicate blocks in bundle: {product['name']}")
        for block in blocks:
            codes = [h["code"] for h in block["hotspots"]]
            if not all(codes) or len(codes) != len(set(codes)):
                raise ValueError(f"Missing/duplicate code: {product['name']} / {block['name']}")
            source = ASSET_ROOT / block["image_png"]
            if not source.is_file():
                raise FileNotFoundError(source)
            digest = hashlib.sha256(source.read_bytes()).hexdigest()
            if digest != block["image_sha256"]:
                raise ValueError(f"Image checksum mismatch: {source}")


def snapshot(cur, product_names: list[str]) -> dict:
    cur.execute(
        "SELECT * FROM dm_loai_hang WHERE ten_loai = ANY(%s) ORDER BY id",
        (product_names,),
    )
    products = [dict(r) for r in cur.fetchall()]
    for product in products:
        cur.execute("SELECT * FROM dm_visual_catalog WHERE loai_hang_id=%s ORDER BY id", (product["id"],))
        product["visual_catalogs"] = [dict(r) for r in cur.fetchall()]
        cur.execute("SELECT * FROM dm_bo_phan WHERE loai_hang_id=%s ORDER BY id", (product["id"],))
        product["blocks"] = [dict(r) for r in cur.fetchall()]
        for block in product["blocks"]:
            cur.execute("SELECT * FROM dm_chi_tiet WHERE bo_phan_id=%s ORDER BY id", (block["id"],))
            block["hotspots"] = [dict(r) for r in cur.fetchall()]
    return {"products": products}


def deploy(cur, bundle: dict, effective_from: date) -> dict:
    stats = {"products_added": 0, "catalogs_added": 0, "blocks_added": 0,
             "blocks_updated": 0, "hotspots_added": 0, "hotspots_updated": 0}
    for table in ("dm_loai_hang", "dm_visual_catalog", "dm_bo_phan", "dm_chi_tiet"):
        reset_sequence(cur, table)

    # The three existing visuals are unchanged; versioning only adds metadata.
    for name in UNCHANGED_PRODUCTS:
        product = one(cur, "SELECT id FROM dm_loai_hang WHERE ten_loai=%s", (name,), name)
        catalog_id, created = ensure_catalog(
            cur, product["id"], "legacy-current", "Visual hiện hành",
            date(1900, 1, 1), None, None,
        )
        stats["catalogs_added"] += int(created)
        cur.execute(
            """
            UPDATE dm_bo_phan SET visual_catalog_id=%s
            WHERE loai_hang_id=%s AND visual_catalog_id IS NULL
              AND nhom IS NOT NULL AND image_png IS NOT NULL
            """,
            (catalog_id, product["id"]),
        )
        stats["blocks_updated"] += cur.rowcount

    yem = one(cur, "SELECT id FROM dm_loai_hang WHERE ten_loai=%s", (YEM,), YEM)
    old_catalog, created = ensure_catalog(
        cur, yem["id"], "legacy-before-co2", "Danh mục Yếm trước Co-2",
        date(1900, 1, 1), effective_from - timedelta(days=1), None,
    )
    stats["catalogs_added"] += int(created)
    cur.execute(
        """
        UPDATE dm_bo_phan SET visual_catalog_id=%s
        WHERE loai_hang_id=%s AND visual_catalog_id IS NULL
          AND nhom IS NULL AND image_png IS NULL
        """,
        (old_catalog, yem["id"]),
    )
    stats["blocks_updated"] += cur.rowcount

    for product_data in bundle["products"]:
        product_id, created = ensure_product(cur, product_data["name"], product_data.get("id_type"))
        stats["products_added"] += int(created)
        catalog_id, created = ensure_catalog(
            cur, product_id, product_data["version_code"], product_data["version_name"],
            effective_from, None, bundle.get("source_file"),
        )
        stats["catalogs_added"] += int(created)
        for block_data in product_data["blocks"]:
            cur.execute(
                """
                SELECT * FROM dm_bo_phan
                WHERE loai_hang_id=%s AND ten_bo_phan=%s AND nhom=%s
                  AND (visual_catalog_id=%s OR visual_catalog_id IS NULL)
                ORDER BY (visual_catalog_id=%s) DESC, id
                """,
                (product_id, block_data["name"], block_data["group"], catalog_id, catalog_id),
            )
            blocks = cur.fetchall()
            if len(blocks) > 1:
                raise ValueError(f"Ambiguous block: {product_data['name']} / {block_data['name']}")
            if blocks:
                block_id = blocks[0]["id"]
                cur.execute(
                    """
                    UPDATE dm_bo_phan
                    SET visual_catalog_id=%s, image_png=%s, image_svg=%s, sort_order=%s
                    WHERE id=%s
                    """,
                    (catalog_id, block_data["image_png"], block_data.get("image_svg"),
                     block_data["sort_order"], block_id),
                )
                stats["blocks_updated"] += 1
            else:
                cur.execute(
                    """
                    INSERT INTO dm_bo_phan
                        (loai_hang_id, ten_bo_phan, nhom, image_png, image_svg,
                         sort_order, visual_catalog_id)
                    VALUES (%s,%s,%s,%s,%s,%s,%s)
                    RETURNING id
                    """,
                    (product_id, block_data["name"], block_data["group"],
                     block_data["image_png"], block_data.get("image_svg"),
                     block_data["sort_order"], catalog_id),
                )
                block_id = cur.fetchone()["id"]
                stats["blocks_added"] += 1

            expected_codes = {spot["code"] for spot in block_data["hotspots"]}
            cur.execute("SELECT id, ma_vi_tri FROM dm_chi_tiet WHERE bo_phan_id=%s", (block_id,))
            current = cur.fetchall()
            current_by_code = {}
            for row in current:
                if row["ma_vi_tri"] in current_by_code:
                    raise ValueError(f"Duplicate DB code: block={block_id}, code={row['ma_vi_tri']}")
                current_by_code[row["ma_vi_tri"]] = row
            extras = set(current_by_code) - expected_codes
            if extras:
                raise ValueError(f"Unexpected existing codes in {product_data['name']} / {block_data['name']}: {sorted(extras)}")
            for spot in block_data["hotspots"]:
                values = (
                    spot["label"], spot["x_pct"], spot["y_pct"], spot["w_pct"],
                    spot["h_pct"], spot["rotation"],
                )
                current_spot = current_by_code.get(spot["code"])
                if current_spot:
                    cur.execute(
                        """
                        UPDATE dm_chi_tiet
                        SET ten_chi_tiet=%s,x_pct=%s,y_pct=%s,w_pct=%s,h_pct=%s,rotation=%s
                        WHERE id=%s
                        """,
                        values + (current_spot["id"],),
                    )
                    stats["hotspots_updated"] += 1
                else:
                    cur.execute(
                        """
                        INSERT INTO dm_chi_tiet
                            (bo_phan_id,ma_vi_tri,ten_chi_tiet,x_pct,y_pct,w_pct,h_pct,rotation)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                        """,
                        (block_id, spot["code"]) + values,
                    )
                    stats["hotspots_added"] += 1
    return stats


def copy_assets(bundle: dict, destination_root: Path) -> int:
    copied = 0
    for product in bundle["products"]:
        for block in product["blocks"]:
            source = ASSET_ROOT / block["image_png"]
            target = destination_root / block["image_png"]
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists() and hashlib.sha256(target.read_bytes()).hexdigest() == block["image_sha256"]:
                continue
            shutil.copyfile(source, target)
            copied += 1
    return copied


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--effective-from", required=True, type=date.fromisoformat,
                        help="Business effective date in YYYY-MM-DD")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    load_dotenv(ROOT / ".env")
    bundle = json.loads(BUNDLE_PATH.read_text(encoding="utf-8"))
    validate_bundle(bundle)
    product_names = UNCHANGED_PRODUCTS + [p["name"] for p in bundle["products"]]
    with psycopg2.connect(os.environ["DATABASE_URL"]) as conn:
        conn.autocommit = False
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT to_regclass('public.dm_visual_catalog') AS table_name")
            if not cur.fetchone()["table_name"]:
                raise RuntimeError("Run db/migrate_visual_catalog_versioning.sql first")
            before = snapshot(cur, product_names)
            cur.execute(
                """
                SELECT COUNT(*) AS count
                FROM qc_defect d
                LEFT JOIN dm_bo_phan bp ON bp.id=d.bo_phan_id
                LEFT JOIN dm_chi_tiet ct ON ct.id=d.chi_tiet_id
                WHERE (d.bo_phan_id IS NOT NULL AND bp.id IS NULL)
                   OR (d.chi_tiet_id IS NOT NULL AND ct.id IS NULL)
                """
            )
            broken_before = cur.fetchone()["count"]
            if broken_before:
                raise ValueError(f"Database already has {broken_before} broken QC references")
            stats = deploy(cur, bundle, args.effective_from)
            cur.execute(
                """
                SELECT COUNT(*) AS count
                FROM qc_defect d
                LEFT JOIN dm_bo_phan bp ON bp.id=d.bo_phan_id
                LEFT JOIN dm_chi_tiet ct ON ct.id=d.chi_tiet_id
                WHERE (d.bo_phan_id IS NOT NULL AND bp.id IS NULL)
                   OR (d.chi_tiet_id IS NOT NULL AND ct.id IS NULL)
                """
            )
            if cur.fetchone()["count"] != broken_before:
                raise AssertionError("QC reference integrity changed")
            if args.apply:
                BACKUP_ROOT.mkdir(parents=True, exist_ok=True)
                backup = BACKUP_ROOT / f"co2_before_{datetime.now():%Y%m%d_%H%M%S_%f}.json"
                backup.write_text(json.dumps(before, ensure_ascii=False, indent=2, default=json_default), encoding="utf-8")
                copied = copy_assets(bundle, Path(os.environ["IMAGES_STORAGE_DIR"]))
                conn.commit()
                print(f"APPLIED effective_from={args.effective_from}; images copied={copied}; backup={backup}")
            else:
                conn.rollback()
                print(f"DRY RUN effective_from={args.effective_from}; transaction rolled back")
            print(json.dumps(stats, ensure_ascii=False))


if __name__ == "__main__":
    main()
