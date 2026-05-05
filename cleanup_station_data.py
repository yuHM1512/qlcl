import argparse
import os
import sys
from dataclasses import dataclass
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


@dataclass(frozen=True)
class ForeignKeyRef:
    child: TableRef
    child_column: str
    parent: TableRef
    parent_column: str
    delete_rule: str
    constraint_name: str


STATION_DELETE_COND_SQL = sql.SQL(
    "lower(btrim(station)) IS DISTINCT FROM lower(btrim(%s))"
)


def _require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required env var: {name}")
    return value


def get_conn():
    dsn = _require_env("DATABASE_URL")
    return psycopg2.connect(dsn)


def fetch_station_tables(
    conn,
    schema: str,
    table_like: str,
    include_all_station_tables: bool,
) -> List[TableRef]:
    """
    Return tables that have a TEXT/VARCHAR column named 'station'.

    By default, restrict to qc_% tables to avoid accidental deletes on config tables.
    """
    with conn.cursor() as cur:
        if include_all_station_tables:
            cur.execute(
                """
                SELECT table_schema, table_name
                FROM information_schema.columns
                WHERE table_schema = %s
                  AND column_name = 'station'
                  AND data_type IN ('text', 'character varying')
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
                  AND column_name = 'station'
                  AND data_type IN ('text', 'character varying')
                GROUP BY table_schema, table_name
                ORDER BY table_schema, table_name
                """,
                (schema, table_like),
            )
        return [TableRef(r[0], r[1]) for r in cur.fetchall()]


def fetch_primary_key_columns(conn, table: TableRef) -> List[str]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT kcu.column_name
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
              ON kcu.constraint_name = tc.constraint_name
             AND kcu.table_schema = tc.table_schema
             AND kcu.table_name = tc.table_name
            WHERE tc.table_schema = %s
              AND tc.table_name = %s
              AND tc.constraint_type = 'PRIMARY KEY'
            ORDER BY kcu.ordinal_position
            """,
            (table.schema, table.name),
        )
        return [r[0] for r in cur.fetchall()]


def fetch_inbound_foreign_keys(conn, parent: TableRef) -> List[ForeignKeyRef]:
    """
    Return foreign keys in other tables that reference `parent`.
    Only returns single-column FK mappings.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
              rc.constraint_name,
              rc.delete_rule,
              kcu.table_schema AS child_schema,
              kcu.table_name AS child_table,
              kcu.column_name AS child_column,
              ccu.table_schema AS parent_schema,
              ccu.table_name AS parent_table,
              ccu.column_name AS parent_column
            FROM information_schema.referential_constraints rc
            JOIN information_schema.key_column_usage kcu
              ON kcu.constraint_name = rc.constraint_name
             AND kcu.constraint_schema = rc.constraint_schema
            JOIN information_schema.constraint_column_usage ccu
              ON ccu.constraint_name = rc.unique_constraint_name
             AND ccu.constraint_schema = rc.unique_constraint_schema
            WHERE ccu.table_schema = %s
              AND ccu.table_name = %s
            ORDER BY child_schema, child_table, rc.constraint_name
            """,
            (parent.schema, parent.name),
        )
        raw = cur.fetchall()

    # information_schema.* joins above can produce multiple rows for composite keys; filter to 1:1 cases.
    by_constraint: Dict[str, List[Tuple]] = {}
    for row in raw:
        by_constraint.setdefault(row[0], []).append(row)

    fks: List[ForeignKeyRef] = []
    for constraint_name, rows in by_constraint.items():
        if len(rows) != 1:
            continue
        (
            _constraint_name,
            delete_rule,
            child_schema,
            child_table,
            child_column,
            parent_schema,
            parent_table,
            parent_column,
        ) = rows[0]
        if parent_schema != parent.schema or parent_table != parent.name:
            continue
        fks.append(
            ForeignKeyRef(
                child=TableRef(child_schema, child_table),
                child_column=child_column,
                parent=TableRef(parent_schema, parent_table),
                parent_column=parent_column,
                delete_rule=delete_rule,
                constraint_name=constraint_name,
            )
        )
    return fks


def count_rows(conn, table: TableRef, keep_station: str) -> Tuple[int, int, int]:
    with conn.cursor() as cur:
        cur.execute(
            sql.SQL("SELECT COUNT(*) FROM {}.{}").format(
                sql.Identifier(table.schema), sql.Identifier(table.name)
            )
        )
        total = int(cur.fetchone()[0])

        cur.execute(
            sql.SQL(
                "SELECT COUNT(*) FROM {}.{} WHERE lower(btrim(station)) = lower(btrim(%s))"
            ).format(sql.Identifier(table.schema), sql.Identifier(table.name)),
            (keep_station,),
        )
        keep = int(cur.fetchone()[0])

        cur.execute(
            sql.SQL("SELECT COUNT(*) FROM {}.{} WHERE ").format(
                sql.Identifier(table.schema), sql.Identifier(table.name)
            )
            + STATION_DELETE_COND_SQL,
            (keep_station,),
        )
        delete = int(cur.fetchone()[0])

    return total, keep, delete


def top_station_values(conn, table: TableRef, limit: int = 15) -> List[Tuple[Optional[str], int]]:
    with conn.cursor() as cur:
        cur.execute(
            sql.SQL(
                """
                SELECT station, COUNT(*) AS c
                FROM {}.{}
                GROUP BY station
                ORDER BY c DESC, station NULLS LAST
                LIMIT %s
                """
            ).format(sql.Identifier(table.schema), sql.Identifier(table.name)),
            (limit,),
        )
        return [(r[0], int(r[1])) for r in cur.fetchall()]


def delete_non_cascade_children(conn, parent: TableRef, keep_station: str) -> int:
    """
    For inbound FKs to `parent` that are NOT ON DELETE CASCADE, delete the child rows first.
    Returns total rows deleted across child tables.
    """
    parent_pk = fetch_primary_key_columns(conn, parent)
    if len(parent_pk) != 1:
        raise RuntimeError(
            f"Unsupported primary key on {parent.fqn}: {parent_pk or 'NONE'} (need single-column PK)"
        )
    parent_pk_col = parent_pk[0]

    total_deleted = 0
    fks = fetch_inbound_foreign_keys(conn, parent)
    for fk in fks:
        if fk.delete_rule.upper() == "CASCADE":
            continue
        if fk.parent_column != parent_pk_col:
            raise RuntimeError(
                f"FK {fk.constraint_name} references {parent.fqn}.{fk.parent_column} "
                f"(expected PK {parent_pk_col}). Cannot safely pre-delete."
            )

        with conn.cursor() as cur:
            cur.execute(
                sql.SQL("DELETE FROM {}.{} WHERE {} IN (SELECT {} FROM {}.{} WHERE ")
                .format(
                    sql.Identifier(fk.child.schema),
                    sql.Identifier(fk.child.name),
                    sql.Identifier(fk.child_column),
                    sql.Identifier(parent_pk_col),
                    sql.Identifier(parent.schema),
                    sql.Identifier(parent.name),
                )
                + STATION_DELETE_COND_SQL
                + sql.SQL(")"),
                (keep_station,),
            )
            total_deleted += int(cur.rowcount or 0)
    return total_deleted


def delete_station_rows(conn, table: TableRef, keep_station: str) -> int:
    with conn.cursor() as cur:
        cur.execute(
            sql.SQL("DELETE FROM {}.{} WHERE ").format(
                sql.Identifier(table.schema), sql.Identifier(table.name)
            )
            + STATION_DELETE_COND_SQL,
            (keep_station,),
        )
        return int(cur.rowcount or 0)


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Delete test data for stations other than a kept station value, "
            "including related rows via FK cascades / pre-deletes when needed."
        )
    )
    parser.add_argument(
        "--keep-station",
        default="Trạm sau seam",
        help="Station value to KEEP (default: %(default)s)",
    )
    parser.add_argument("--schema", default="public", help="DB schema (default: %(default)s)")
    parser.add_argument(
        "--table-like",
        default="qc_%",
        help="SQL LIKE pattern for tables to target when not using --all-station-tables (default: %(default)s)",
    )
    parser.add_argument(
        "--all-station-tables",
        action="store_true",
        help="Target all tables with a TEXT/VARCHAR station column (more risky).",
    )
    parser.add_argument(
        "--commit",
        action="store_true",
        help="Actually perform deletes. Without this flag, runs in dry-run mode.",
    )
    return parser.parse_args(list(argv))


def _configure_utf8_console() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        except Exception:
            pass


def main(argv: Sequence[str]) -> int:
    _configure_utf8_console()
    load_dotenv()

    args = parse_args(argv)
    keep_station = (args.keep_station or "").strip()
    if not keep_station:
        print("ERROR: --keep-station must be non-empty.", file=sys.stderr)
        return 2

    conn = None
    try:
        conn = get_conn()
        conn.autocommit = False

        station_tables = fetch_station_tables(
            conn,
            schema=args.schema,
            table_like=args.table_like,
            include_all_station_tables=bool(args.all_station_tables),
        )

        if not station_tables:
            print(
                f"No target tables found with station column in schema '{args.schema}' "
                f"(table_like={args.table_like!r}, all_station_tables={args.all_station_tables})."
            )
            return 0

        print(f"Keep station: {keep_station}")
        print("Target tables:")
        for t in station_tables:
            print(f"  - {t.fqn}")

        print("\nRow counts (total / keep / delete):")
        to_delete_total = 0
        for t in station_tables:
            total, keep, delete = count_rows(conn, t, keep_station)
            to_delete_total += delete
            print(f"  - {t.fqn}: {total} / {keep} / {delete}")

        print("\nTop station values per table (for sanity check):")
        for t in station_tables:
            vals = top_station_values(conn, t, limit=10)
            summary = ", ".join([f"{repr(v)}={c}" for v, c in vals])
            print(f"  - {t.fqn}: {summary}")

        if not args.commit:
            conn.rollback()
            print("\nDry-run complete (no data deleted). Re-run with --commit to apply.")
            return 0

        if to_delete_total == 0:
            conn.rollback()
            print("\nNothing to delete (all rows already match keep station).")
            return 0

        print("\nDeleting...")
        deleted_children = 0
        deleted_roots = 0
        for t in station_tables:
            deleted_children += delete_non_cascade_children(conn, t, keep_station)
            table_deleted = delete_station_rows(conn, t, keep_station)
            deleted_roots += table_deleted
            print(
                f"  - {t.fqn}: deleted {table_deleted} rows "
                f"(cumulative roots: {deleted_roots}, pre-deleted children: {deleted_children})"
            )

        conn.commit()
        print(
            f"\nDone. Deleted root rows: {deleted_roots}; pre-deleted child rows (non-cascade): {deleted_children}."
        )
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
