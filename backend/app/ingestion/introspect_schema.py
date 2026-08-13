"""
Reads table/column names, types, foreign keys, and sample rows from the
seeded Postgres database, and writes one structured text "document" per
table to data/schema_docs/tables/<table_name>.txt. These documents (plus
the hand-written business glossary in data/schema_docs/business_glossary.json)
are what gets embedded and stored in pgvector for RAG retrieval.

Note: `schema_documents` (the pgvector storage table created by
embed_documents.py) lives in the same database as the business tables but
is deliberately excluded here — it's RAG infrastructure, not business
schema, and introspecting it would create a confusing "table that
describes itself" document.

Usage:
    python backend/app/ingestion/introspect_schema.py
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))

from backend.app.db.connection import get_connection

OUT_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "..", "data", "schema_docs", "tables")
SAMPLE_ROWS_PER_TABLE = 3

TABLE_QUERY = """
SELECT table_name
FROM information_schema.tables
WHERE table_schema = 'public'
  AND table_type = 'BASE TABLE'
  AND table_name NOT IN ('schema_documents')  -- internal RAG storage, not business data
ORDER BY table_name;
"""

COLUMN_QUERY = """
SELECT column_name, data_type, is_nullable, column_default
FROM information_schema.columns
WHERE table_schema = 'public' AND table_name = %s
ORDER BY ordinal_position;
"""

PK_QUERY = """
SELECT kcu.column_name
FROM information_schema.table_constraints tc
JOIN information_schema.key_column_usage kcu
  ON tc.constraint_name = kcu.constraint_name AND tc.table_schema = kcu.table_schema
WHERE tc.constraint_type = 'PRIMARY KEY'
  AND tc.table_schema = 'public'
  AND tc.table_name = %s;
"""

FK_QUERY = """
SELECT
    kcu.column_name AS fk_column,
    ccu.table_name AS references_table,
    ccu.column_name AS references_column
FROM information_schema.table_constraints tc
JOIN information_schema.key_column_usage kcu
  ON tc.constraint_name = kcu.constraint_name AND tc.table_schema = kcu.table_schema
JOIN information_schema.constraint_column_usage ccu
  ON tc.constraint_name = ccu.constraint_name AND tc.table_schema = ccu.table_schema
WHERE tc.constraint_type = 'FOREIGN KEY'
  AND tc.table_schema = 'public'
  AND tc.table_name = %s;
"""

# Referenced-by is just FK_QUERY run against every other table filtered on
# references_table = this table; computed in Python from a single pass below.


def fetch_tables(cur):
    cur.execute(TABLE_QUERY)
    return [r[0] for r in cur.fetchall()]


def fetch_columns(cur, table):
    cur.execute(COLUMN_QUERY, (table,))
    return cur.fetchall()  # (name, type, nullable, default)


def fetch_primary_keys(cur, table):
    cur.execute(PK_QUERY, (table,))
    return [r[0] for r in cur.fetchall()]


def fetch_foreign_keys(cur, table):
    cur.execute(FK_QUERY, (table,))
    return cur.fetchall()  # (fk_column, references_table, references_column)


def fetch_row_count(cur, table):
    cur.execute(f"SELECT COUNT(*) FROM {table}")
    return cur.fetchone()[0]


def fetch_sample_rows(cur, table, columns, n=SAMPLE_ROWS_PER_TABLE):
    col_names = ", ".join(c[0] for c in columns)
    cur.execute(f"SELECT {col_names} FROM {table} ORDER BY random() LIMIT %s", (n,))
    return cur.fetchall()


def build_table_doc(table, columns, pks, fks, referenced_by, row_count, sample_rows):
    lines = []
    lines.append(f"TABLE: {table}")
    lines.append(f"ROW COUNT (at seed time): {row_count:,}")
    lines.append("")
    lines.append("COLUMNS:")
    for name, dtype, nullable, default in columns:
        flags = []
        if name in pks:
            flags.append("PRIMARY KEY")
        nullable_str = "NULL" if nullable == "YES" else "NOT NULL"
        flags.append(nullable_str)
        flag_str = f" [{', '.join(flags)}]"
        lines.append(f"  - {name} ({dtype}){flag_str}")

    if fks:
        lines.append("")
        lines.append("FOREIGN KEYS (this table -> other tables):")
        for fk_col, ref_table, ref_col in fks:
            lines.append(f"  - {table}.{fk_col} -> {ref_table}.{ref_col}")

    if referenced_by:
        lines.append("")
        lines.append("REFERENCED BY (other tables -> this table):")
        for src_table, src_col, ref_col in referenced_by:
            lines.append(f"  - {src_table}.{src_col} -> {table}.{ref_col}")

    if sample_rows:
        lines.append("")
        lines.append(f"SAMPLE ROWS ({len(sample_rows)}):")
        col_names = [c[0] for c in columns]
        for row in sample_rows:
            row_str = ", ".join(f"{col}={val}" for col, val in zip(col_names, row))
            lines.append(f"  - {row_str}")

    return "\n".join(lines)


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            tables = fetch_tables(cur)
            print(f"Found {len(tables)} tables: {', '.join(tables)}")

            # First pass: gather every table's own FKs so we can invert
            # them into "referenced by" for each target table.
            all_fks = {t: fetch_foreign_keys(cur, t) for t in tables}
            referenced_by_map = {t: [] for t in tables}
            for src_table, fk_list in all_fks.items():
                for fk_col, ref_table, ref_col in fk_list:
                    if ref_table in referenced_by_map:
                        referenced_by_map[ref_table].append((src_table, fk_col, ref_col))

            for table in tables:
                columns = fetch_columns(cur, table)
                pks = fetch_primary_keys(cur, table)
                fks = all_fks[table]
                referenced_by = referenced_by_map[table]
                row_count = fetch_row_count(cur, table)
                sample_rows = fetch_sample_rows(cur, table, columns)

                doc = build_table_doc(table, columns, pks, fks, referenced_by, row_count, sample_rows)

                out_path = os.path.join(OUT_DIR, f"{table}.txt")
                with open(out_path, "w", encoding="utf-8") as f:
                    f.write(doc)
                print(f"  wrote {out_path}")
    finally:
        conn.close()

    print(f"\nDone. {len(tables)} schema documents written to {OUT_DIR}")


if __name__ == "__main__":
    main()
