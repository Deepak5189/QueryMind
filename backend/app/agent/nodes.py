"""
Node functions for the QueryMind LangGraph agent graph. Each function
takes the AgentState dict and returns a partial dict of updates, which
LangGraph merges into state before the next node runs. Every node is
wrapped in @traced_node so its input/output is logged (and, when
LangSmith is configured, traced there too) -- see tracing.py.
"""

from __future__ import annotations

import os
import re

import numpy as np
from pgvector.psycopg2 import register_vector

from backend.app.agent.guardrails import validate_sql as guardrail_validate
from backend.app.agent.llm import get_llm
from backend.app.agent.state import AgentState
from backend.app.agent.tracing import traced_node
from backend.app.db.connection import get_connection, get_readonly_connection
from backend.app.ingestion.embeddings import get_embedder

MAX_RETRIES = 2
# Overridable via env var so the Phase 4 eval harness can run a retrieval
# tuning pass (e.g. TOP_K_CONTEXT=8) without editing code between runs.
TOP_K_CONTEXT = int(os.environ.get("TOP_K_CONTEXT", "8"))
EXECUTION_TIMEOUT_MS = 5000
MAX_DISPLAY_ROWS = 50


def _clean_sql_text(text: str) -> str:
    """LLMs frequently wrap SQL in markdown code fences or prefix it with
    a label even when told not to -- strip that defensively rather than
    letting it fail sqlglot parsing on something a human would read as
    obviously fine."""
    text = text.strip()
    text = re.sub(r"^```(?:sql)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"```\s*$", "", text)
    text = re.sub(r"^(SQL|Query)\s*:\s*", "", text, flags=re.IGNORECASE)
    return text.strip()


@traced_node("retrieve_context")
def retrieve_context(state: AgentState) -> dict:
    """Reuses the Phase 1 embedder + pgvector schema_documents table.
    For follow-up questions, the retrieval query blends recent
    conversation history with the current question -- a bare follow-up
    like "now filter to only Karnataka" carries little retrievable
    signal on its own, but combined with the prior turn's question it
    surfaces the same states/transactions context the original question
    did."""
    history = state.get("conversation_history", [])
    recent_questions = [t["question"] for t in history[-2:]] + [state["question"]]
    retrieval_query = " ".join(recent_questions)

    embedder = get_embedder()
    query_vector = np.array(embedder.embed([retrieval_query])[0])

    conn = get_connection()
    register_vector(conn)
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT doc_type, title, content, 1 - (embedding <=> %s) AS similarity
                FROM schema_documents
                ORDER BY embedding <=> %s
                LIMIT %s
                """,
                (query_vector, query_vector, TOP_K_CONTEXT),
            )
            rows = cur.fetchall()
    finally:
        conn.close()

    context = [
        {"doc_type": r[0], "title": r[1], "content": r[2], "similarity": float(r[3])}
        for r in rows
    ]
    return {"retrieved_context": context}


# @traced_node("generate_sql")
# def generate_sql(state: AgentState) -> dict:
    """Generates (or regenerates, on retry) candidate SQL. When
    validation_error is set in state, this call IS a retry -- increment
    retry_count and pass the error to the LLM as feedback so it can fix
    the specific problem rather than guessing again blind."""
    llm = get_llm()
    validation_error = state.get("validation_error")
    retry_count = state.get("retry_count", 0)
    if validation_error:
        retry_count += 1

    raw_sql = llm.generate_sql(
        question=state["question"],
        context=state.get("retrieved_context", []),
        history=state.get("conversation_history", []),
        feedback=validation_error,
    )
    return {
        "candidate_sql": _clean_sql_text(raw_sql),
        "retry_count": retry_count,
        "validation_error": None,
    }

@traced_node("generate_sql")
def generate_sql(state: AgentState) -> dict:
    """Generates or regenerates candidate SQL.

    A regeneration can be triggered by either:
    1. a SQL safety/validation error, or
    2. a PostgreSQL execution error.

    The specific error is passed back to the LLM as feedback so that
    it can correct the previous SQL rather than generating blindly.
    """
    llm = get_llm()

    validation_error = state.get("validation_error")
    execution_error = state.get("execution_error")

    # Either type of error means this is a retry.
    feedback = validation_error or execution_error

    retry_count = state.get("retry_count", 0)

    if feedback:
        retry_count += 1

    raw_sql = llm.generate_sql(
        question=state["question"],
        context=state.get("retrieved_context", []),
        history=state.get("conversation_history", []),
        feedback=feedback,
    )

    return {
        "candidate_sql": _clean_sql_text(raw_sql),
        "retry_count": retry_count,
        "validation_error": None,
        "execution_error": None,
    }

@traced_node("validate_sql")
def validate_sql(state: AgentState) -> dict:
    result = guardrail_validate(state["candidate_sql"])
    if result.is_valid:
        return {"is_valid": True, "candidate_sql": result.cleaned_sql, "validation_error": None}
    return {"is_valid": False, "validation_error": result.error}


def route_after_validate(state: AgentState) -> str:
    """Conditional edge (not itself a node -- LangGraph calls this to
    pick the next node, it doesn't update state)."""
    if state.get("is_valid"):
        return "execute"
    # if state.get("retry_count", 0) >= MAX_RETRIES:
    #     return "fail"
    # return "retry"
    return "fail"


# @traced_node("execute_sql")
# def execute_sql(state: AgentState) -> dict:
    """Runs the validated SQL against the read-only Postgres role (see
    db/connection.py:get_readonly_connection and
    data/seed/create_readonly_role.sql) -- defense-in-depth behind the
    sqlglot guardrail, not a replacement for it. A DB-level execution
    error here (e.g. the LLM hallucinated a column name that passed the
    table-scope check but doesn't exist) is treated as a hard failure
    for this turn rather than looped back into the retry budget, since
    the spec's retry loop is scoped to *validation* failures; a natural
    Phase 3 extension is folding execution errors into the same retry
    path."""
    sql = state["candidate_sql"]
    try:
        conn = get_readonly_connection()
    except RuntimeError as e:
        return {"failed": True, "failure_reason": str(e), "columns": [], "rows": [], "row_count": 0}

    try:
        with conn.cursor() as cur:
            cur.execute(f"SET statement_timeout = {EXECUTION_TIMEOUT_MS}")
            cur.execute(sql)
            columns = [desc[0] for desc in cur.description]
            fetched = cur.fetchall()
            rows = [dict(zip(columns, row)) for row in fetched]
    except Exception as e:
        return {
            "failed": True,
            "failure_reason": f"Execution error against the read-only DB: {e}",
            "columns": [],
            "rows": [],
            "row_count": 0,
        }
    finally:
        conn.close()

    return {
        "executed_sql": sql,
        "columns": columns,
        "rows": rows[:MAX_DISPLAY_ROWS],
        "row_count": len(rows),
        "failed": False,
    }

@traced_node("execute_sql")
def execute_sql(state: AgentState) -> dict:
    """Runs validated SQL against the read-only Postgres role.

    SQL execution errors are returned as retryable feedback so the LLM
    can correct the query. Infrastructure/connection errors remain
    hard failures because retrying the SQL will not fix a database
    connectivity problem.
    """
    sql = state["candidate_sql"]

    try:
        conn = get_readonly_connection()
    except RuntimeError as e:
        return {
            "failed": True,
            "failure_reason": str(e),
            "columns": [],
            "rows": [],
            "row_count": 0,
        }

    try:
        with conn.cursor() as cur:
            cur.execute(f"SET statement_timeout = {EXECUTION_TIMEOUT_MS}")
            cur.execute(sql)

            columns = [desc[0] for desc in cur.description]
            fetched = cur.fetchall()
            rows = [dict(zip(columns, row)) for row in fetched]

    except Exception as e:
        return {
            "failed": False,
            "execution_error": f"Execution error against the read-only DB: {e}",
            "columns": [],
            "rows": [],
            "row_count": 0,
        }

    finally:
        conn.close()

    return {
        "executed_sql": sql,
        "columns": columns,
        "rows": rows[:MAX_DISPLAY_ROWS],
        "row_count": len(rows),
        "failed": False,
        "execution_error": None,
    }

# def route_after_execute(state: AgentState) -> str:
#     return "fail" if state.get("failed") else "summarize"

def route_after_execute(state: AgentState) -> str:
    """Route successful execution to summarization, but send retryable
    PostgreSQL execution errors back through SQL generation while retry
    budget remains.
    """
    if state.get("failed"):
        return "fail"

    if state.get("execution_error"):
        if state.get("retry_count", 0) >= MAX_RETRIES:
            return "fail"
        return "retry"

    return "summarize"

@traced_node("summarize")
def summarize(state: AgentState) -> dict:
    llm = get_llm()
    explanation = llm.summarize(
        question=state["question"],
        sql=state["executed_sql"],
        columns=state["columns"],
        rows=state["rows"],
        row_count=state["row_count"],
    )
    turn = {
        "question": state["question"],
        "sql": state["executed_sql"],
        "row_count": state["row_count"],
        "explanation": explanation,
    }
    history = state.get("conversation_history", []) + [turn]
    return {"explanation": explanation, "conversation_history": history}


# @traced_node("handle_failure")
# def handle_failure(state: AgentState) -> dict:
    reason = state.get("failure_reason") or state.get("validation_error") or "Unknown failure."
    explanation = (
        f"I couldn't produce a safe, executable query for that question "
        f"after {state.get('retry_count', 0) + 1} attempt(s). "
        f"Last error: {reason}"
    )
    turn = {
        "question": state["question"],
        "sql": state.get("candidate_sql", ""),
        "row_count": 0,
        "explanation": explanation,
    }
    history = state.get("conversation_history", []) + [turn]
    return {
        "failed": True,
        "failure_reason": reason,
        "explanation": explanation,
        "conversation_history": history,
    }

@traced_node("handle_failure")
def handle_failure(state: AgentState) -> dict:
    reason = (
        state.get("failure_reason")
        or state.get("execution_error")
        or state.get("validation_error")
        or "Unknown failure."
    )

    explanation = (
        f"I couldn't produce a safe, executable query for that question "
        f"after {state.get('retry_count', 0) + 1} attempt(s). "
        f"Last error: {reason}"
    )

    turn = {
        "question": state["question"],
        "sql": state.get("candidate_sql", ""),
        "row_count": 0,
        "explanation": explanation,
    }

    history = state.get("conversation_history", []) + [turn]

    return {
        "failed": True,
        "failure_reason": reason,
        "explanation": explanation,
        "conversation_history": history,
    }
