"""Postgres connection helpers.

Replaces the previous SQLite layer. The public shape is unchanged —
``get_conn()``, ``tx()`` and ``init_db()`` — so callers did not need
restructuring, only their SQL dialect updated.

Three behavioural differences from the SQLite version are worth knowing:

* **Placeholders are ``%s``, not ``?``.** psycopg does not accept ``?``.

* **Transactions are explicit.** sqlite3 committed on connection close in
  some paths; psycopg does not. Every write path must call ``commit()``, and
  ``tx()`` does it for you. Autocommit is deliberately left off so multi-
  statement writes stay atomic — ``create_manual_mapping`` deletes a prior
  mapping and inserts a replacement, and those two must land together or not
  at all.

* **Rows are dicts.** ``row["col"]`` works exactly as it did with
  ``sqlite3.Row``, but positional access (``row[0]``) does not. The two
  places that relied on it were rewritten to name their column.

Connections are created per caller rather than pooled. At current traffic the
connect cost is negligible next to the queries themselves, and a pool would
add a lifecycle to get wrong during a migration. If ``/api/dashboard`` stays
hot after the N+1 fix, a ``psycopg_pool.ConnectionPool`` drops in behind
``get_conn()`` without touching any caller.
"""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

from src import config

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"


def get_conn() -> psycopg.Connection:
    """Open a connection with dict rows. The caller is responsible for
    closing it, and for committing if it writes."""
    return psycopg.connect(config.DATABASE_URL, row_factory=dict_row)


def init_db() -> None:
    """Apply the schema. Idempotent — every statement is IF NOT EXISTS."""
    sql = (MIGRATIONS_DIR / "001_initial_schema.sql").read_text()
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(sql)
        conn.commit()
    finally:
        conn.close()


@contextmanager
def tx():
    """Transaction scope: commits on success, rolls back on any exception."""
    conn = get_conn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
