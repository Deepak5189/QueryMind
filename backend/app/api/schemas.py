"""Pydantic models for the /chat endpoint."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    question: str = Field(..., min_length=1, description="Natural-language question")
    conversation_id: Optional[str] = Field(
        None, description="Omit on the first message of a new chat; echo it back on every follow-up."
    )


class ChatResponse(BaseModel):
    conversation_id: str
    question: str
    failed: bool

    # populated when failed == False
    sql: Optional[str] = None
    columns: list[str] = []
    rows: list[dict] = []
    row_count: int = 0
    explanation: Optional[str] = None

    # populated when failed == True (guardrail rejection or execution error)
    warning: Optional[str] = None
    last_candidate_sql: Optional[str] = None

    retry_count: int = 0


class ResetResponse(BaseModel):
    conversation_id: str
    reset: bool


class HealthResponse(BaseModel):
    status: str
    llm_provider: str
