"""GET /transcripts and PATCH /transcripts/{id}/date — transcript management routes.

GET /transcripts
    Returns all ingested transcript rows with their price snapshot status.
    Used by the frontend to display the transcript list on the Ingest page.

PATCH /transcripts/{id}/date
    Updates the filing_date on an existing transcript and re-fetches the price
    snapshot for the new date. Useful when the wrong date was entered (e.g.
    using the announcement date instead of the next trading day for after-close
    earnings).
"""

import logging
import uuid
from typing import Optional

from fastapi import APIRouter, HTTPException
from sqlalchemy import delete, select

from backend.api.schemas import TranscriptRecord, UpdateDateRequest, UpdateDateResponse
from backend.data.prices import get_price_snapshot
from backend.db.models import PriceSnapshot, Transcript
from backend.db.session import get_session

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/transcripts", response_model=list[TranscriptRecord])
async def list_transcripts() -> list[TranscriptRecord]:
    """Return all ingested transcripts with price snapshot status, newest first."""
    async with get_session() as session:
        stmt = select(Transcript).order_by(Transcript.filing_date.desc().nullslast())
        result = await session.execute(stmt)
        transcripts = result.scalars().all()

        if not transcripts:
            return []

        # Fetch all relevant price snapshots in one query
        tickers = list({t.ticker for t in transcripts})
        snap_stmt = select(PriceSnapshot).where(PriceSnapshot.ticker.in_(tickers))
        snap_result = await session.execute(snap_stmt)
        snapshots = snap_result.scalars().all()

    # Index by (ticker, snapshot_date) for O(1) lookup
    snap_index: dict[tuple[str, object], PriceSnapshot] = {
        (s.ticker, s.snapshot_date): s for s in snapshots
    }

    records: list[TranscriptRecord] = []
    for t in transcripts:
        snap: Optional[PriceSnapshot] = snap_index.get((t.ticker, t.filing_date))
        word_count = len(t.transcript_text.split()) if t.transcript_text else None
        records.append(TranscriptRecord(
            id=t.id,
            ticker=t.ticker,
            fiscal_quarter=t.fiscal_quarter,
            filing_date=t.filing_date,
            word_count=word_count,
            price_snapshot_found=snap is not None and snap.close_price is not None,
            actual_direction=snap.actual_direction if snap else None,
        ))

    return records


@router.patch("/transcripts/{transcript_id}/date", response_model=UpdateDateResponse)
async def update_transcript_date(
    transcript_id: uuid.UUID,
    body: UpdateDateRequest,
) -> UpdateDateResponse:
    """Update a transcript's filing date and refresh its price snapshot.

    Deletes any existing PriceSnapshot for the old (ticker, old_date) pair if
    no other transcript references it, then fetches and inserts a snapshot for
    the new date.
    """
    async with get_session() as session:
        stmt = select(Transcript).where(Transcript.id == transcript_id)
        result = await session.execute(stmt)
        transcript = result.scalar_one_or_none()

        if transcript is None:
            raise HTTPException(status_code=404, detail="Transcript not found")

        old_date = transcript.filing_date
        ticker = transcript.ticker

        # Update the filing date
        transcript.filing_date = body.filing_date

        # Remove old price snapshot for this (ticker, old_date) — only if no
        # other transcript still uses that date
        if old_date and old_date != body.filing_date:
            other_stmt = (
                select(Transcript)
                .where(Transcript.ticker == ticker)
                .where(Transcript.filing_date == old_date)
                .where(Transcript.id != transcript_id)
            )
            other_result = await session.execute(other_stmt)
            still_referenced = other_result.scalar_one_or_none() is not None

            if not still_referenced:
                del_stmt = delete(PriceSnapshot).where(
                    PriceSnapshot.ticker == ticker,
                    PriceSnapshot.snapshot_date == old_date,
                )
                await session.execute(del_stmt)

    logger.info(
        "Updated transcript %s filing_date: %s → %s",
        transcript_id, old_date, body.filing_date,
    )

    # Fetch new price snapshot (outside the session so it doesn't block DB)
    price_snapshot_found = False
    actual_direction: Optional[str] = None

    try:
        snap = await get_price_snapshot(ticker, body.filing_date)
        if snap.close_price is not None:
            async with get_session() as session:
                # Only insert if not already present for this (ticker, date)
                existing_stmt = select(PriceSnapshot).where(
                    PriceSnapshot.ticker == ticker,
                    PriceSnapshot.snapshot_date == body.filing_date,
                )
                existing_result = await session.execute(existing_stmt)
                existing = existing_result.scalar_one_or_none()

                if existing is None:
                    session.add(PriceSnapshot(
                        id=uuid.uuid4(),
                        ticker=snap.ticker,
                        snapshot_date=snap.snapshot_date,
                        close_price=snap.close_price,
                        price_30d_later=snap.price_30d_later,
                        actual_direction=snap.actual_direction,
                    ))
                else:
                    # Update in place
                    existing.close_price = snap.close_price
                    existing.price_30d_later = snap.price_30d_later
                    existing.actual_direction = snap.actual_direction

            price_snapshot_found = True
            actual_direction = snap.actual_direction
            logger.info(
                "Price snapshot refreshed for %s on %s: %s",
                ticker, body.filing_date, actual_direction or "direction pending",
            )
        else:
            logger.warning("No price data for %s on %s", ticker, body.filing_date)
    except Exception:
        logger.exception(
            "Price snapshot fetch failed for %s on %s", ticker, body.filing_date
        )

    return UpdateDateResponse(
        transcript_id=transcript_id,
        filing_date=body.filing_date,
        price_snapshot_found=price_snapshot_found,
        actual_direction=actual_direction,
    )
