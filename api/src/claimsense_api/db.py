"""Small helpers for talking to PostgreSQL with plain SQL (psycopg 3).

Each call opens a short connection. That is simple and fast enough for this pilot's
volumes; a connection pool can replace it later without changing the callers.
"""
import os

import psycopg
from psycopg.rows import dict_row

DEFAULT_DB_URL = "postgresql://claimsense:claimsense@localhost:5433/claimsense"


def db_url():
    return os.environ.get("CLAIMSENSE_DB_URL", DEFAULT_DB_URL)


def fetch_all(sql, params=None):
    """Run a SELECT and return a list of dicts."""
    with psycopg.connect(db_url(), row_factory=dict_row) as conn:
        return conn.execute(sql, params).fetchall()


def fetch_one(sql, params=None):
    """Run a SELECT and return one dict, or None when there is no row."""
    with psycopg.connect(db_url(), row_factory=dict_row) as conn:
        return conn.execute(sql, params).fetchone()


def connect():
    """Open a connection for several statements that must succeed or fail together.

    Use it as `with connect() as conn:` — psycopg commits at the end of the block, or rolls
    everything back if an error is raised inside it.
    """
    return psycopg.connect(db_url(), row_factory=dict_row)


def execute(sql, params=None):
    """Run an INSERT/UPDATE and commit."""
    with psycopg.connect(db_url()) as conn:
        conn.execute(sql, params)
        conn.commit()
