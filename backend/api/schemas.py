"""Pydantic request/response schemas for the earnings-agent API.

All schemas use strict types so invalid payloads are rejected at the
FastAPI validation layer before any agent or database code runs.
"""

import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


# ---------------------------------------------------------------------------
# POST /analyze
# ---------------------------------------------------------------------------


class AnalyzeRequest(BaseModel):
    """Payload for a single earnings analysis run."""

    ticker: str
    transcript: str
    price_data: dict


class AnalyzeResponse(BaseModel):
    """Returned after a successful analysis run."""

    prediction_id: uuid.UUID
    ticker: str
    run_date: datetime
    direction: str
    confidence: float
    reasoning: str
    weighted_signals: dict


# ---------------------------------------------------------------------------
# GET /predictions
# ---------------------------------------------------------------------------


class PredictionRecord(BaseModel):
    """Full prediction row returned by the history endpoint."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    ticker: str
    run_date: datetime
    final_direction: Optional[str] = None
    final_confidence: Optional[float] = None
    final_reasoning: Optional[str] = None
    agent_reports: Optional[dict] = None
    debate_transcript: Optional[dict] = None
    weighted_signals: Optional[dict] = None
    actual_direction: Optional[str] = None
    was_correct: Optional[bool] = None
