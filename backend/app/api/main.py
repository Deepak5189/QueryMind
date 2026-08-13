"""
FastAPI backend for QueryMind -- Phase 3.

Wraps the Phase 2 LangGraph agent (`backend.app.agent.graph.get_graph()`)
behind a single POST /chat endpoint, the same contract `run_agent.py`
already exercises via the CLI: build an AgentState with `question` +
`conversation_history`, call `graph.invoke(state)`, read the result back
out. This file adds nothing to the agent itself -- it's routing and
session-state plumbing around what Phase 2 already proved works, per
Phase 2's own NEXT STEPS notes.

Run:
    uvicorn backend.app.api.main:app --reload --port 8000
"""

from __future__ import annotations

import logging
import os

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

load_dotenv()

from backend.app.agent.graph import get_graph  # noqa: E402
from backend.app.agent.tracing import configure_logging  # noqa: E402
from backend.app.api import sessions  # noqa: E402
from backend.app.api.schemas import ChatRequest, ChatResponse, HealthResponse, ResetResponse  # noqa: E402

configure_logging(verbose=os.environ.get("LOG_LEVEL", "INFO").upper() == "DEBUG")
logger = logging.getLogger("querymind.api")

app = FastAPI(
    title="QueryMind API",
    description="Natural-language-to-SQL analytics agent -- FastAPI layer around the Phase 2 LangGraph agent.",
    version="0.3.0",
)

# CORS for local Next.js dev (default `next dev` port is 3000). Configurable
# via FRONTEND_ORIGIN so a deployed frontend origin can be added later
# without code changes.
_default_origins = ["http://localhost:3000", "http://127.0.0.1:3000"]
_extra_origin = os.environ.get("FRONTEND_ORIGIN")
allow_origins = _default_origins + ([_extra_origin] if _extra_origin else [])

app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_graph = None


def _get_graph():
    # Lazy + cached: mirrors get_graph()'s own lazy-compile pattern, and
    # avoids compiling the graph (and importing psycopg2/pgvector/sqlglot)
    # at module import time, so `uvicorn ... --reload` stays fast and a
    # missing DB/API key only surfaces on the first real request, not on
    # `import backend.app.api.main`.
    global _graph
    if _graph is None:
        _graph = get_graph()
    return _graph


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok", llm_provider=os.environ.get("LLM_PROVIDER", "mock"))


@app.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest) -> ChatResponse:
    conversation_id = sessions.resolve_conversation_id(req.conversation_id)
    history = sessions.get_history(conversation_id)

    state = {"question": req.question, "conversation_history": history}

    try:
        graph = _get_graph()
        result = graph.invoke(state)
    except Exception as e:
        # A hard infra failure (DB unreachable, missing API key, etc.) --
        # distinct from a guardrail rejection, which the graph itself
        # already handles gracefully via handle_failure and returns as
        # failed=True below. This is the "something is actually broken"
        # path, so it's a 503, not a normal chat response.
        logger.exception("Unhandled error invoking agent graph")
        raise HTTPException(status_code=503, detail=f"Agent failed to run: {e}") from e

    # Persist whatever conversation_history the graph produced -- on
    # success this includes the just-completed turn; handle_failure also
    # appends a turn (with the failure explanation) so a rejected question
    # still shows up in history for context on the next follow-up.
    sessions.save_history(conversation_id, result.get("conversation_history", history))

    failed = bool(result.get("failed"))

    return ChatResponse(
        conversation_id=conversation_id,
        question=req.question,
        failed=failed,
        sql=result.get("executed_sql") if not failed else None,
        columns=result.get("columns", []) if not failed else [],
        rows=result.get("rows", []) if not failed else [],
        row_count=result.get("row_count", 0) if not failed else 0,
        explanation=result.get("explanation"),
        warning=result.get("failure_reason") if failed else None,
        last_candidate_sql=result.get("candidate_sql") if failed else None,
        retry_count=result.get("retry_count", 0),
    )


@app.post("/chat/reset/{conversation_id}", response_model=ResetResponse)
def reset(conversation_id: str) -> ResetResponse:
    """Clears server-side history for a conversation id (e.g. the
    frontend's "New chat" button) without needing a full restart."""
    sessions.reset_conversation(conversation_id)
    return ResetResponse(conversation_id=conversation_id, reset=True)
