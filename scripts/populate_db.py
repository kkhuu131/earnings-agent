"""DB population script — fetches transcripts + price snapshots and inserts them.

Tries FMP first (broad S&P 500 coverage), falls back to EDGAR (works for some
smaller companies that file transcripts directly with the SEC).

Run from the repo root after adding your FMP_API_KEY to .env:

    python scripts/populate_db.py

Edit TICKERS below. Run scripts/recon.py first to confirm coverage.
The script is idempotent — it skips records already in the DB (matched by
accession number for transcripts, ticker + date for price snapshots).
"""

import asyncio
import logging
import uuid
from datetime import date

from sqlalchemy import select

from backend.config import settings
from backend.data.edgar import TranscriptResult, fetch_transcripts as edgar_fetch
from backend.data.fmp import fetch_transcripts as fmp_fetch
from backend.data.prices import get_price_snapshot
from backend.db.models import PriceSnapshot, Transcript
from backend.db.session import get_session

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
logger = logging.getLogger(__name__)

# ── Edit this list ────────────────────────────────────────────────────────────
TICKERS: list[str] = [
    # Add tickers confirmed by scripts/recon.py
    # e.g. "AAPL", "NVDA", "MSFT", "META", "JPM"
]

# Transcripts to fetch per ticker (more = stronger reputation signal, more API calls)
TRANSCRIPTS_PER_TICKER = 10
# ─────────────────────────────────────────────────────────────────────────────


async def _accession_exists(session, accession_number: str) -> bool:
    result = await session.execute(
        select(Transcript).where(Transcript.edgar_accession_number == accession_number)
    )
    return result.scalar_one_or_none() is not None


async def _snapshot_exists(session, ticker: str, snapshot_date: date) -> bool:
    result = await session.execute(
        select(PriceSnapshot).where(
            PriceSnapshot.ticker == ticker,
            PriceSnapshot.snapshot_date == snapshot_date,
        )
    )
    return result.scalar_one_or_none() is not None


async def _fetch(ticker: str) -> list[TranscriptResult]:
    """Try FMP first; fall back to EDGAR if FMP returns nothing."""
    if settings.fmp_api_key:
        results = await fmp_fetch(ticker, api_key=settings.fmp_api_key, limit=TRANSCRIPTS_PER_TICKER)
        if results:
            logger.info("%s: FMP returned %d transcript(s)", ticker, len(results))
            return results
        logger.info("%s: FMP returned nothing — trying EDGAR", ticker)
    else:
        logger.warning("FMP_API_KEY not set — skipping FMP, trying EDGAR only")

    results = await edgar_fetch(ticker, limit=TRANSCRIPTS_PER_TICKER)
    if results:
        logger.info("%s: EDGAR returned %d transcript(s)", ticker, len(results))
    else:
        logger.warning("%s: no transcripts found in FMP or EDGAR", ticker)
    return results


async def populate():
    if not TICKERS:
        print("No tickers configured. Edit the TICKERS list in scripts/populate_db.py.")
        print("Run scripts/recon.py first to confirm which tickers have coverage.")
        return

    total_transcripts = 0
    total_snapshots = 0

    for ticker in TICKERS:
        logger.info("── %s ──────────────────────────────", ticker)

        try:
            transcripts = await _fetch(ticker)
        except Exception:
            logger.exception("Fetch failed for %s — skipping", ticker)
            continue

        if not transcripts:
            continue

        for t in transcripts:
            # ── Transcript row ───────────────────────────────────────────────
            async with get_session() as session:
                if await _accession_exists(session, t.accession_number):
                    logger.info("  %s %s — transcript already in DB, skipping", ticker, t.fiscal_quarter)
                    continue
                session.add(Transcript(
                    id=uuid.uuid4(),
                    ticker=t.ticker,
                    fiscal_quarter=t.fiscal_quarter,
                    filing_date=t.filing_date,
                    transcript_text=t.transcript_text,
                    edgar_accession_number=t.accession_number,
                ))
                total_transcripts += 1
                logger.info("  inserted transcript: %s %s (%d words)", ticker, t.fiscal_quarter, t.word_count)

            # ── Price snapshot row ───────────────────────────────────────────
            if t.filing_date is None:
                logger.warning("  %s %s has no filing_date — skipping price snapshot", ticker, t.fiscal_quarter)
                continue

            async with get_session() as session:
                if await _snapshot_exists(session, t.ticker, t.filing_date):
                    logger.info("  price snapshot %s %s — already in DB, skipping", ticker, t.filing_date)
                    continue

            try:
                snap = await get_price_snapshot(t.ticker, t.filing_date)
            except Exception:
                logger.exception("  get_price_snapshot failed for %s %s — skipping", ticker, t.filing_date)
                continue

            if snap.close_price is None:
                logger.warning("  no price data for %s on %s — skipping snapshot", ticker, t.filing_date)
                continue

            async with get_session() as session:
                session.add(PriceSnapshot(
                    id=uuid.uuid4(),
                    ticker=snap.ticker,
                    snapshot_date=snap.snapshot_date,
                    close_price=snap.close_price,
                    price_30d_later=snap.price_30d_later,
                    actual_direction=snap.actual_direction,
                ))
                total_snapshots += 1
                logger.info(
                    "  inserted snapshot: %s %s → %s (30d: %s)",
                    ticker, t.filing_date,
                    snap.actual_direction or "unknown",
                    f"${snap.price_30d_later:.2f}" if snap.price_30d_later else "N/A",
                )

    print(f"\nDone. Inserted {total_transcripts} transcript(s) and {total_snapshots} price snapshot(s).")
    if total_transcripts > 0:
        print("You can now run POST /api/v1/backtest with the tickers above.")


if __name__ == "__main__":
    asyncio.run(populate())
