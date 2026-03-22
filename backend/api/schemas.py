"""Pydantic request/response schemas for the earnings-agent API.

All schemas use strict types so invalid payloads are rejected at the
FastAPI validation layer before any agent or database code runs.
"""

import uuid
from datetime import date, datetime
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
    debate_transcript: Optional[list] = None


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
    debate_transcript: Optional[list] = None
    weighted_signals: Optional[dict] = None
    actual_direction: Optional[str] = None
    was_correct: Optional[bool] = None


# ---------------------------------------------------------------------------
# POST /backtest
# ---------------------------------------------------------------------------


class BacktestRequest(BaseModel):
    """Payload for a historical backtest run."""

    tickers: list[str]
    start_date: date
    end_date: date


class TickerSummary(BaseModel):
    """Per-ticker accuracy breakdown within a BacktestResponse."""

    total: int
    correct: int
    accuracy: float


class BacktestResponse(BaseModel):
    """Returned after a successful backtest run."""

    total: int
    correct: int
    accuracy: float
    per_ticker: dict[str, TickerSummary]


# ---------------------------------------------------------------------------
# POST /ingest
# ---------------------------------------------------------------------------


class IngestRequest(BaseModel):
    """Payload for manually ingesting a transcript into the backtest database."""

    ticker: str
    fiscal_quarter: str          # e.g. "Q1 2025"
    filing_date: date            # earnings release date — used to fetch 30d price
    transcript_text: str


class IngestResponse(BaseModel):
    """Returned after a successful transcript ingestion."""

    transcript_id: uuid.UUID
    ticker: str
    fiscal_quarter: str
    filing_date: date
    word_count: int
    price_snapshot_found: bool
    actual_direction: Optional[str] = None  # "up" | "down" | "neutral" | None


# ---------------------------------------------------------------------------
# GET /transcripts  +  PATCH /transcripts/{id}/date
# ---------------------------------------------------------------------------


class TranscriptRecord(BaseModel):
    """Summary of an ingested transcript row, including price snapshot status."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    ticker: str
    fiscal_quarter: Optional[str] = None
    filing_date: Optional[date] = None
    word_count: Optional[int] = None      # computed from transcript_text length
    price_snapshot_found: bool = False
    actual_direction: Optional[str] = None


class UpdateDateRequest(BaseModel):
    """Payload for updating a transcript's filing date and refreshing its price snapshot."""

    filing_date: date


class UpdateDateResponse(BaseModel):
    """Returned after a successful date update and price snapshot refresh."""

    transcript_id: uuid.UUID
    filing_date: date
    price_snapshot_found: bool
    actual_direction: Optional[str] = None


# ---------------------------------------------------------------------------
# GET /reputation
# ---------------------------------------------------------------------------


class AgentReputationRecord(BaseModel):
    """Single agent row from the agent_reputation table."""

    model_config = ConfigDict(from_attributes=True)

    agent_name: str
    correct_predictions: int
    total_predictions: int
    accuracy: float
    weight: float
