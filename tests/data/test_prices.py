"""Unit tests for backend/data/prices.py.

yfinance.download is patched to return controlled DataFrames so no network
access is required.
"""

from datetime import date, timedelta
from unittest.mock import patch

import pandas as pd
import pytest

from backend.data.prices import (
    DIRECTION_THRESHOLD,
    LOOKAHEAD_DAYS,
    MAX_TRADING_DAY_SEARCH,
    PriceSnapshot,
    _compute_direction,
    _fetch_range_sync,
    _fetch_snapshot_sync,
    _nearest_close,
    get_price_range,
    get_price_snapshot,
)

# ---------------------------------------------------------------------------
# DataFrame helpers
# ---------------------------------------------------------------------------


def make_price_df(dates: list, closes: list) -> pd.DataFrame:
    """Return a minimal yfinance-style DataFrame with a DatetimeIndex."""
    idx = pd.DatetimeIndex([pd.Timestamp(d) for d in dates])
    return pd.DataFrame(
        {
            "Close": [float(c) for c in closes],
            "High": [float(c) for c in closes],
            "Low": [float(c) for c in closes],
            "Open": [float(c) for c in closes],
            "Volume": [1_000_000] * len(closes),
        },
        index=idx,
    )


def make_snapshot_df(snapshot_date: date, close: float, price_30d: float) -> pd.DataFrame:
    """Two-row DataFrame: snapshot_date and 30 calendar days later."""
    target = snapshot_date + timedelta(days=LOOKAHEAD_DAYS)
    return make_price_df([snapshot_date, target], [close, price_30d])


# ---------------------------------------------------------------------------
# _compute_direction
# ---------------------------------------------------------------------------


class TestComputeDirection:
    def test_up_above_threshold(self):
        pct = DIRECTION_THRESHOLD + 0.01          # 3 % if threshold is 2 %
        assert _compute_direction(100.0, 100.0 * (1 + pct)) == "up"

    def test_down_below_threshold(self):
        pct = DIRECTION_THRESHOLD + 0.01
        assert _compute_direction(100.0, 100.0 * (1 - pct)) == "down"

    def test_neutral_within_positive_threshold(self):
        pct = DIRECTION_THRESHOLD - 0.005         # just inside the band
        assert _compute_direction(100.0, 100.0 * (1 + pct)) == "neutral"

    def test_neutral_within_negative_threshold(self):
        pct = DIRECTION_THRESHOLD - 0.005
        assert _compute_direction(100.0, 100.0 * (1 - pct)) == "neutral"

    def test_exactly_at_positive_threshold_is_neutral(self):
        # price_end == price_start * (1 + threshold) → pct == threshold → NOT > threshold
        price_end = 100.0 * (1 + DIRECTION_THRESHOLD)
        assert _compute_direction(100.0, price_end) == "neutral"

    def test_exactly_at_negative_threshold_is_neutral(self):
        price_end = 100.0 * (1 - DIRECTION_THRESHOLD)
        assert _compute_direction(100.0, price_end) == "neutral"

    def test_flat_price_is_neutral(self):
        assert _compute_direction(150.0, 150.0) == "neutral"


# ---------------------------------------------------------------------------
# _nearest_close
# ---------------------------------------------------------------------------


class TestNearestClose:
    def test_returns_price_on_exact_date(self):
        target = date(2024, 5, 22)
        hist = make_price_df([target], [100.0])
        assert _nearest_close(hist, target) == pytest.approx(100.0)

    def test_returns_next_trading_day_when_exact_missing(self):
        target = date(2024, 5, 22)          # Wednesday — say it's missing
        next_day = target + timedelta(days=1)
        hist = make_price_df([next_day], [105.0])
        assert _nearest_close(hist, target) == pytest.approx(105.0)

    def test_returns_none_when_no_date_within_window(self):
        # DataFrame only has a date far in the future
        far_date = date(2024, 5, 22) + timedelta(days=MAX_TRADING_DAY_SEARCH + 5)
        target = date(2024, 5, 22)
        hist = make_price_df([far_date], [99.0])
        assert _nearest_close(hist, target) is None

    def test_returns_none_for_empty_dataframe(self):
        hist = make_price_df([], [])
        assert _nearest_close(hist, date(2024, 1, 1)) is None

    def test_picks_earliest_match_within_window(self):
        target = date(2024, 5, 22)
        d1 = target + timedelta(days=1)
        d2 = target + timedelta(days=2)
        hist = make_price_df([d1, d2], [111.0, 222.0])
        # Should return d1's price (offset=1 wins over offset=2)
        assert _nearest_close(hist, target) == pytest.approx(111.0)


# ---------------------------------------------------------------------------
# _fetch_snapshot_sync
# ---------------------------------------------------------------------------


class TestFetchSnapshotSync:
    def test_returns_snapshot_with_direction(self):
        snap_date = date(2024, 5, 22)
        hist = make_snapshot_df(snap_date, close=100.0, price_30d=110.0)
        with patch("backend.data.prices.yf.download", return_value=hist):
            snap = _fetch_snapshot_sync("NVDA", snap_date)

        assert snap.ticker == "NVDA"
        assert snap.snapshot_date == snap_date
        assert snap.close_price == pytest.approx(100.0)
        assert snap.price_30d_later == pytest.approx(110.0)
        assert snap.actual_direction == "up"

    def test_direction_down(self):
        snap_date = date(2024, 5, 22)
        hist = make_snapshot_df(snap_date, close=100.0, price_30d=90.0)
        with patch("backend.data.prices.yf.download", return_value=hist):
            snap = _fetch_snapshot_sync("NVDA", snap_date)
        assert snap.actual_direction == "down"

    def test_direction_neutral(self):
        snap_date = date(2024, 5, 22)
        hist = make_snapshot_df(snap_date, close=100.0, price_30d=101.0)
        with patch("backend.data.prices.yf.download", return_value=hist):
            snap = _fetch_snapshot_sync("NVDA", snap_date)
        assert snap.actual_direction == "neutral"

    def test_returns_nones_when_dataframe_empty(self):
        snap_date = date(2024, 5, 22)
        empty_df = make_price_df([], [])
        with patch("backend.data.prices.yf.download", return_value=empty_df):
            snap = _fetch_snapshot_sync("NVDA", snap_date)

        assert snap.close_price is None
        assert snap.price_30d_later is None
        assert snap.actual_direction is None

    def test_returns_nones_when_yfinance_raises(self):
        snap_date = date(2024, 5, 22)
        with patch("backend.data.prices.yf.download", side_effect=Exception("network error")):
            snap = _fetch_snapshot_sync("NVDA", snap_date)

        assert snap.close_price is None
        assert snap.actual_direction is None

    def test_direction_is_none_when_30d_price_unavailable(self):
        """If there's no data 30d later, direction should be None."""
        snap_date = date(2024, 5, 22)
        hist = make_price_df([snap_date], [100.0])     # only snapshot date, no 30d data
        with patch("backend.data.prices.yf.download", return_value=hist):
            snap = _fetch_snapshot_sync("NVDA", snap_date)

        assert snap.close_price == pytest.approx(100.0)
        assert snap.price_30d_later is None
        assert snap.actual_direction is None


# ---------------------------------------------------------------------------
# _fetch_range_sync
# ---------------------------------------------------------------------------


class TestFetchRangeSync:
    def test_returns_snapshot_per_trading_day(self):
        start = date(2024, 1, 2)
        end = date(2024, 1, 4)
        # 3 consecutive days + their 30d-later counterparts
        trading_days = [start + timedelta(days=i) for i in range(3)]
        later_days = [d + timedelta(days=LOOKAHEAD_DAYS) for d in trading_days]
        all_dates = trading_days + later_days
        all_closes = [100.0, 102.0, 104.0, 103.0, 105.0, 107.0]
        hist = make_price_df(all_dates, all_closes)

        with patch("backend.data.prices.yf.download", return_value=hist):
            snaps = _fetch_range_sync("NVDA", start, end)

        assert len(snaps) == 3
        for snap in snaps:
            assert snap.ticker == "NVDA"
            assert snap.close_price is not None
            assert snap.actual_direction is not None

    def test_returns_empty_list_when_dataframe_empty(self):
        empty_df = make_price_df([], [])
        with patch("backend.data.prices.yf.download", return_value=empty_df):
            snaps = _fetch_range_sync("NVDA", date(2024, 1, 2), date(2024, 1, 5))
        assert snaps == []

    def test_returns_empty_list_when_yfinance_raises(self):
        with patch("backend.data.prices.yf.download", side_effect=Exception("api error")):
            snaps = _fetch_range_sync("NVDA", date(2024, 1, 2), date(2024, 1, 5))
        assert snaps == []

    def test_snaps_outside_range_are_excluded(self):
        """Dates before start or after end must not appear in the result."""
        start = date(2024, 1, 10)
        end = date(2024, 1, 12)
        before = start - timedelta(days=1)
        after = end + timedelta(days=1)
        in_range = [start, end]
        hist = make_price_df(
            [before] + in_range + [after],
            [90.0, 100.0, 102.0, 200.0],
        )
        with patch("backend.data.prices.yf.download", return_value=hist):
            snaps = _fetch_range_sync("NVDA", start, end)

        snap_dates = {s.snapshot_date for s in snaps}
        assert before not in snap_dates
        assert after not in snap_dates


# ---------------------------------------------------------------------------
# get_price_snapshot  (async public API)
# ---------------------------------------------------------------------------


class TestGetPriceSnapshot:
    async def test_returns_price_snapshot(self):
        snap_date = date(2024, 5, 22)
        expected = PriceSnapshot(
            ticker="NVDA",
            snapshot_date=snap_date,
            close_price=100.0,
            price_30d_later=110.0,
            actual_direction="up",
        )
        with patch("backend.data.prices._fetch_snapshot_sync", return_value=expected):
            result = await get_price_snapshot("NVDA", snap_date)

        assert result is expected

    async def test_passes_ticker_and_date_to_sync_fn(self):
        snap_date = date(2024, 6, 1)
        dummy = PriceSnapshot("AAPL", snap_date, None, None, None)
        with patch("backend.data.prices._fetch_snapshot_sync", return_value=dummy) as mock_fn:
            await get_price_snapshot("AAPL", snap_date)

        mock_fn.assert_called_once_with("AAPL", snap_date)


# ---------------------------------------------------------------------------
# get_price_range  (async public API)
# ---------------------------------------------------------------------------


class TestGetPriceRange:
    async def test_returns_list_of_snapshots(self):
        start = date(2024, 1, 2)
        end = date(2024, 1, 4)
        expected = [
            PriceSnapshot("NVDA", start, 100.0, 105.0, "up"),
            PriceSnapshot("NVDA", end, 102.0, 100.0, "down"),
        ]
        with patch("backend.data.prices._fetch_range_sync", return_value=expected):
            result = await get_price_range("NVDA", start, end)

        assert result == expected

    async def test_passes_ticker_and_dates_to_sync_fn(self):
        start = date(2024, 3, 1)
        end = date(2024, 3, 31)
        with patch("backend.data.prices._fetch_range_sync", return_value=[]) as mock_fn:
            await get_price_range("MSFT", start, end)

        mock_fn.assert_called_once_with("MSFT", start, end)
