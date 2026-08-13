"""
Creates the QueryMind schema (data/seed/schema.sql) and loads the CSVs
produced by generate_data.py into Postgres using COPY (fast, no per-row
round trips).

Usage:
    python data/seed/seed_db.py

Requires DATABASE_URL in the environment (see .env.example). Loads .env
automatically via python-dotenv if present.
"""

import os

import psycopg2
from dotenv import load_dotenv

load_dotenv()

HERE = os.path.dirname(__file__)
SCHEMA_PATH = os.path.join(HERE, "schema.sql")
GENERATED_DIR = os.path.join(HERE, "generated")

# Load order matters: parents before children (FK dependencies).
# Value is the serial/bigserial primary-key column whose sequence needs
# resyncing after a COPY with explicit ids (states has no serial PK).
TABLE_LOAD_ORDER = [
    ("states", None),
    ("banks", "bank_id"),
    ("merchant_categories", "category_id"),
    ("users", "user_id"),
    ("merchants", "merchant_id"),
    ("cards", "card_id"),
    ("transactions", "transaction_id"),
    ("disputes", "dispute_id"),
]


def get_conn():
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        raise RuntimeError(
            "DATABASE_URL not set. Copy .env.example to .env and fill it in, "
            "or export DATABASE_URL directly."
        )
    return psycopg2.connect(dsn)


def apply_schema(conn):
    print(f"Applying schema from {SCHEMA_PATH} ...")
    with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
        ddl = f.read()
    with conn.cursor() as cur:
        cur.execute(ddl)
    conn.commit()
    print("  schema applied.")


def load_table(conn, table_name, pk_column):
    csv_path = os.path.join(GENERATED_DIR, f"{table_name}.csv")
    if not os.path.exists(csv_path):
        raise FileNotFoundError(
            f"{csv_path} not found. Run `python data/seed/generate_data.py` first."
        )
    with conn.cursor() as cur, open(csv_path, "r", encoding="utf-8") as f:
        # NULL '' handles the empty-string sentinel used for optional
        # FK/date columns (e.g. transactions.card_id, disputes.resolved_date)
        # written by generate_data.py.
        copy_sql = f"COPY {table_name} FROM STDIN WITH (FORMAT csv, HEADER true, NULL '')"
        cur.copy_expert(copy_sql, f)
        if pk_column:
            # Re-sync the serial sequence after loading explicit ids, so
            # future inserts (e.g. from the Phase 2+ app) don't collide.
            cur.execute(
                f"SELECT setval(pg_get_serial_sequence('{table_name}', %s), "
                f"COALESCE((SELECT MAX({pk_column}) FROM {table_name}), 1))",
                (pk_column,),
            )
    conn.commit()
    with conn.cursor() as cur:
        cur.execute(f"SELECT COUNT(*) FROM {table_name}")
        count = cur.fetchone()[0]
    print(f"  loaded {table_name:<22} {count:>7,} rows")


def main():
    conn = get_conn()
    try:
        apply_schema(conn)
        print("Loading CSVs into Postgres...")
        for table, pk_column in TABLE_LOAD_ORDER:
            load_table(conn, table, pk_column)
        print("\nSeed complete.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
