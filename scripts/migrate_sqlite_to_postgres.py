"""Copy the SQLite database into Postgres, then prove the copy is correct.

The proving is the point. A migration that reports "6 tables copied" and stops
there is a guess — row counts can match while values are silently mangled, and
the failure surfaces weeks later as a wrong price in front of someone making a
pricing decision.

So every run ends with four gates, and any failure exits non-zero:

  1. row counts match per table
  2. MAX() of the four BIGINT columns matches exactly
     -- catches an INTEGER column silently truncating synthetic option ids
  3. zero orphaned foreign keys
  4. full row-level checksum of the five tables that cannot be regenerated

Gate 4 is the one that matters most. products and Rayna options are rebuilt
nightly from the feed, so losing them costs a cron run. mappings are human
judgement, competitor_listings and competitor options cost real Claude and
Firecrawl spend, and price_observations are historical and gone for good.

Usage:
    python -m scripts.migrate_sqlite_to_postgres \\
        --sqlite data/market_intel.db \\
        --pg "postgresql:///market_intel" \\
        [--truncate] [--verify-only]
"""
from __future__ import annotations

import argparse
import hashlib
import sqlite3
import sys
from typing import Any, Iterable

import psycopg

# Insert order matters: every table's FK targets must already exist.
TABLES: list[tuple[str, list[str]]] = [
    ("products", [
        "id", "name", "type", "city", "country", "market", "currency",
        "url", "raw_json", "ingested_at",
    ]),
    ("competitors", [
        "id", "rayna_product_id", "market", "seller_domain", "seller_name",
        "seed_url", "snippet", "search_rank", "search_query", "classified_as",
        "classifier_confidence", "classifier_reason", "sells_this_product",
        "classified_at", "discovered_at",
    ]),
    ("competitor_listings", [
        "id", "competitor_id", "listing_url", "title", "raw_markdown",
        "raw_html", "scraped_at", "scrape_method",
    ]),
    ("options", [
        "id", "source", "rayna_product_id", "competitor_listing_id", "name",
        "pricing_basis", "price", "currency", "market", "fingerprint_json",
        "raw_extracted_json", "extraction_model", "extracted_at",
    ]),
    ("mappings", [
        "id", "rayna_option_id", "competitor_option_id", "verdict",
        "confidence", "diff_notes", "judge_model", "human_reviewed",
        "human_verdict", "is_manual", "created_at",
    ]),
    ("price_observations", [
        "id", "option_id", "price", "currency", "market", "target_date",
        "captured_at", "is_spike_flagged", "capture_method",
    ]),
]

# SQLite stores these as 0/1; Postgres types them BOOLEAN.
BOOLEAN_COLUMNS = {
    ("competitors", "sells_this_product"),
    ("mappings", "human_reviewed"),
    ("mappings", "is_manual"),
    ("price_observations", "is_spike_flagged"),
}

# Cannot be regenerated from the feed — these get the full checksum.
CRITICAL_TABLES = [
    "mappings", "competitors", "competitor_listings",
    "options", "price_observations",
]

# Columns whose values exceed Postgres INTEGER range.
BIGINT_COLUMNS = [
    ("options", "id"),
    ("mappings", "rayna_option_id"),
    ("mappings", "competitor_option_id"),
    ("price_observations", "option_id"),
]

# Sequences to fast-forward. products.id has none — ids come from the feed.
SEQUENCE_TABLES = [
    "competitors", "competitor_listings", "options",
    "mappings", "price_observations",
]

BATCH = 500


def _coerce(table: str, columns: list[str], row: sqlite3.Row) -> tuple[Any, ...]:
    """SQLite row -> Postgres parameter tuple, converting 0/1 to bool."""
    out: list[Any] = []
    for col in columns:
        v = row[col]
        if (table, col) in BOOLEAN_COLUMNS and v is not None:
            v = bool(v)
        out.append(v)
    return tuple(out)


def _checksum_rows(rows: Iterable[tuple[Any, ...]]) -> str:
    """Order-independent digest of a whole table.

    Each row is hashed on its own and the digests are XORed together, so the
    result does not depend on the order rows come back in — the two engines
    make no promise of matching physical order, and imposing an ORDER BY on
    every table would just be a slower way to compare the same thing.
    """
    acc = bytearray(32)
    for row in rows:
        # repr() distinguishes None from "None" and 1 from "1"; str() would
        # collapse exactly the differences we are trying to detect.
        h = hashlib.sha256("\x1f".join(repr(v) for v in row).encode("utf-8")).digest()
        for i, b in enumerate(h):
            acc[i] ^= b
    return acc.hex()


def _normalise(table: str, columns: list[str], row: tuple[Any, ...]) -> tuple[Any, ...]:
    """Put both engines' values in the same shape before hashing.

    SQLite hands back ints for booleans and may hand back an int where the
    column is REAL; Postgres returns bool and float. Neither is a data
    difference, so normalise both sides rather than reporting a false failure.
    """
    out: list[Any] = []
    for col, v in zip(columns, row):
        if (table, col) in BOOLEAN_COLUMNS:
            v = None if v is None else bool(v)
        elif isinstance(v, int) and not isinstance(v, bool) and col in (
            "price", "confidence", "classifier_confidence",
        ):
            v = float(v)
        out.append(v)
    return tuple(out)


def copy_all(sqlite_path: str, pg_dsn: str, truncate: bool) -> None:
    src = sqlite3.connect(f"file:{sqlite_path}?mode=ro", uri=True)
    src.row_factory = sqlite3.Row

    with psycopg.connect(pg_dsn) as pg:
        with pg.cursor() as cur:
            if truncate:
                # Reverse order so FK dependents go first. RESTART IDENTITY
                # resets the sequences too; step 3 sets them properly after.
                names = ", ".join(t for t, _ in reversed(TABLES))
                cur.execute(f"TRUNCATE {names} RESTART IDENTITY CASCADE")
                print(f"  truncated: {names}")

            for table, columns in TABLES:
                rows = src.execute(f"SELECT {', '.join(columns)} FROM {table}").fetchall()
                if not rows:
                    print(f"  {table:<22} 0 rows (nothing to copy)")
                    continue
                placeholders = ", ".join(["%s"] * len(columns))
                stmt = (
                    f"INSERT INTO {table} ({', '.join(columns)}) "
                    f"VALUES ({placeholders})"
                )
                payload = [_coerce(table, columns, r) for r in rows]
                for i in range(0, len(payload), BATCH):
                    cur.executemany(stmt, payload[i:i + BATCH])
                print(f"  {table:<22} {len(rows):>8} rows copied")

            # Sequences must start above every id we just inserted explicitly,
            # or the first competitor option / mapping insert collides.
            print("\n  resetting sequences:")
            for table in SEQUENCE_TABLES:
                cur.execute(
                    "SELECT setval("
                    "  pg_get_serial_sequence(%s, 'id'),"
                    "  COALESCE((SELECT MAX(id) FROM " + table + "), 0) + 1,"
                    "  false)",
                    (table,),
                )
                nextval = cur.fetchone()[0]
                print(f"    {table:<22} next id = {nextval}")
        pg.commit()
    src.close()


def verify(sqlite_path: str, pg_dsn: str) -> bool:
    src = sqlite3.connect(f"file:{sqlite_path}?mode=ro", uri=True)
    src.row_factory = sqlite3.Row
    ok = True

    with psycopg.connect(pg_dsn) as pg, pg.cursor() as cur:
        # -- Gate 1: row counts ------------------------------------------
        print("\n  [1/4] row counts")
        for table, _ in TABLES:
            a = src.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            cur.execute(f"SELECT COUNT(*) FROM {table}")
            b = cur.fetchone()[0]
            flag = "ok" if a == b else "** MISMATCH **"
            if a != b:
                ok = False
            print(f"        {table:<22} sqlite={a:<8} pg={b:<8} {flag}")

        # -- Gate 2: BIGINT columns survived intact ----------------------
        print("\n  [2/4] BIGINT max values (truncation check)")
        for table, col in BIGINT_COLUMNS:
            a = src.execute(f"SELECT MAX({col}) FROM {table}").fetchone()[0]
            cur.execute(f"SELECT MAX({col}) FROM {table}")
            b = cur.fetchone()[0]
            flag = "ok" if a == b else "** TRUNCATED **"
            if a != b:
                ok = False
            print(f"        {table}.{col:<24} {str(a):>18} vs {str(b):>18}  {flag}")

        # -- Gate 3: referential integrity -------------------------------
        print("\n  [3/4] orphaned foreign keys")
        fks = [
            ("competitors", "rayna_product_id", "products", "id"),
            ("competitor_listings", "competitor_id", "competitors", "id"),
            ("options", "rayna_product_id", "products", "id"),
            ("options", "competitor_listing_id", "competitor_listings", "id"),
            ("mappings", "rayna_option_id", "options", "id"),
            ("mappings", "competitor_option_id", "options", "id"),
            ("price_observations", "option_id", "options", "id"),
        ]
        for child, ccol, parent, pcol in fks:
            cur.execute(
                f"SELECT COUNT(*) FROM {child} c "
                f"LEFT JOIN {parent} p ON p.{pcol} = c.{ccol} "
                f"WHERE c.{ccol} IS NOT NULL AND p.{pcol} IS NULL"
            )
            n = cur.fetchone()[0]
            if n:
                ok = False
            print(f"        {child}.{ccol:<24} orphans={n} {'ok' if n == 0 else '** BROKEN **'}")

        # -- Gate 4: row-level checksum on the irreplaceable tables -------
        print("\n  [4/4] row-level checksums (irreplaceable tables)")
        cols_by_table = dict(TABLES)
        for table in CRITICAL_TABLES:
            columns = cols_by_table[table]
            sel = ", ".join(columns)
            a_rows = (
                _normalise(table, columns, tuple(r))
                for r in src.execute(f"SELECT {sel} FROM {table}")
            )
            a = _checksum_rows(a_rows)
            cur.execute(f"SELECT {sel} FROM {table}")
            b = _checksum_rows(
                _normalise(table, columns, r) for r in cur.fetchall()
            )
            flag = "ok" if a == b else "** DIFFERS **"
            if a != b:
                ok = False
            print(f"        {table:<22} {a[:16]}… vs {b[:16]}…  {flag}")

    src.close()
    return ok


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sqlite", default="data/market_intel.db")
    ap.add_argument("--pg", default="postgresql:///market_intel")
    ap.add_argument("--truncate", action="store_true",
                    help="empty the Postgres tables first (safe to re-run)")
    ap.add_argument("--verify-only", action="store_true",
                    help="skip the copy, just run the four gates")
    args = ap.parse_args()

    print("=" * 66)
    print(f"  sqlite : {args.sqlite}")
    print(f"  pg     : {args.pg}")
    print("=" * 66)

    if not args.verify_only:
        print("\nCOPY")
        copy_all(args.sqlite, args.pg, args.truncate)

    print("\nVERIFY")
    ok = verify(args.sqlite, args.pg)

    print("\n" + "=" * 66)
    print("  RESULT: ALL GATES PASSED" if ok else "  RESULT: FAILED — do not cut over")
    print("=" * 66)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
