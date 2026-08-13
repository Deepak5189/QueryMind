"""
Embeds the schema documents (data/schema_docs/tables/*.txt, produced by
introspect_schema.py) and the hand-written business glossary
(data/schema_docs/business_glossary.json), and stores them with their
embedding vectors in a pgvector-backed table (schema_documents) for RAG
retrieval.

Usage:
    python backend/app/ingestion/embed_documents.py

Requires DATABASE_URL in the environment and the `vector` extension to
already be enabled in the target database (docker-compose.yml enables it
automatically; data/seed/init_extensions.sql is the source of truth).
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))

from pgvector.psycopg2 import register_vector

from backend.app.db.connection import get_connection
from backend.app.ingestion.embeddings import get_embedder

SCHEMA_DOCS_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "..", "data", "schema_docs")
TABLES_DIR = os.path.join(SCHEMA_DOCS_DIR, "tables")
GLOSSARY_PATH = os.path.join(SCHEMA_DOCS_DIR, "business_glossary.json")

CREATE_TABLE_SQL = """
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS schema_documents (
    id          SERIAL PRIMARY KEY,
    doc_type    VARCHAR(20) NOT NULL,   -- 'table' | 'glossary'
    title       VARCHAR(120) NOT NULL,  -- table name or glossary term
    content     TEXT NOT NULL,
    embedding   VECTOR({dim}) NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_schema_documents_embedding
    ON schema_documents USING hnsw (embedding vector_cosine_ops);
"""


def load_table_docs():
    docs = []
    if not os.path.isdir(TABLES_DIR):
        raise FileNotFoundError(
            f"{TABLES_DIR} not found. Run `python backend/app/ingestion/introspect_schema.py` first."
        )
    for fname in sorted(os.listdir(TABLES_DIR)):
        if not fname.endswith(".txt"):
            continue
        table_name = fname[: -len(".txt")]
        with open(os.path.join(TABLES_DIR, fname), "r", encoding="utf-8") as f:
            content = f.read()
        docs.append({"doc_type": "table", "title": table_name, "content": content})
    return docs


def load_glossary_docs():
    docs = []
    with open(GLOSSARY_PATH, "r", encoding="utf-8") as f:
        glossary = json.load(f)
    for entry in glossary:
        content = (
            f"TERM: {entry['term']}\n\n"
            f"DEFINITION: {entry['definition']}\n\n"
            f"RELATED TABLES: {', '.join(entry['related_tables'])}"
        )
        docs.append({"doc_type": "glossary", "title": entry["term"], "content": content})
    return docs


def main():
    embedder = get_embedder()
    print(f"Using embedder: {embedder.__class__.__name__} (dim={embedder.dim})")

    table_docs = load_table_docs()
    glossary_docs = load_glossary_docs()
    all_docs = table_docs + glossary_docs
    print(f"Loaded {len(table_docs)} table docs + {len(glossary_docs)} glossary docs = {len(all_docs)} total")

    print("Computing embeddings...")
    contents = [d["content"] for d in all_docs]
    vectors = embedder.embed(contents)

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(CREATE_TABLE_SQL.format(dim=embedder.dim))
        conn.commit()
        register_vector(conn)  # must run after CREATE EXTENSION vector, before using vector cursor adaptation
        with conn.cursor() as cur:
            # Idempotent re-ingestion: clear previous rows so re-running
            # this script after schema/glossary edits doesn't duplicate.
            cur.execute("TRUNCATE TABLE schema_documents RESTART IDENTITY")
            for doc, vector in zip(all_docs, vectors):
                cur.execute(
                    "INSERT INTO schema_documents (doc_type, title, content, embedding) "
                    "VALUES (%s, %s, %s, %s)",
                    (doc["doc_type"], doc["title"], doc["content"], vector),
                )
        conn.commit()
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM schema_documents")
            count = cur.fetchone()[0]
        print(f"\nInserted {count} rows into schema_documents (pgvector table).")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
