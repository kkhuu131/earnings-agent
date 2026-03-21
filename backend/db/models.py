"""SQLAlchemy ORM models for earnings-agent.

Uses the modern SQLAlchemy 2.x style:
  DeclarativeBase, Mapped, mapped_column — fully async-compatible via asyncpg.

Tables
------
transcripts       — Earnings call transcript text and metadata
price_snapshots   — Pre-computed price snapshots for backtesting
agent_reputation  — Per-agent accuracy scores and reputation weights
predictions       — Full prediction run records (inputs + outputs)
"""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.sql import func


class Base(DeclarativeBase):
    pass


# ---------------------------------------------------------------------------
# transcripts
# ---------------------------------------------------------------------------


class Transcript(Base):
    """Earnings call transcript fetched from SEC EDGAR."""

    __tablename__ = "transcripts"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    ticker: Mapped[str] = mapped_column(String(10), nullable=False)
    fiscal_quarter: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    filing_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    transcript_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    edgar_accession_number: Mapped[Optional[str]] = mapped_column(String(25), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


# ---------------------------------------------------------------------------
# price_snapshots
# ---------------------------------------------------------------------------


class PriceSnapshot(Base):
    """Pre-computed price data used by the backtesting runner."""

    __tablename__ = "price_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    ticker: Mapped[str] = mapped_column(String(10), nullable=False)
    snapshot_date: Mapped[date] = mapped_column(Date, nullable=False)
    close_price: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 4), nullable=True)
    price_30d_later: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 4), nullable=True)
    actual_direction: Mapped[Optional[str]] = mapped_column(String(5), nullable=True)


# ---------------------------------------------------------------------------
# agent_reputation
# ---------------------------------------------------------------------------


class AgentReputation(Base):
    """Accuracy scores and reputation weights for each analytical agent.

    Updated after every backtest run. The weight column is normalised so that
    all weights sum to 1.0 across active agents.
    """

    __tablename__ = "agent_reputation"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    agent_name: Mapped[str] = mapped_column(String(50), nullable=False)
    correct_predictions: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_predictions: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    accuracy: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 4), nullable=True)
    weight: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 4), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


# ---------------------------------------------------------------------------
# predictions
# ---------------------------------------------------------------------------


class Prediction(Base):
    """Full record of one prediction run — inputs, outputs, and backtest result.

    agent_reports, debate_transcript, and weighted_signals are stored as JSONB
    so the full LLM payloads can be queried without a fixed schema.
    """

    __tablename__ = "predictions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    ticker: Mapped[str] = mapped_column(String(10), nullable=False)
    transcript_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("transcripts.id"), nullable=True
    )
    run_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    final_direction: Mapped[Optional[str]] = mapped_column(String(5), nullable=True)
    final_confidence: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 4), nullable=True)
    final_reasoning: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    agent_reports: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    debate_transcript: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    weighted_signals: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    actual_direction: Mapped[Optional[str]] = mapped_column(String(5), nullable=True)
    was_correct: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
