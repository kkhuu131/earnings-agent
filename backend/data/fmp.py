"""Financial Modeling Prep (FMP) transcript fetcher.

Fetches earnings call transcripts from the FMP API, which covers most S&P 500
companies going back several years. Returns the same TranscriptResult type as
edgar.py so the rest of the pipeline is source-agnostic.

Current status (as of March 2026)
----------------------------------
FMP deprecated all earnings call transcript endpoints on August 31 2025. They
are now classified as "Legacy Endpoints" and are only accessible to users who
held a valid paid subscription before that date. New accounts — including free
tier — receive HTTP 403 on all transcript requests.

This module is kept because:
  - The code is correct and will work if/when FMP restores access or introduces
    a replacement endpoint.
  - Paid legacy subscribers can use it immediately by setting FMP_API_KEY.
  - The architecture (FMP first, EDGAR fallback) in populate_db.py is right.

If you do not have a legacy FMP subscription, use the Ingest page
(frontend/app/ingest/page.tsx) to manually seed the backtest database instead.

Note on FMP tiers
-----------------
The v4 transcript *listing* endpoint requires a paid plan. This module uses
only the free-tier v3 endpoint, which fetches a specific quarter by number:

    GET /api/v3/earning_call_transcript/{SYMBOL}?quarter={Q}&year={Y}&apikey={KEY}

We discover available transcripts by iterating backwards through recent quarters
and collecting whichever ones return content. This costs one API call per quarter
tried (up to ``limit * 2`` attempts), which is well within the 250 req/day limit
for a typical seeding run.

Usage:
    import asyncio
    from backend.data.fmp import fetch_transcripts

    results = asyncio.run(fetch_transcripts("AAPL", api_key="YOUR_KEY", limit=5))
    for r in results:
        print(r.ticker, r.fiscal_quarter, r.word_count)
"""

import asyncio
import logging
from datetime import UTC, date, datetime
from typing import Optional

import httpx

from backend.data.edgar import TranscriptResult

logger = logging.getLogger(__name__)

FMP_BASE = "https://financialmodelingprep.com/api"

# FMP free tier: stay well under their rate limit
_REQUEST_DELAY = 0.25  # seconds between requests

# Reject transcripts shorter than this — filters empty/stub API responses
_MIN_WORDS = 500


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _recent_quarters(n: int) -> list[tuple[int, int]]:
    """Return the last *n* (quarter, year) pairs, newest first."""
    now = datetime.now(UTC)
    q = (now.month - 1) // 3 + 1
    y = now.year
    pairs: list[tuple[int, int]] = []
    for _ in range(n):
        pairs.append((q, y))
        q -= 1
        if q == 0:
            q = 4
            y -= 1
    return pairs


def _parse_fmp_date(date_str: str) -> date:
    """Parse FMP date strings: '2024-02-02 16:30:00' or '2024-02-02'."""
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(date_str, fmt).date()
        except (ValueError, TypeError):
            continue
    return date.today()


def _quarter_label(quarter: int, year: int) -> str:
    return f"Q{quarter} {year}"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def fetch_transcripts(
    ticker: str,
    api_key: str,
    limit: int = 10,
) -> list[TranscriptResult]:
    """Fetch the most recent earnings call transcripts for a ticker from FMP.

    Uses the free-tier v3 endpoint only. Iterates backwards through recent
    quarters, fetching each one until ``limit`` transcripts are collected.

    Args:
        ticker:  US equity ticker symbol (e.g. "AAPL", "NVDA").
        api_key: FMP API key (free tier works).
        limit:   Maximum number of transcripts to return (default 10).

    Returns:
        List of TranscriptResult sorted by filing_date descending.
        Returns an empty list when the API key is missing/invalid or the
        ticker has no FMP coverage.
    """
    if not api_key:
        logger.warning("FMP_API_KEY not set — skipping FMP fetch for %s", ticker)
        return []

    symbol = ticker.upper()
    # Try up to limit*2 quarters to find limit valid transcripts
    quarters_to_try = _recent_quarters(limit * 2)
    content_url = f"{FMP_BASE}/v3/earning_call_transcript/{symbol}"

    results: list[TranscriptResult] = []

    async with httpx.AsyncClient(
        timeout=httpx.Timeout(30.0, connect=10.0),
        follow_redirects=True,
    ) as client:
        for quarter, year in quarters_to_try:
            if len(results) >= limit:
                break

            await asyncio.sleep(_REQUEST_DELAY)
            try:
                resp = await client.get(
                    content_url,
                    params={"quarter": quarter, "year": year, "apikey": api_key},
                )
                resp.raise_for_status()
                data = resp.json()
            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code
                if status == 403:
                    logger.error(
                        "FMP returned 403 for %s Q%s %s — check your API key at "
                        "financialmodelingprep.com (free tier supported)",
                        symbol, quarter, year,
                    )
                    # 403 on the first attempt means the key is bad — abort early
                    if not results:
                        break
                    continue
                elif status == 404:
                    logger.debug("FMP: no transcript for %s Q%s %s", symbol, quarter, year)
                    continue
                else:
                    logger.warning("FMP HTTP %s for %s Q%s %s", status, symbol, quarter, year)
                    continue
            except Exception as exc:
                logger.warning("FMP request error for %s Q%s %s: %s", symbol, quarter, year, exc)
                continue

            if not isinstance(data, list) or not data:
                logger.debug("FMP: empty response for %s Q%s %s", symbol, quarter, year)
                continue

            entry = data[0]
            content: str = entry.get("content", "") or ""
            word_count = len(content.split())

            if word_count < _MIN_WORDS:
                logger.debug(
                    "FMP: transcript too short for %s Q%s %s (%d words) — skipping",
                    symbol, quarter, year, word_count,
                )
                continue

            filing_date = _parse_fmp_date(entry.get("date", ""))

            results.append(
                TranscriptResult(
                    ticker=symbol,
                    company_name=symbol,
                    filing_date=filing_date,
                    fiscal_quarter=_quarter_label(quarter, year),
                    accession_number=f"fmp-{symbol}-Q{quarter}-{year}",
                    transcript_text=content,
                    word_count=word_count,
                )
            )
            logger.info(
                "FMP: fetched %s Q%s %s (%d words) from %s",
                symbol, quarter, year, word_count, filing_date,
            )

    results.sort(key=lambda r: r.filing_date, reverse=True)
    return results[:limit]
