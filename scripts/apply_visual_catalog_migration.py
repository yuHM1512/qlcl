"""Apply the idempotent visual-catalog schema migration.

The default is a transactional dry run. Pass --apply to commit the schema.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path

import psycopg2
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "db/migrate_visual_catalog_versioning.sql"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Commit the migration")
    args = parser.parse_args()

    load_dotenv(ROOT / ".env")
    sql = MIGRATION.read_text(encoding="utf-8")
    with psycopg2.connect(os.environ["DATABASE_URL"]) as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
            cur.execute(
                """
                SELECT to_regclass('public.dm_visual_catalog'),
                       EXISTS (
                           SELECT 1 FROM information_schema.columns
                           WHERE table_schema='public'
                             AND table_name='dm_bo_phan'
                             AND column_name='visual_catalog_id'
                       )
                """
            )
            table_name, has_column = cur.fetchone()
            if not table_name or not has_column:
                raise RuntimeError("Visual catalog schema verification failed")
        if args.apply:
            conn.commit()
            print(f"APPLIED {MIGRATION.name}")
        else:
            conn.rollback()
            print(f"DRY RUN {MIGRATION.name}; transaction rolled back")


if __name__ == "__main__":
    main()
