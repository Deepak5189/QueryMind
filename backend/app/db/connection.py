# """Shared Postgres connection helper used by all Phase 1 scripts."""

# import os

# import psycopg2
# from dotenv import load_dotenv

# load_dotenv()


# def get_connection():
#     dsn = os.environ.get("DATABASE_URL")
#     if not dsn:
#         raise RuntimeError(
#             "DATABASE_URL not set. Copy .env.example to .env (or export "
#             "DATABASE_URL) and try again."
#         )
#     return psycopg2.connect(dsn, connect_timeout = 10)


# def get_readonly_connection():
#     """
#     Connection used ONLY by the agent's execute_sql node (Phase 2).

#     Uses READONLY_DATABASE_URL, which points at the `querymind_readonly`
#     Postgres role (see data/seed/create_readonly_role.sql) -- a role with
#     SELECT-only grants on the 8 business tables and no grants at all on
#     schema_documents. The connection is also explicitly set to
#     READ ONLY at the transaction level as a second, independent check,
#     so this is defense-in-depth behind the sqlglot guardrail in
#     backend/app/agent/guardrails.py, not a substitute for it.
#     """
#     dsn = os.environ.get("READONLY_DATABASE_URL")
#     if not dsn:
#         raise RuntimeError(
#             "READONLY_DATABASE_URL not set. Run "
#             "`psql \"$DATABASE_URL\" -f data/seed/create_readonly_role.sql` "
#             "then copy READONLY_DATABASE_URL from .env.example into your .env."
#         )
#     conn = psycopg2.connect(dsn, connect_timeout=10)
#     conn.set_session(readonly=True, autocommit=True)
#     return conn


"""Shared Postgres connection helper used by all Phase 1 scripts."""

import os
import time

import psycopg2
from dotenv import load_dotenv

load_dotenv()


def _connect_with_retry(dsn: str, *, retries: int = 5, backoff_s: float = 3.0, **kwargs):
    last_err = None
    for attempt in range(1, retries + 1):
        try:
            return psycopg2.connect(dsn, connect_timeout=10, **kwargs)
        except psycopg2.OperationalError as e:
            last_err = e
            if attempt < retries:
                time.sleep(backoff_s * (2 ** (attempt - 1)))
    raise last_err


def get_connection():
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        raise RuntimeError(
            "DATABASE_URL not set. Copy .env.example to .env (or export "
            "DATABASE_URL) and try again."
        )
    return _connect_with_retry(dsn)


def get_readonly_connection():
    """
    Connection used ONLY by the agent's execute_sql node (Phase 2).
    ...
    """
    dsn = os.environ.get("READONLY_DATABASE_URL")
    if not dsn:
        raise RuntimeError(
            "READONLY_DATABASE_URL not set. Run "
            "`psql \"$DATABASE_URL\" -f data/seed/create_readonly_role.sql` "
            "then copy READONLY_DATABASE_URL from .env.example into your .env."
        )
    conn = _connect_with_retry(dsn)
    conn.set_session(readonly=True, autocommit=True)
    return conn
