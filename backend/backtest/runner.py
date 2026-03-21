"""Backtesting runner for the earnings-agent pipeline.

For a given set of tickers and date range, this module:

1. Loads all Transcript rows from the DB that fall within the date range.
2. For each transcript, finds the matching PriceSnapshot (same ticker,
   snapshot_date == transcript.filing_date).
3. Calls run_pipeline(transcript_text, price_data) to get a prediction.
4. Persists a Prediction row with actual_direction and was_correct filled in.
5. Returns a BacktestSummary dict with aggregate accuracy metrics.

No real network calls are made here — transcript and price data are read from
the database, and run_pipeline is the only external dependency (mockable in
tests via ``unittest.mock``).
"""

import logging
import uuid
from datetime import date, datetime, timezone
from typing import TypedDict

from sqlalchemy import select

from backend.backtest.reputation import update_reputation
from backend.db.models import Prediction, PriceSnapshot, Transcript
from backend.db.session import get_session
from backend.graph.earnings_graph import run_pipeline

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Return type
# ---------------------------------------------------------------------------


class TickerSummary(TypedDict):
    total: int
    correct: int
    accuracy: float


class BacktestSummary(TypedDict):
    total: int
    correct: int
    accuracy: float
    per_ticker: dict[str, TickerSummary]


# ---------------------------------------------------------------------------
# Core runner
# ---------------------------------------------------------------------------


async def run_backtest(
    tickers: list[str],
    start_date: date,
    end_date: date,
) -> BacktestSummary:
    """Run the full pipeline on all historical transcripts for *tickers*.

    Args:
        tickers: List of ticker symbols to back-test (upper-cased internally).
        start_date: Inclusive start of the filing_date range to scan.
        end_date: Inclusive end of the filing_date range to scan.

    Returns:
        A :class:`BacktestSummary` with overall and per-ticker accuracy.
    """
    upper_tickers = [t.upper() for t in tickers]

    total = 0
    correct = 0
    per_ticker: dict[str, TickerSummary] = {}

    if not upper_tickers:
        return BacktestSummary(total=0, correct=0, accuracy=0.0, per_ticker={})

    async with get_session() as session:
        # Load all transcripts in scope
        stmt = (
            select(Transcript)
            .where(Transcript.ticker.in_(upper_tickers))
            .where(Transcript.filing_date >= start_date)
            .where(Transcript.filing_date <= end_date)
            .order_by(Transcript.filing_date)
        )
        result = await session.execute(stmt)
        transcripts = result.scalars().all()

        if not transcripts:
            return BacktestSummary(total=0, correct=0, accuracy=0.0, per_ticker={})

        # Load all relevant price snapshots in one query
        snap_stmt = (
            select(PriceSnapshot)
            .where(PriceSnapshot.ticker.in_(upper_tickers))
            .where(PriceSnapshot.snapshot_date >= start_date)
            .where(PriceSnapshot.snapshot_date <= end_date)
        )
        snap_result = await session.execute(snap_stmt)
        snapshots = snap_result.scalars().all()

    # Index snapshots by (ticker, snapshot_date) for O(1) lookup
    snap_index: dict[tuple[str, date], PriceSnapshot] = {
        (s.ticker, s.snapshot_date): s for s in snapshots
    }

    for transcript in transcripts:
        ticker = transcript.ticker
        filing_date = transcript.filing_date

        snapshot = snap_index.get((ticker, filing_date))
        if snapshot is None:
            logger.warning(
                "No PriceSnapshot for %s on %s — skipping transcript %s",
                ticker,
                filing_date,
                transcript.id,
            )
            continue

        if not transcript.transcript_text:
            logger.warning(
                "Transcript %s for %s has no text — skipping",
                transcript.id,
                ticker,
            )
            continue

        # Build price_data dict for the TechnicalAnalyst (matches prices.py output)
        price_data: dict = {
            "ticker": ticker,
            "snapshot_date": str(filing_date),
            "close_price": float(snapshot.close_price) if snapshot.close_price is not None else None,
            "price_30d_later": float(snapshot.price_30d_later) if snapshot.price_30d_later is not None else None,
            "actual_direction": snapshot.actual_direction,
        }

        try:
            pipeline_result = await run_pipeline(transcript.transcript_text, price_data)
        except Exception:
            logger.exception(
                "Pipeline failed for %s transcript %s — skipping",
                ticker,
                transcript.id,
            )
            continue

        predicted_direction = pipeline_result.get("direction")
        actual_direction = snapshot.actual_direction
        was_correct: bool | None = None
        if predicted_direction is not None and actual_direction is not None:
            was_correct = predicted_direction == actual_direction

        record = Prediction(
            id=uuid.uuid4(),
            ticker=ticker,
            transcript_id=transcript.id,
            run_date=datetime.now(timezone.utc),
            final_direction=predicted_direction,
            final_confidence=pipeline_result.get("confidence"),
            final_reasoning=pipeline_result.get("reasoning"),
            agent_reports=pipeline_result.get("agent_reports"),
            debate_transcript=pipeline_result.get("debate_transcript"),
            weighted_signals=pipeline_result.get("weighted_signals"),
            actual_direction=actual_direction,
            was_correct=was_correct,
        )

        async with get_session() as session:
            session.add(record)

        # Accumulate counters
        total += 1
        if was_correct:
            correct += 1

        ticker_stats = per_ticker.setdefault(
            ticker, TickerSummary(total=0, correct=0, accuracy=0.0)
        )
        ticker_stats["total"] += 1
        if was_correct:
            ticker_stats["correct"] += 1
        ticker_stats["accuracy"] = (
            ticker_stats["correct"] / ticker_stats["total"]
        )

    overall_accuracy = correct / total if total > 0 else 0.0

    if total > 0:
        await update_reputation()

    return BacktestSummary(
        total=total,
        correct=correct,
        accuracy=overall_accuracy,
        per_ticker=per_ticker,
    )
