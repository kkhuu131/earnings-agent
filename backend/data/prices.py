"""Price data fetcher using yfinance.

Fetches historical closing prices and computes 30-day post-earnings direction
for backtesting. The direction label uses a 2% threshold to avoid noise:
  - "up"      price moved > +2 %
  - "down"    price moved < -2 %
  - "neutral" price moved within ±2 %

Usage:
    import asyncio
    from datetime import date
    from backend.data.prices import get_price_snapshot, get_price_range

    snap = asyncio.run(get_price_snapshot("NVDA", date(2024, 5, 22)))
    print(snap.close_price, snap.price_30d_later, snap.actual_direction)
"""

import asyncio
import logging
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional

import yfinance as yf

logger = logging.getLogger(__name__)

# Minimum % move required to call a direction (avoids noise near flat).
DIRECTION_THRESHOLD = 0.02  # 2 %

# Number of calendar days to look forward for the "30-day" price.
LOOKAHEAD_DAYS = 30

# When the exact target date is not a trading day we look up to this many
# additional calendar days ahead before giving up.
MAX_TRADING_DAY_SEARCH = 7


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class PriceSnapshot:
    ticker: str
    snapshot_date: date
    close_price: Optional[float]        # closing price on snapshot_date
    price_30d_later: Optional[float]    # closing price ~30 calendar days later
    actual_direction: Optional[str]     # "up" | "down" | "neutral"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _compute_direction(price_start: float, price_end: float) -> str:
    pct = (price_end - price_start) / price_start
    if pct > DIRECTION_THRESHOLD:
        return "up"
    if pct < -DIRECTION_THRESHOLD:
        return "down"
    return "neutral"


def _nearest_close(hist, target: date) -> Optional[float]:
    """Return the closing price on or after target within MAX_TRADING_DAY_SEARCH days."""
    for offset in range(MAX_TRADING_DAY_SEARCH + 1):
        candidate = target + timedelta(days=offset)
        # yfinance returns a DatetimeIndex; compare as date
        try:
            row = hist.loc[hist.index.date == candidate]  # type: ignore[attr-defined]
        except AttributeError:
            # Fallback for tz-aware index
            row = hist[hist.index.normalize().date == candidate]  # type: ignore[attr-defined]

        if not row.empty:
            val = row["Close"].values[0]
            # values[0] may itself be an array when yfinance uses MultiIndex columns
            if hasattr(val, "__len__"):
                val = val[0]
            return float(val)
    return None


def _fetch_snapshot_sync(ticker: str, snapshot_date: date) -> PriceSnapshot:
    """Synchronous core — runs inside an executor thread."""
    # Fetch a window that covers snapshot_date → snapshot_date + 30d + buffer
    start = snapshot_date - timedelta(days=5)   # small back-buffer for safety
    end = snapshot_date + timedelta(days=LOOKAHEAD_DAYS + MAX_TRADING_DAY_SEARCH + 2)

    try:
        hist = yf.download(
            ticker,
            start=start.isoformat(),
            end=end.isoformat(),
            auto_adjust=True,
            progress=False,
        )
    except Exception as exc:
        logger.error("yfinance download failed for %s: %s", ticker, exc)
        return PriceSnapshot(
            ticker=ticker.upper(),
            snapshot_date=snapshot_date,
            close_price=None,
            price_30d_later=None,
            actual_direction=None,
        )

    if hist.empty:
        logger.warning("No price data returned by yfinance for %s around %s", ticker, snapshot_date)
        return PriceSnapshot(
            ticker=ticker.upper(),
            snapshot_date=snapshot_date,
            close_price=None,
            price_30d_later=None,
            actual_direction=None,
        )

    close_price = _nearest_close(hist, snapshot_date)
    target_30d = snapshot_date + timedelta(days=LOOKAHEAD_DAYS)
    price_30d = _nearest_close(hist, target_30d)

    direction: Optional[str] = None
    if close_price is not None and price_30d is not None:
        direction = _compute_direction(close_price, price_30d)

    return PriceSnapshot(
        ticker=ticker.upper(),
        snapshot_date=snapshot_date,
        close_price=close_price,
        price_30d_later=price_30d,
        actual_direction=direction,
    )


def _fetch_range_sync(ticker: str, start: date, end: date) -> list[PriceSnapshot]:
    """Fetch all trading-day closes in [start, end] and compute 30d directions.

    The look-forward window requires price data beyond `end`, so we fetch an
    extended range and use it for both the snapshot prices and the 30d-later
    prices.
    """
    fetch_end = end + timedelta(days=LOOKAHEAD_DAYS + MAX_TRADING_DAY_SEARCH + 2)

    try:
        hist = yf.download(
            ticker,
            start=start.isoformat(),
            end=fetch_end.isoformat(),
            auto_adjust=True,
            progress=False,
        )
    except Exception as exc:
        logger.error("yfinance range download failed for %s: %s", ticker, exc)
        return []

    if hist.empty:
        logger.warning("No price data for %s between %s and %s", ticker, start, end)
        return []

    # Collect all trading days in the requested window
    try:
        trading_dates = [idx.date() for idx in hist.index if start <= idx.date() <= end]
    except AttributeError:
        trading_dates = [idx.date() for idx in hist.index if start <= idx.date() <= end]  # type: ignore[union-attr]

    snapshots: list[PriceSnapshot] = []
    for snap_date in trading_dates:
        close_price = _nearest_close(hist, snap_date)
        target_30d = snap_date + timedelta(days=LOOKAHEAD_DAYS)
        price_30d = _nearest_close(hist, target_30d)

        direction: Optional[str] = None
        if close_price is not None and price_30d is not None:
            direction = _compute_direction(close_price, price_30d)

        snapshots.append(
            PriceSnapshot(
                ticker=ticker.upper(),
                snapshot_date=snap_date,
                close_price=close_price,
                price_30d_later=price_30d,
                actual_direction=direction,
            )
        )

    logger.info("Fetched %d price snapshots for %s (%s → %s)", len(snapshots), ticker, start, end)
    return snapshots


# ---------------------------------------------------------------------------
# Public API (async wrappers)
# ---------------------------------------------------------------------------


async def get_price_snapshot(ticker: str, snapshot_date: date) -> PriceSnapshot:
    """Return closing price on snapshot_date and 30 calendar days later.

    Runs yfinance in a thread pool to keep the event loop unblocked.

    Args:
        ticker:        US equity ticker symbol (e.g. "NVDA").
        snapshot_date: The date of interest (typically an earnings filing date).

    Returns:
        PriceSnapshot with close_price, price_30d_later, and actual_direction.
        Fields are None when price data is unavailable (weekend, holiday, delisted).
    """
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _fetch_snapshot_sync, ticker, snapshot_date)


async def get_price_range(
    ticker: str,
    start: date,
    end: date,
) -> list[PriceSnapshot]:
    """Return PriceSnapshot for every trading day in [start, end].

    Useful for bulk-computing snapshots during backtesting without making
    one yfinance call per date.

    Args:
        ticker: US equity ticker symbol.
        start:  First date (inclusive).
        end:    Last date (inclusive).

    Returns:
        List of PriceSnapshot sorted chronologically. 30d-later prices near
        the end of the range will be None if the lookahead exceeds available data.
    """
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _fetch_range_sync, ticker, start, end)
