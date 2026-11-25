"""Deploy the Co-2 v2 visual bundle as a NEW catalog version for each product.

    python scripts/deploy_co2_v2_visual_catalog.py --effective-from YYYY-MM-DD          # dry run
    python scripts/deploy_co2_v2_visual_catalog.py --effective-from YYYY-MM-DD --apply  # commit

For every product in scripts/data/co2_v2_visual_catalog.json:
  * the currently open visual version is closed at effective_from - 1 day;
  * version "co2-v2" is created from effective_from with fresh blocks/hotspots.
Old blocks/hotspots are never modified or deleted, so historical QC defects keep
their references and QC reports dated before effective_from show the old visual.
Re-running with the same date is a no-op.
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
BUNDLE_PATH = ROOT / "scripts/data/co2_v2_visual_catalog.json"
ASSET_ROOT = ROOT / "scripts/assets/visual_picker"
BACKUP_ROOT = ROOT / "scripts/out/deploy_backups"
EXPECTED = {  # product -> (blocks, codes); guards against a wrong bundle
    "Áo đồng phục y tế": (4, 50),
    "Quần đồng phục y tế": (4, 47),
    "Quần thể thao": (12, 152),
    "Yếm thể thao": (13, 170),
    "Áo khoác thể thao nhiều lớp": (21, 218),
}


def json_default(value):
    if isinstance(value, (date, datetime, Decimal)):
        return str(value)
    raise TypeError(type(value).__name__)


def reset_sequence(cur, table: str) -> None:
    cur.execute("SELECT pg_get_serial_sequence(%s, 'id') AS seq", (f"public.{table}",))
    seq = cur.fetchone()["seq"]
    if seq:
        cur.execute(f"SELECT setval(%s, COALESCE((SELECT MAX(id) FROM public.{table}), 0) + 1, false)", (seq,))


def validate_bundle(bundle: dict) -> None:
    names = {p["name"] for p in bundle["products"]}
    if names != set(EXPECTED):
        raise ValueError(f"Unexpected bundle products: {sorted(names)}")
    for product in bundle["products"]:
        blocks = product["blocks"]
        codes = sum(len(b["hotspots"]) for b in blocks)
        if (len(blocks), codes) != EXPECTED[product["name"]]:
            raise ValueError(f"Unexpected counts for {product['name']}: {len(blocks)} blocks, {codes} codes")
        keys = [(b["group"], b["name"]) for b in blocks]
        if len(keys) != len(set(keys)):
            raise ValueError(f"Duplicate blocks: {product['name']}")
        for block in blocks:
            block_codes = [h["code"] for h in block["hotspots"]]
            if not all(block_codes) or len(block_codes) != len(set(block_codes)):
                raise ValueError(f"Missing/duplicate code: {product['name']} / {block['name']}")
            if any(len(c) > 10 for c in block_codes):
                raise ValueError(f"Code longer than dm_chi_tiet.ma_vi_tri: {block_codes}")
            source = ASSET_ROOT / block["image_png"]
            if hashlib.sha256(source.read_bytes()).hexdigest() != block["image_sha256"]:
                raise ValueError(f"Image checksum mismatch: {source}")


def broken_references(cur) -> int:
    cur.execute(
        """
        SELECT COUNT(*) AS count
        FROM qc_defect d
        LEFT JOIN dm_bo_phan bp ON bp.id = d.bo_phan_id
        LEFT JOIN dm_chi_tiet ct ON ct.id = d.chi_tiet_id
        WHERE (d.bo_phan_id IS NOT NULL AND bp.id IS NULL)
           OR (d.chi_tiet_id IS NOT NULL AND ct.id IS NULL)
        """
    )
    return cur.fetchone()["count"]


def snapshot(cur, product_ids: list[int]) -> dict:
    cur.execute("SELECT * FROM dm_visual_catalog WHERE loai_hang_id = ANY(%s) ORDER BY id", (product_ids,))
    catalogs = [dict(r) for r in cur.fetchall()]
    cur.execute("SELECT * FROM dm_bo_phan WHERE loai_hang_id = ANY(%s) ORDER BY id", (product_ids,))
    blocks = [dict(r) for r in cur.fetchall()]
    cur.execute("SELECT ct.* FROM dm_chi_tiet ct JOIN dm_bo_phan bp ON bp.id = ct.bo_phan_id "
                "WHERE bp.loai_hang_id = ANY(%s) ORDER BY ct.id", (product_ids,))
    return {"catalogs": catalogs, "blocks": blocks, "hotspots": [dict(r) for r in cur.fetchall()]}


def sync_existing(cur, product: dict, catalog_id: int, stats: dict) -> None:
    """Re-apply a corrected bundle to an already deployed version, keeping IDs.

    Blocks match on (nhom, name) and hotspots on code, so QC defects recorded
    against this version stay valid. Structural changes (added/removed blocks or
    codes) are refused: those need a new version instead.
    """
    changed = 0
    for block in product["blocks"]:
        cur.execute("SELECT id, image_png, sort_order FROM dm_bo_phan "
                    "WHERE visual_catalog_id = %s AND nhom = %s AND ten_bo_phan = %s",
                    (catalog_id, block["group"], block["name"]))
        rows = cur.fetchall()
        if len(rows) != 1:
            raise ValueError(f"{product['name']} / {block['name']}: expected one deployed block")
        row = rows[0]
        if (row["image_png"], row["sort_order"]) != (block["image_png"], block["sort_order"]):
            cur.execute("UPDATE dm_bo_phan SET image_png = %s, sort_order = %s WHERE id = %s",
                        (block["image_png"], block["sort_order"], row["id"]))
            stats["blocks_updated"] += 1
            changed += 1
        cur.execute("SELECT id, ma_vi_tri, ten_chi_tiet, x_pct, y_pct, w_pct, h_pct FROM dm_chi_tiet "
                    "WHERE bo_phan_id = %s", (row["id"],))
        current = {r["ma_vi_tri"]: r for r in cur.fetchall()}
        wanted = {s["code"]: s for s in block["hotspots"]}
        if set(current) != set(wanted):
            raise ValueError(f"{product['name']} / {block['name']}: codes differ from the deployed "
                             f"version ({sorted(set(current) ^ set(wanted))}); create a new version")
        for code, spot in wanted.items():
            r = current[code]
            new = (spot["label"], spot["x_pct"], spot["y_pct"], spot["w_pct"], spot["h_pct"])
            old = (r["ten_chi_tiet"],) + tuple(None if v is None else float(v)
                                               for v in (r["x_pct"], r["y_pct"], r["w_pct"], r["h_pct"]))
            if old != new:
                cur.execute("UPDATE dm_chi_tiet SET ten_chi_tiet = %s, x_pct = %s, y_pct = %s, "
                            "w_pct = %s, h_pct = %s WHERE id = %s", new + (r["id"],))
                stats["hotspots_updated"] += 1
                changed += 1
    print(f"  {product['name']}: {product['version_code']} already deployed; "
          f"{'synced ' + str(changed) + ' change(s)' if changed else 'up to date'}")


def deploy_product(cur, product: dict, effective_from: date, source_file: str, stats: dict) -> None:
    cur.execute("SELECT id FROM dm_loai_hang WHERE ten_loai = %s", (product["name"],))
    rows = cur.fetchall()
    if len(rows) != 1:
        raise ValueError(f"Expected one dm_loai_hang '{product['name']}', found {len(rows)}")
    product_id = rows[0]["id"]

    cur.execute("SELECT * FROM dm_visual_catalog WHERE loai_hang_id = %s AND version_code = %s",
                (product_id, product["version_code"]))
    existing = cur.fetchone()
    if existing:
        if existing["effective_from"] != effective_from:
            raise ValueError(f"{product['name']}: {product['version_code']} already starts "
                             f"{existing['effective_from']}, not {effective_from}")
        sync_existing(cur, product, existing["id"], stats)
        return

    # Unversioned visual blocks (older installs) get a legacy version first.
    cur.execute("SELECT COUNT(*) AS n FROM dm_bo_phan WHERE loai_hang_id = %s AND visual_catalog_id IS NULL "
                "AND nhom IS NOT NULL AND image_png IS NOT NULL", (product_id,))
    if cur.fetchone()["n"]:
        cur.execute("SELECT COUNT(*) AS n FROM dm_visual_catalog WHERE loai_hang_id = %s", (product_id,))
        if cur.fetchone()["n"]:
            raise ValueError(f"{product['name']}: mixes versioned and unversioned visual blocks")
        cur.execute("INSERT INTO dm_visual_catalog (loai_hang_id, version_code, name, effective_from) "
                    "VALUES (%s, 'legacy-current', 'Visual hiện hành', DATE '1900-01-01') RETURNING id",
                    (product_id,))
        legacy_id = cur.fetchone()["id"]
        cur.execute("UPDATE dm_bo_phan SET visual_catalog_id = %s WHERE loai_hang_id = %s "
                    "AND visual_catalog_id IS NULL AND nhom IS NOT NULL AND image_png IS NOT NULL",
                    (legacy_id, product_id))

    cur.execute("SELECT * FROM dm_visual_catalog WHERE loai_hang_id = %s AND effective_to IS NULL",
                (product_id,))
    open_versions = cur.fetchall()
    # Defects already entered on/after the switch date with the version being closed
    # stay valid (IDs are kept) but that day will show the new visual when reopened.
    cur.execute(
        "SELECT COUNT(*) AS n FROM qc_defect d JOIN dm_bo_phan bp ON bp.id = d.bo_phan_id "
        "WHERE bp.visual_catalog_id = ANY(%s) AND d.created_at::date >= %s",
        ([v["id"] for v in open_versions], effective_from),
    )
    late = cur.fetchone()["n"]
    if late:
        stats["warnings"] += 1
        print(f"  WARNING {product['name']}: {late} QC defect(s) since {effective_from} use the old "
              f"visual; they stay valid but reopen with the new one. Consider a later --effective-from.")
    for open_version in open_versions:
        if open_version["effective_from"] >= effective_from:
            raise ValueError(f"{product['name']}: open version {open_version['version_code']} starts "
                             f"{open_version['effective_from']}, cannot close it before {effective_from}")
        cur.execute("UPDATE dm_visual_catalog SET effective_to = %s WHERE id = %s",
                    (effective_from - timedelta(days=1), open_version["id"]))
        stats["versions_closed"] += 1
        print(f"  {product['name']}: close {open_version['version_code']} "
              f"({open_version['effective_from']}..{effective_from - timedelta(days=1)})")

    cur.execute(
        "INSERT INTO dm_visual_catalog (loai_hang_id, version_code, name, effective_from, source_file) "
        "VALUES (%s, %s, %s, %s, %s) RETURNING id",
        (product_id, product["version_code"], product["version_name"], effective_from, source_file),
    )
    catalog_id = cur.fetchone()["id"]
    stats["versions_added"] += 1
    for block in product["blocks"]:
        cur.execute(
            "INSERT INTO dm_bo_phan (loai_hang_id, ten_bo_phan, nhom, image_png, image_svg, sort_order, "
            "visual_catalog_id) VALUES (%s, %s, %s, %s, NULL, %s, %s) RETURNING id",
            (product_id, block["name"], block["group"], block["image_png"], block["sort_order"], catalog_id),
        )
        block_id = cur.fetchone()["id"]
        stats["blocks_added"] += 1
        for spot in block["hotspots"]:
            cur.execute(
                "INSERT INTO dm_chi_tiet (bo_phan_id, ma_vi_tri, ten_chi_tiet, x_pct, y_pct, w_pct, h_pct, "
                "rotation) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                (block_id, spot["code"], spot["label"], spot["x_pct"], spot["y_pct"],
                 spot["w_pct"], spot["h_pct"], spot["rotation"]),
            )
            stats["hotspots_added"] += 1
    print(f"  {product['name']}: + {product['version_code']} from {effective_from}: "
          f"{len(product['blocks'])} blocks, {sum(len(b['hotspots']) for b in product['blocks'])} codes")


def copy_assets(bundle: dict, destination_root: Path) -> int:
    copied = 0
    for product in bundle["products"]:
        for block in product["blocks"]:
            target = destination_root / block["image_png"]
            if target.exists() and hashlib.sha256(target.read_bytes()).hexdigest() == block["image_sha256"]:
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ASSET_ROOT / block["image_png"], target)
            copied += 1
    return copied


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--effective-from", required=True, type=date.fromisoformat)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    load_dotenv(ROOT / ".env")
    bundle = json.loads(BUNDLE_PATH.read_text(encoding="utf-8"))
    validate_bundle(bundle)
    stats = dict(versions_closed=0, versions_added=0, blocks_added=0, hotspots_added=0,
                 blocks_updated=0, hotspots_updated=0, warnings=0)
    with psycopg2.connect(os.environ["DATABASE_URL"]) as conn:
        conn.autocommit = False
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT to_regclass('public.dm_visual_catalog') AS t")
            if not cur.fetchone()["t"]:
                raise RuntimeError("Run db/migrate_visual_catalog_versioning.sql first")
            cur.execute("SELECT id FROM dm_loai_hang WHERE ten_loai = ANY(%s)", (list(EXPECTED),))
            before = snapshot(cur, [r["id"] for r in cur.fetchall()])
            broken = broken_references(cur)
            for table in ("dm_visual_catalog", "dm_bo_phan", "dm_chi_tiet"):
                reset_sequence(cur, table)
            for product in bundle["products"]:
                deploy_product(cur, product, args.effective_from, bundle["source_file"], stats)
            if broken_references(cur) != broken:
                raise AssertionError("QC defect reference integrity changed")
            if args.apply:
                BACKUP_ROOT.mkdir(parents=True, exist_ok=True)
                backup = BACKUP_ROOT / f"co2_v2_before_{datetime.now():%Y%m%d_%H%M%S}.json"
                backup.write_text(json.dumps(before, ensure_ascii=False, indent=1, default=json_default),
                                  encoding="utf-8")
                copied = copy_assets(bundle, Path(os.environ["IMAGES_STORAGE_DIR"]))
                conn.commit()
                print(f"APPLIED effective_from={args.effective_from}; images copied={copied}; backup={backup}")
            else:
                conn.rollback()
                print(f"DRY RUN effective_from={args.effective_from}; rolled back")
    print(json.dumps(stats))


if __name__ == "__main__":
    main()
