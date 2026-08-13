"""
Sanity-check script for the RAG retrieval pipeline built in Phase 1.
Embeds a natural-language question with the same embedder used at
ingestion time, runs a cosine-similarity search against the
schema_documents pgvector table, and prints the top-K matches so we can
eyeball retrieval quality *before* building the agent on top of it.

Usage:
    python backend/app/retrieval/test_retrieval.py "your question here"
    python backend/app/retrieval/test_retrieval.py "your question here" --top-k 5

If no question is given, runs a small built-in set of sample questions
covering different tables/glossary terms, useful as a quick regression
check after re-ingesting.
"""

import argparse
import os
import sys
import textwrap

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))

import numpy as np
from pgvector.psycopg2 import register_vector
from tabulate import tabulate

from backend.app.db.connection import get_connection
from backend.app.ingestion.embeddings import get_embedder

SAMPLE_QUESTIONS = [
    "What was transaction volume last quarter by state?",
    "Which merchant categories have the highest dispute rate?",
    "Show me the success rate of UPI payments versus card payments",
    "How many active users do we have in the South region?",
    "Which bank settles the most merchant transactions?",
]


def retrieve(cur, embedder, question, top_k):
    query_vector = np.array(embedder.embed([question])[0])
    cur.execute(
        """
        SELECT doc_type, title, content, 1 - (embedding <=> %s) AS similarity
        FROM schema_documents
        ORDER BY embedding <=> %s
        LIMIT %s
        """,
        (query_vector, query_vector, top_k),
    )
    return cur.fetchall()


def print_results(question, results):
    print("\n" + "=" * 100)
    print(f"QUESTION: {question}")
    print("=" * 100)
    table_rows = []
    for doc_type, title, content, similarity in results:
        preview = textwrap.shorten(content.replace("\n", " "), width=90, placeholder=" ...")
        table_rows.append([f"{similarity:.4f}", doc_type, title, preview])
    print(tabulate(table_rows, headers=["similarity", "doc_type", "title", "preview"], tablefmt="simple"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("question", nargs="?", default=None, help="Natural-language question to test retrieval for")
    parser.add_argument("--top-k", type=int, default=3)
    args = parser.parse_args()

    embedder = get_embedder()
    questions = [args.question] if args.question else SAMPLE_QUESTIONS

    conn = get_connection()
    register_vector(conn)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM schema_documents")
            total = cur.fetchone()[0]
            if total == 0:
                print(
                    "schema_documents is empty. Run "
                    "`python backend/app/ingestion/embed_documents.py` first.",
                    file=sys.stderr,
                )
                sys.exit(1)
            print(f"Retrieving from {total} indexed documents (embedder: {embedder.__class__.__name__})")

            for question in questions:
                results = retrieve(cur, embedder, question, args.top_k)
                print_results(question, results)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
