"""
Extract & Load (the "EL" in ELT): copy ShopBase source tables (public schema) into the
warehouse schema `raw`, unchanged, plus a _loaded_at column. No cleaning happens here:
cleaning belongs to dbt (next step).

Idempotent: every table is truncated and reloaded inside its own transaction, so running
the script twice never doubles the rows.

Config (.env):
    DATABASE_URL   source database (Supabase Session pooler string)
    WAREHOUSE_URL  optional; defaults to DATABASE_URL (same DB, separate `raw` schema)

Usage:  python extract_load.py
"""
import os
import sys
import time

import psycopg2
from psycopg2.extensions import register_adapter
from psycopg2.extras import Json, execute_values

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

register_adapter(dict, Json)   # jsonb columns come back as dict/list
register_adapter(list, Json)

# Analytics tables only. Auth/permission tables (business_members, inventory_access,
# staff_invitations) are deliberately excluded: personal data not needed for analytics.
TABLES = [
    "businesses", "inventories", "products", "inventory_stock", "customers", "tags",
    "customer_tags", "sales", "sale_items", "payments", "expenses",
    "stock_transfers", "stock_transfer_items", "stock_discrepancies", "applied_stock_operations",
]
BATCH = 5000

SRC_URL = os.environ.get("DATABASE_URL")
DST_URL = os.environ.get("WAREHOUSE_URL", SRC_URL)
if not SRC_URL:
    sys.exit("DATABASE_URL is not set. Put it in a .env file.")


def source_columns(conn, table):
    with conn.cursor() as cur:
        cur.execute(
            """select a.attname, format_type(a.atttypid, a.atttypmod)
               from pg_attribute a
               where a.attrelid = %s::regclass and a.attnum > 0 and not a.attisdropped
               order by a.attnum""",
            (f"public.{table}",),
        )
        cols = cur.fetchall()
    conn.rollback()
    return cols


def load_table(src, dst, table):
    cols = source_columns(src, table)
    names = ", ".join(f'"{c}"' for c, _ in cols)
    ddl = ", ".join(f'"{c}" {t}' for c, t in cols)      # no constraints: raw stays permissive
    total = 0
    with dst, dst.cursor() as d:                         # one transaction per table
        d.execute(f'create table if not exists raw."{table}" ({ddl}, _loaded_at timestamptz default now())')
        d.execute(f'truncate raw."{table}"')
        with src.cursor(name=f"cur_{table}") as s:       # server-side cursor: streams, low memory
            s.itersize = BATCH
            s.execute(f'select {names} from public."{table}"')
            while True:
                rows = s.fetchmany(BATCH)
                if not rows:
                    break
                execute_values(d, f'insert into raw."{table}" ({names}) values %s', rows, page_size=BATCH)
                total += len(rows)
    src.rollback()
    return total


def count(conn, qualified):
    with conn.cursor() as cur:
        cur.execute(f"select count(*) from {qualified}")
        n = cur.fetchone()[0]
    conn.rollback()
    return n


def main():
    src, dst = psycopg2.connect(SRC_URL), psycopg2.connect(DST_URL)
    with dst, dst.cursor() as d:
        d.execute("create schema if not exists raw")

    results, t0 = [], time.time()
    for t in TABLES:
        start = time.time()
        loaded = load_table(src, dst, t)
        results.append((t, count(src, f'public."{t}"'), count(dst, f'raw."{t}"'), time.time() - start))
        print(f"loaded {t:<26}{loaded:>9,} rows")

    print("\nReconciliation (source vs raw):")
    print(f"{'table':<26}{'source':>10}{'raw':>10}  status")
    ok = True
    for t, s, r, _ in results:
        status = "OK" if s == r else "MISMATCH"
        ok &= s == r
        print(f"{t:<26}{s:>10,}{r:>10,}  {status}")
    print(f"\nFinished in {time.time() - t0:.1f}s")
    src.close()
    dst.close()
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()