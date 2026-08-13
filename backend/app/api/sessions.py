"""
In-memory conversation/session store for the FastAPI layer.

Phase 2's `conversation_history` already lives on AgentState as a plain
list of `{question, sql, row_count, explanation}` dicts -- exactly what
`nodes.py` reads and appends to on every turn. This module just needs to
keep that list alive *between* HTTP requests, keyed by a conversation id,
since each request is a fresh process-level call into `graph.invoke(...)`.

Deliberately a plain dict, not a DB table: the phase brief says "in-memory
or simple DB table" is fine, and a Postgres-backed session table is listed
explicitly as Phase 3+ scope in Phase 2's own NEXT STEPS notes -- so
starting here and swapping the storage backend later (same three methods)
is a smaller change than building persistence now for a single-process
dev backend that already restarts on every `uvicorn --reload`.
"""

from __future__ import annotations

import threading
import uuid
from typing import Optional

# conversation_id -> list[ConversationTurn]
_SESSIONS: dict[str, list[dict]] = {}
_LOCK = threading.Lock()


def new_conversation_id() -> str:
    return uuid.uuid4().hex


def get_history(conversation_id: str) -> list[dict]:
    with _LOCK:
        return list(_SESSIONS.get(conversation_id, []))


def save_history(conversation_id: str, history: list[dict]) -> None:
    with _LOCK:
        _SESSIONS[conversation_id] = history


def reset_conversation(conversation_id: str) -> None:
    with _LOCK:
        _SESSIONS.pop(conversation_id, None)


def resolve_conversation_id(conversation_id: Optional[str]) -> str:
    """Returns the id to use for this request, minting a new one if the
    client didn't send one (first message of a new chat)."""
    if conversation_id and conversation_id in _SESSIONS:
        return conversation_id
    if conversation_id:
        # Client sent an id we haven't seen (fresh server restart, or a
        # client-generated id) -- accept it as a new conversation rather
        # than silently minting a different one, so the frontend's id
        # stays stable across a backend restart during dev.
        with _LOCK:
            _SESSIONS.setdefault(conversation_id, [])
        return conversation_id
    new_id = new_conversation_id()
    with _LOCK:
        _SESSIONS[new_id] = []
    return new_id
