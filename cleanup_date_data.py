import argparse
import os
import sys
from dataclasses import dataclass
from datetime import date, datetime
from typing import Dict, List, Optional, Sequence, Tuple

import psycopg2
from psycopg2 import sql
from dotenv import load_dotenv


@dataclass(frozen=True)
class TableRef:
    schema: str
    name: str

    @property
    def fqn(self) -> str:
        return f"{self.schema}.{self.name}"


def _configure_utf8_console() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        except Exception:
            pass


def _require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required env var: {name}")
    return value


def get_conn():
    dsn = _require_env("DATABASE_URL")
    return psycopg2.connect(dsn)


def parse_target_date(value: str) -> date:
    raw = (value or "").strip()
    if not raw:
        raise ValueError("date value is empty")

    # Prefer ISO first
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            pass

    raise ValueError(
        f"Unsupported date format: {value!r}. Use YYYY-MM-DD (recommended) or DD/MM/YYYY."
    )


def fetch_date_tables(conn, schema: str, table_like: str, include_all_date_tables: bool) -> List[TableRef]:
    """
    Return tables that have a DATE column named 'date'.

    By default, restrict to qc_% tables to avoid accidental deletes on other modules.
    """
    with conn.cursor() as cur:
        if include_all_date_tables:
            cur.execute(
                """
                SELECT table_schema, table_name
                FROM information_schema.columns
                WHERE table_schema = %s
                  AND column_name = 'date'
                  AND data_type = 'date'
                GROUP BY table_schema, table_name
                ORDER BY table_schema, table_name
                """,
                (schema,),
            )
        else:
            cur.execute(
                """
                SELECT table_schema, table_name
                FROM information_schema.columns
                WHERE table_schema = %s
                  AND table_name LIKE %s
                  AND column_name = 'date'
                  AND data_type = 'date'
                GROUP BY table_schema, table_name
                ORDER BY table_schema, table_name
                """,
                (schema, table_like),
            )
        return [TableRef(r[0], r[1]) for r in cur.fetchall()]


def count_rows_for_date(conn, table: TableRef, target: date) -> Tuple[int, int]:
    with conn.cursor() as cur:
        cur.execute(
            sql.SQL("SELECT COUNT(*) FROM {}.{}").format(
                sql.Identifier(table.schema), sql.Identifier(table.name)
            )
        )
        total = int(cur.fetchone()[0])

        cur.execute(
            sql.SQL("SELECT COUNT(*) FROM {}.{} WHERE date = %s").format(
                sql.Identifier(table.schema), sql.Identifier(table.name)
            ),
            (target,),
        )
        match = int(cur.fetchone()[0])
    return total, match


def top_dates(conn, table: TableRef, limit: int = 10) -> List[Tuple[Optional[date], int]]:
    with conn.cursor() as cur:
        cur.execute(
            sql.SQL(
                """
                SELECT date, COUNT(*) AS c
                FROM {}.{}
                GROUP BY date
                ORDER BY c DESC, date DESC NULLS LAST
                LIMIT %s
                """
            ).format(sql.Identifier(table.schema), sql.Identifier(table.name)),
            (limit,),
        )
        return [(r[0], int(r[1])) for r in cur.fetchall()]


def delete_for_date(conn, table: TableRef, target: date) -> int:
    with conn.cursor() as cur:
        cur.execute(
            sql.SQL("DELETE FROM {}.{} WHERE date = %s").format(
                sql.Identifier(table.schema), sql.Identifier(table.name)
            ),
            (target,),
        )
        return int(cur.rowcount or 0)


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Delete data for a specific day (DATE column) in qc_% tables, "
            "including related rows via FK cascades."
        )
    )
    parser.add_argument(
        "--date",
        default="2026-04-07",
        help="Target date to DELETE (default: %(default)s). Use YYYY-MM-DD or DD/MM/YYYY.",
    )
    parser.add_argument("--schema", default="public", help="DB schema (default: %(default)s)")
    parser.add_argument(
        "--table-like",
        default="qc_%",
        help="SQL LIKE pattern for tables to target when not using --all-date-tables (default: %(default)s)",
    )
    parser.add_argument(
        "--all-date-tables",
        action="store_true",
        help="Target ALL tables with a DATE column named 'date' (more risky).",
    )
    parser.add_argument(
        "--commit",
        action="store_true",
        help="Actually perform deletes. Without this flag, runs in dry-run mode.",
    )
    return parser.parse_args(list(argv))


def main(argv: Sequence[str]) -> int:
    _configure_utf8_console()
    load_dotenv()

    args = parse_args(argv)
    try:
        target = parse_target_date(args.date)
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2

    conn = None
    try:
        conn = get_conn()
        conn.autocommit = False

        tables = fetch_date_tables(
            conn,
            schema=args.schema,
            table_like=args.table_like,
            include_all_date_tables=bool(args.all_date_tables),
        )
        if not tables:
            print(
                f"No target tables found with DATE column named 'date' in schema '{args.schema}' "
                f"(table_like={args.table_like!r}, all_date_tables={args.all_date_tables})."
            )
            return 0

        print(f"Target date to delete: {target.isoformat()}")
        print("Target tables:")
        for t in tables:
            print(f"  - {t.fqn}")

        print("\nRow counts (total / date-match):")
        total_match = 0
        per_table: Dict[str, int] = {}
        for t in tables:
            total, match = count_rows_for_date(conn, t, target)
            total_match += match
            per_table[t.fqn] = match
            print(f"  - {t.fqn}: {total} / {match}")

        print("\nTop dates per table (for sanity check):")
        for t in tables:
            vals = top_dates(conn, t, limit=10)
            summary = ", ".join([f"{d.isoformat() if d else None}={c}" for d, c in vals])
            print(f"  - {t.fqn}: {summary}")

        if not args.commit:
            conn.rollback()
            print("\nDry-run complete (no data deleted). Re-run with --commit to apply.")
            return 0

        if total_match == 0:
            conn.rollback()
            print("\nNothing to delete for that date.")
            return 0

        print("\nDeleting...")
        deleted_total = 0
        for t in tables:
            deleted = delete_for_date(conn, t, target)
            deleted_total += deleted
            print(f"  - {t.fqn}: deleted {deleted} rows (planned match: {per_table.get(t.fqn, 0)})")

        conn.commit()
        print(f"\nDone. Deleted {deleted_total} rows where date = {target.isoformat()} (FK cascades may delete more).")
        return 0

    except Exception as e:
        if conn is not None:
            try:
                conn.rollback()
            except Exception:
                pass
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

