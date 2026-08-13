"""
Shared state schema for the QueryMind LangGraph agent.

LangGraph threads a single mutable dict-like object (an AgentState) through
every node. Each node reads what it needs and returns a partial dict of
updates, which LangGraph merges into the state before calling the next
node. Defining the shape up front (rather than passing loose kwargs)
is what makes every node's input/output independently inspectable --
which matters for the tracing/logging requirement in this phase.
"""

from __future__ import annotations

from typing import Optional, TypedDict


class RetrievedDoc(TypedDict):
    doc_type: str  # "table" | "glossary"
    title: str
    content: str
    similarity: float


class ConversationTurn(TypedDict):
    """One completed turn, kept so follow-up questions can refer back to it."""

    question: str
    sql: str
    row_count: int
    explanation: str


class AgentState(TypedDict, total=False):
    # ---- input for this turn ----
    question: str  # raw NL question for the current turn
    conversation_history: list[ConversationTurn]  # prior turns, oldest first

    # ---- retrieval ----
    retrieved_context: list[RetrievedDoc]

    # # ---- generate -> validate retry loop ----
    # candidate_sql: str
    # validation_error: Optional[str]
    # retry_count: int
    # is_valid: bool

    # ---- generate -> validate -> execute retry loop ----
    candidate_sql: str
    validation_error: Optional[str]
    execution_error: Optional[str]
    retry_count: int
    is_valid: bool

    # ---- execution ----
    executed_sql: str  # the validated SQL actually run (LIMIT-enforced)
    columns: list[str]
    rows: list[dict]
    row_count: int

    # ---- output ----
    explanation: str
    failed: bool  # True if the guardrail rejected every attempt
    failure_reason: Optional[str]
