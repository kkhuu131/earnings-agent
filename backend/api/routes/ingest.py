"""POST /ingest — manually ingest a transcript into the backtest database.

This route exists because the primary transcript API (FMP) deprecated free-tier
access in August 2025, and SEC EDGAR does not carry transcripts for large-cap
companies. Ingestion lets users paste a transcript from any public source
(e.g. Motley Fool) via the frontend UI, storing it in the DB so the backtest
runner can process it.

Flow
----
1. Validate the request (ticker, filing_date, fiscal_quarter, transcript_text).
2. Insert a Transcript row.
3. Fetch the price snapshot for filing_date via yfinance.
4. Insert a PriceSnapshot row if price data is available.
5. Return a summary including whether the 30-day outcome is already known.
"""

import logging
import uuid

from fastapi import APIRouter, HTTPException

from backend.api.schemas import IngestRequest, IngestResponse
from backend.data.prices import get_price_snapshot
from backend.db.models import PriceSnapshot, Transcript
from backend.db.session import get_session

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/ingest", response_model=IngestResponse)
async def ingest(body: IngestRequest) -> IngestResponse:
    """Store a manually provided transcript and fetch its price snapshot.

    The transcript is saved to the ``transcripts`` table. A price snapshot
    (close price on filing_date and 30 days later) is fetched from yfinance
    and saved to ``price_snapshots`` if available. Both rows are required by
    the backtest runner to evaluate prediction accuracy.
    """
    ticker = body.ticker.upper().strip()
    word_count = len(body.transcript_text.split())

    if word_count < 100:
        raise HTTPException(
            status_code=422,
            detail=f"Transcript too short ({word_count} words). Paste the full earnings call text.",
        )

    transcript_id = uuid.uuid4()

    # Synthetic accession number so the populate script can de-duplicate later
    accession = f"manual-{ticker}-{body.fiscal_quarter.replace(' ', '-')}"

    async with get_session() as session:
        session.add(Transcript(
            id=transcript_id,
            ticker=ticker,
            fiscal_quarter=body.fiscal_quarter,
            filing_date=body.filing_date,
            transcript_text=body.transcript_text,
            edgar_accession_number=accession,
        ))

    logger.info("Ingested transcript %s %s (%d words)", ticker, body.fiscal_quarter, word_count)

    # Fetch price snapshot — non-fatal if unavailable
    price_snapshot_found = False
    actual_direction: str | None = None

    try:
        snap = await get_price_snapshot(ticker, body.filing_date)
        if snap.close_price is not None:
            async with get_session() as session:
                session.add(PriceSnapshot(
                    id=uuid.uuid4(),
                    ticker=snap.ticker,
                    snapshot_date=snap.snapshot_date,
                    close_price=snap.close_price,
                    price_30d_later=snap.price_30d_later,
                    actual_direction=snap.actual_direction,
                ))
            price_snapshot_found = True
            actual_direction = snap.actual_direction
            logger.info(
                "Price snapshot for %s on %s: %s",
                ticker, body.filing_date, actual_direction or "direction unknown (30d not yet elapsed)",
            )
        else:
            logger.warning("No price data found for %s on %s", ticker, body.filing_date)
    except Exception:
        logger.exception("Price snapshot fetch failed for %s on %s", ticker, body.filing_date)

    return IngestResponse(
        transcript_id=transcript_id,
        ticker=ticker,
        fiscal_quarter=body.fiscal_quarter,
        filing_date=body.filing_date,
        word_count=word_count,
        price_snapshot_found=price_snapshot_found,
        actual_direction=actual_direction,
    )
