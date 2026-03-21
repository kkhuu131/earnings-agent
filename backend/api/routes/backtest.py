"""POST /backtest — run the backtesting pipeline over a historical date range.

Accepts a BacktestRequest (tickers + date range), delegates to
``run_backtest`` in the runner module, and returns a BacktestResponse with
aggregate accuracy metrics.
"""

import logging

from fastapi import APIRouter, HTTPException

from backend.api.schemas import BacktestRequest, BacktestResponse, TickerSummary
from backend.backtest.runner import run_backtest

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/backtest", response_model=BacktestResponse)
async def backtest(body: BacktestRequest) -> BacktestResponse:
    """Run the agent pipeline on all historical transcripts for the given tickers.

    1. Loads transcripts from the DB for each ticker within the date range.
    2. Matches each transcript to its PriceSnapshot.
    3. Calls ``run_pipeline`` for each transcript.
    4. Persists Prediction rows with ``actual_direction`` and ``was_correct``.
    5. Returns aggregate accuracy metrics.
    """
    try:
        summary = await run_backtest(
            tickers=body.tickers,
            start_date=body.start_date,
            end_date=body.end_date,
        )
    except Exception as exc:
        logger.exception("Backtest failed for tickers %s", body.tickers)
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return BacktestResponse(
        total=summary["total"],
        correct=summary["correct"],
        accuracy=summary["accuracy"],
        per_ticker={
            ticker: TickerSummary(
                total=ts["total"],
                correct=ts["correct"],
                accuracy=ts["accuracy"],
            )
            for ticker, ts in summary["per_ticker"].items()
        },
    )
