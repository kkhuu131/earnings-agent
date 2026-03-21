"""Unit tests for backend.backtest.runner.run_backtest.

run_pipeline and get_session are mocked at the module level so no real LLM
calls or database connections are made.

Tests verify:
  - Empty ticker list returns a zero-filled BacktestSummary immediately
  - No matching transcripts returns a zero-filled BacktestSummary
  - Correct labelling: was_correct=True when directions match
  - Correct labelling: was_correct=False when directions differ
  - was_correct=None when actual_direction is None
  - was_correct=None when predicted direction is None
  - All Prediction rows are persisted via session.add()
  - BacktestSummary accuracy arithmetic (overall and per-ticker)
  - Transcripts with missing price snapshots are skipped gracefully
  - Transcripts with empty text are skipped gracefully
  - Pipeline exceptions are caught and the transcript is skipped gracefully
  - Per-ticker counters are tracked independently across multiple tickers
"""

import uuid
from contextlib import asynccontextmanager
from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from backend.backtest.runner import run_backtest


@pytest.fixture(autouse=True)
def mock_update_reputation():
    """Suppress update_reputation in all runner tests — it has its own test file."""
    with patch("backend.backtest.runner.update_reputation", new=AsyncMock()):
        yield

# ---------------------------------------------------------------------------
# Test data helpers
# ---------------------------------------------------------------------------

_START = date(2024, 1, 1)
_END = date(2024, 12, 31)

_MOCK_PREDICTION_UP = {
    "direction": "up",
    "confidence": 0.8,
    "reasoning": "Bullish signals.",
    "weighted_signals": {},
    "agent_reports": {},
    "debate_transcript": {},
}

_MOCK_PREDICTION_DOWN = {
    "direction": "down",
    "confidence": 0.7,
    "reasoning": "Bearish signals.",
    "weighted_signals": {},
    "agent_reports": {},
    "debate_transcript": {},
}


def _make_transcript(
    ticker: str = "AAPL",
    filing_date: date = date(2024, 2, 1),
    transcript_text: str = "Revenue grew 18%...",
) -> MagicMock:
    t = MagicMock()
    t.id = uuid.uuid4()
    t.ticker = ticker
    t.filing_date = filing_date
    t.transcript_text = transcript_text
    return t


def _make_snapshot(
    ticker: str = "AAPL",
    snapshot_date: date = date(2024, 2, 1),
    close_price: float = 182.0,
    price_30d_later: float = 195.0,
    actual_direction: str = "up",
) -> MagicMock:
    s = MagicMock()
    s.ticker = ticker
    s.snapshot_date = snapshot_date
    s.close_price = close_price
    s.price_30d_later = price_30d_later
    s.actual_direction = actual_direction
    return s


def _make_mock_session(transcripts: list, snapshots: list) -> MagicMock:
    """Return a mock session that returns *transcripts* then *snapshots*."""
    transcript_result = MagicMock()
    transcript_result.scalars.return_value.all.return_value = transcripts

    snapshot_result = MagicMock()
    snapshot_result.scalars.return_value.all.return_value = snapshots

    session = MagicMock()
    # First execute → transcripts, second execute → snapshots
    session.execute = AsyncMock(
        side_effect=[transcript_result, snapshot_result]
    )
    return session


def _make_write_session() -> MagicMock:
    """Return a fresh mock session for Prediction writes."""
    session = MagicMock()
    session.add = MagicMock()
    return session


# Context-manager factories

def _make_read_get_session(session: MagicMock):
    """Single-use read session (transcripts + snapshots query)."""
    @asynccontextmanager
    async def _mock():
        yield session

    return _mock


def _make_write_sessions(*write_sessions):
    """Cycle through write_sessions, one per Prediction write call."""
    sessions_iter = iter(write_sessions)

    @asynccontextmanager
    async def _mock():
        yield next(sessions_iter)

    return _mock


# ---------------------------------------------------------------------------
# Helper: patch both get_session calls (read then N writes)
# ---------------------------------------------------------------------------


def _patch_sessions(read_session: MagicMock, write_sessions: list[MagicMock]):
    """
    Return a single get_session patcher that yields read_session first,
    then each write_session in order.
    """
    all_sessions = [read_session] + write_sessions
    session_iter = iter(all_sessions)

    @asynccontextmanager
    async def _mock():
        yield next(session_iter)

    return _mock


# ---------------------------------------------------------------------------
# Empty inputs
# ---------------------------------------------------------------------------


class TestEmptyInputs:
    @pytest.mark.asyncio
    async def test_empty_ticker_list_returns_zero_summary(self):
        summary = await run_backtest([], _START, _END)
        assert summary["total"] == 0
        assert summary["correct"] == 0
        assert summary["accuracy"] == 0.0
        assert summary["per_ticker"] == {}

    @pytest.mark.asyncio
    async def test_no_matching_transcripts_returns_zero_summary(self):
        read_session = _make_mock_session(transcripts=[], snapshots=[])
        with patch(
            "backend.backtest.runner.get_session",
            new=_make_read_get_session(read_session),
        ):
            summary = await run_backtest(["AAPL"], _START, _END)
        assert summary["total"] == 0
        assert summary["correct"] == 0
        assert summary["accuracy"] == 0.0
        assert summary["per_ticker"] == {}


# ---------------------------------------------------------------------------
# Labelling logic
# ---------------------------------------------------------------------------


class TestLabellingLogic:
    @pytest.mark.asyncio
    async def test_was_correct_true_when_directions_match(self):
        transcript = _make_transcript(ticker="AAPL", filing_date=date(2024, 2, 1))
        snapshot = _make_snapshot(ticker="AAPL", snapshot_date=date(2024, 2, 1), actual_direction="up")
        read_session = _make_mock_session([transcript], [snapshot])
        write_session = _make_write_session()

        with (
            patch(
                "backend.backtest.runner.get_session",
                new=_patch_sessions(read_session, [write_session]),
            ),
            patch(
                "backend.backtest.runner.run_pipeline",
                new=AsyncMock(return_value=_MOCK_PREDICTION_UP),
            ),
        ):
            summary = await run_backtest(["AAPL"], _START, _END)

        (record,), _ = write_session.add.call_args
        assert record.was_correct is True
        assert summary["correct"] == 1

    @pytest.mark.asyncio
    async def test_was_correct_false_when_directions_differ(self):
        transcript = _make_transcript(ticker="AAPL", filing_date=date(2024, 2, 1))
        snapshot = _make_snapshot(ticker="AAPL", snapshot_date=date(2024, 2, 1), actual_direction="down")
        read_session = _make_mock_session([transcript], [snapshot])
        write_session = _make_write_session()

        with (
            patch(
                "backend.backtest.runner.get_session",
                new=_patch_sessions(read_session, [write_session]),
            ),
            patch(
                "backend.backtest.runner.run_pipeline",
                new=AsyncMock(return_value=_MOCK_PREDICTION_UP),
            ),
        ):
            summary = await run_backtest(["AAPL"], _START, _END)

        (record,), _ = write_session.add.call_args
        assert record.was_correct is False
        assert summary["correct"] == 0

    @pytest.mark.asyncio
    async def test_was_correct_none_when_actual_direction_none(self):
        transcript = _make_transcript(ticker="AAPL", filing_date=date(2024, 2, 1))
        snapshot = _make_snapshot(ticker="AAPL", snapshot_date=date(2024, 2, 1), actual_direction=None)
        read_session = _make_mock_session([transcript], [snapshot])
        write_session = _make_write_session()

        with (
            patch(
                "backend.backtest.runner.get_session",
                new=_patch_sessions(read_session, [write_session]),
            ),
            patch(
                "backend.backtest.runner.run_pipeline",
                new=AsyncMock(return_value=_MOCK_PREDICTION_UP),
            ),
        ):
            await run_backtest(["AAPL"], _START, _END)

        (record,), _ = write_session.add.call_args
        assert record.was_correct is None

    @pytest.mark.asyncio
    async def test_was_correct_none_when_predicted_direction_none(self):
        transcript = _make_transcript(ticker="AAPL", filing_date=date(2024, 2, 1))
        snapshot = _make_snapshot(ticker="AAPL", snapshot_date=date(2024, 2, 1), actual_direction="up")
        read_session = _make_mock_session([transcript], [snapshot])
        write_session = _make_write_session()
        pipeline_result = {**_MOCK_PREDICTION_UP, "direction": None}

        with (
            patch(
                "backend.backtest.runner.get_session",
                new=_patch_sessions(read_session, [write_session]),
            ),
            patch(
                "backend.backtest.runner.run_pipeline",
                new=AsyncMock(return_value=pipeline_result),
            ),
        ):
            await run_backtest(["AAPL"], _START, _END)

        (record,), _ = write_session.add.call_args
        assert record.was_correct is None


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


class TestPersistence:
    @pytest.mark.asyncio
    async def test_prediction_row_added_to_session(self):
        transcript = _make_transcript()
        snapshot = _make_snapshot()
        read_session = _make_mock_session([transcript], [snapshot])
        write_session = _make_write_session()

        with (
            patch(
                "backend.backtest.runner.get_session",
                new=_patch_sessions(read_session, [write_session]),
            ),
            patch(
                "backend.backtest.runner.run_pipeline",
                new=AsyncMock(return_value=_MOCK_PREDICTION_UP),
            ),
        ):
            await run_backtest(["AAPL"], _START, _END)

        write_session.add.assert_called_once()

    @pytest.mark.asyncio
    async def test_persisted_record_has_correct_ticker(self):
        transcript = _make_transcript(ticker="MSFT")
        snapshot = _make_snapshot(ticker="MSFT")
        read_session = _make_mock_session([transcript], [snapshot])
        write_session = _make_write_session()

        with (
            patch(
                "backend.backtest.runner.get_session",
                new=_patch_sessions(read_session, [write_session]),
            ),
            patch(
                "backend.backtest.runner.run_pipeline",
                new=AsyncMock(return_value=_MOCK_PREDICTION_UP),
            ),
        ):
            await run_backtest(["MSFT"], _START, _END)

        (record,), _ = write_session.add.call_args
        assert record.ticker == "MSFT"

    @pytest.mark.asyncio
    async def test_persisted_record_has_uuid_id(self):
        transcript = _make_transcript()
        snapshot = _make_snapshot()
        read_session = _make_mock_session([transcript], [snapshot])
        write_session = _make_write_session()

        with (
            patch(
                "backend.backtest.runner.get_session",
                new=_patch_sessions(read_session, [write_session]),
            ),
            patch(
                "backend.backtest.runner.run_pipeline",
                new=AsyncMock(return_value=_MOCK_PREDICTION_UP),
            ),
        ):
            await run_backtest(["AAPL"], _START, _END)

        (record,), _ = write_session.add.call_args
        assert isinstance(record.id, uuid.UUID)

    @pytest.mark.asyncio
    async def test_persisted_record_has_transcript_id(self):
        transcript = _make_transcript()
        snapshot = _make_snapshot()
        read_session = _make_mock_session([transcript], [snapshot])
        write_session = _make_write_session()

        with (
            patch(
                "backend.backtest.runner.get_session",
                new=_patch_sessions(read_session, [write_session]),
            ),
            patch(
                "backend.backtest.runner.run_pipeline",
                new=AsyncMock(return_value=_MOCK_PREDICTION_UP),
            ),
        ):
            await run_backtest(["AAPL"], _START, _END)

        (record,), _ = write_session.add.call_args
        assert record.transcript_id == transcript.id

    @pytest.mark.asyncio
    async def test_persisted_record_has_actual_direction(self):
        transcript = _make_transcript()
        snapshot = _make_snapshot(actual_direction="down")
        read_session = _make_mock_session([transcript], [snapshot])
        write_session = _make_write_session()

        with (
            patch(
                "backend.backtest.runner.get_session",
                new=_patch_sessions(read_session, [write_session]),
            ),
            patch(
                "backend.backtest.runner.run_pipeline",
                new=AsyncMock(return_value=_MOCK_PREDICTION_DOWN),
            ),
        ):
            await run_backtest(["AAPL"], _START, _END)

        (record,), _ = write_session.add.call_args
        assert record.actual_direction == "down"

    @pytest.mark.asyncio
    async def test_multiple_transcripts_each_added_to_session(self):
        filing_date_1 = date(2024, 2, 1)
        filing_date_2 = date(2024, 5, 1)
        t1 = _make_transcript(filing_date=filing_date_1)
        t2 = _make_transcript(filing_date=filing_date_2)
        s1 = _make_snapshot(snapshot_date=filing_date_1)
        s2 = _make_snapshot(snapshot_date=filing_date_2)
        read_session = _make_mock_session([t1, t2], [s1, s2])
        ws1 = _make_write_session()
        ws2 = _make_write_session()

        with (
            patch(
                "backend.backtest.runner.get_session",
                new=_patch_sessions(read_session, [ws1, ws2]),
            ),
            patch(
                "backend.backtest.runner.run_pipeline",
                new=AsyncMock(return_value=_MOCK_PREDICTION_UP),
            ),
        ):
            await run_backtest(["AAPL"], _START, _END)

        ws1.add.assert_called_once()
        ws2.add.assert_called_once()


# ---------------------------------------------------------------------------
# Accuracy arithmetic
# ---------------------------------------------------------------------------


class TestAccuracyArithmetic:
    @pytest.mark.asyncio
    async def test_accuracy_one_correct_of_one(self):
        transcript = _make_transcript()
        snapshot = _make_snapshot(actual_direction="up")
        read_session = _make_mock_session([transcript], [snapshot])
        write_session = _make_write_session()

        with (
            patch(
                "backend.backtest.runner.get_session",
                new=_patch_sessions(read_session, [write_session]),
            ),
            patch(
                "backend.backtest.runner.run_pipeline",
                new=AsyncMock(return_value=_MOCK_PREDICTION_UP),
            ),
        ):
            summary = await run_backtest(["AAPL"], _START, _END)

        assert summary["total"] == 1
        assert summary["correct"] == 1
        assert summary["accuracy"] == pytest.approx(1.0)

    @pytest.mark.asyncio
    async def test_accuracy_zero_correct_of_one(self):
        transcript = _make_transcript()
        snapshot = _make_snapshot(actual_direction="down")
        read_session = _make_mock_session([transcript], [snapshot])
        write_session = _make_write_session()

        with (
            patch(
                "backend.backtest.runner.get_session",
                new=_patch_sessions(read_session, [write_session]),
            ),
            patch(
                "backend.backtest.runner.run_pipeline",
                new=AsyncMock(return_value=_MOCK_PREDICTION_UP),
            ),
        ):
            summary = await run_backtest(["AAPL"], _START, _END)

        assert summary["total"] == 1
        assert summary["correct"] == 0
        assert summary["accuracy"] == pytest.approx(0.0)

    @pytest.mark.asyncio
    async def test_accuracy_one_correct_of_two(self):
        filing_date_1 = date(2024, 2, 1)
        filing_date_2 = date(2024, 5, 1)
        t1 = _make_transcript(filing_date=filing_date_1)
        t2 = _make_transcript(filing_date=filing_date_2)
        s1 = _make_snapshot(snapshot_date=filing_date_1, actual_direction="up")
        s2 = _make_snapshot(snapshot_date=filing_date_2, actual_direction="down")
        read_session = _make_mock_session([t1, t2], [s1, s2])
        ws1 = _make_write_session()
        ws2 = _make_write_session()
        # Pipeline always predicts "up" → correct for s1, wrong for s2
        with (
            patch(
                "backend.backtest.runner.get_session",
                new=_patch_sessions(read_session, [ws1, ws2]),
            ),
            patch(
                "backend.backtest.runner.run_pipeline",
                new=AsyncMock(return_value=_MOCK_PREDICTION_UP),
            ),
        ):
            summary = await run_backtest(["AAPL"], _START, _END)

        assert summary["total"] == 2
        assert summary["correct"] == 1
        assert summary["accuracy"] == pytest.approx(0.5)

    @pytest.mark.asyncio
    async def test_per_ticker_accuracy_tracked_independently(self):
        aapl_t = _make_transcript(ticker="AAPL", filing_date=date(2024, 2, 1))
        msft_t = _make_transcript(ticker="MSFT", filing_date=date(2024, 3, 1))
        aapl_s = _make_snapshot(ticker="AAPL", snapshot_date=date(2024, 2, 1), actual_direction="up")
        msft_s = _make_snapshot(ticker="MSFT", snapshot_date=date(2024, 3, 1), actual_direction="down")
        read_session = _make_mock_session([aapl_t, msft_t], [aapl_s, msft_s])
        ws1 = _make_write_session()
        ws2 = _make_write_session()

        with (
            patch(
                "backend.backtest.runner.get_session",
                new=_patch_sessions(read_session, [ws1, ws2]),
            ),
            patch(
                "backend.backtest.runner.run_pipeline",
                new=AsyncMock(return_value=_MOCK_PREDICTION_UP),
            ),
        ):
            summary = await run_backtest(["AAPL", "MSFT"], _START, _END)

        assert summary["per_ticker"]["AAPL"]["correct"] == 1
        assert summary["per_ticker"]["AAPL"]["total"] == 1
        assert summary["per_ticker"]["MSFT"]["correct"] == 0
        assert summary["per_ticker"]["MSFT"]["total"] == 1

    @pytest.mark.asyncio
    async def test_per_ticker_accuracy_value(self):
        aapl_t = _make_transcript(ticker="AAPL", filing_date=date(2024, 2, 1))
        aapl_s = _make_snapshot(ticker="AAPL", snapshot_date=date(2024, 2, 1), actual_direction="up")
        read_session = _make_mock_session([aapl_t], [aapl_s])
        write_session = _make_write_session()

        with (
            patch(
                "backend.backtest.runner.get_session",
                new=_patch_sessions(read_session, [write_session]),
            ),
            patch(
                "backend.backtest.runner.run_pipeline",
                new=AsyncMock(return_value=_MOCK_PREDICTION_UP),
            ),
        ):
            summary = await run_backtest(["AAPL"], _START, _END)

        assert summary["per_ticker"]["AAPL"]["accuracy"] == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# Graceful skipping
# ---------------------------------------------------------------------------


class TestGracefulSkipping:
    @pytest.mark.asyncio
    async def test_missing_price_snapshot_is_skipped(self):
        transcript = _make_transcript(ticker="AAPL", filing_date=date(2024, 2, 1))
        # No snapshot provided — snap_index will have no entry
        read_session = _make_mock_session([transcript], [])

        mock_pipeline = AsyncMock(return_value=_MOCK_PREDICTION_UP)
        with (
            patch(
                "backend.backtest.runner.get_session",
                new=_make_read_get_session(read_session),
            ),
            patch("backend.backtest.runner.run_pipeline", new=mock_pipeline),
        ):
            summary = await run_backtest(["AAPL"], _START, _END)

        mock_pipeline.assert_not_awaited()
        assert summary["total"] == 0

    @pytest.mark.asyncio
    async def test_empty_transcript_text_is_skipped(self):
        transcript = _make_transcript(ticker="AAPL", filing_date=date(2024, 2, 1), transcript_text="")
        snapshot = _make_snapshot(ticker="AAPL", snapshot_date=date(2024, 2, 1))
        read_session = _make_mock_session([transcript], [snapshot])

        mock_pipeline = AsyncMock(return_value=_MOCK_PREDICTION_UP)
        with (
            patch(
                "backend.backtest.runner.get_session",
                new=_make_read_get_session(read_session),
            ),
            patch("backend.backtest.runner.run_pipeline", new=mock_pipeline),
        ):
            summary = await run_backtest(["AAPL"], _START, _END)

        mock_pipeline.assert_not_awaited()
        assert summary["total"] == 0

    @pytest.mark.asyncio
    async def test_none_transcript_text_is_skipped(self):
        transcript = _make_transcript(transcript_text=None)
        snapshot = _make_snapshot()
        read_session = _make_mock_session([transcript], [snapshot])

        mock_pipeline = AsyncMock(return_value=_MOCK_PREDICTION_UP)
        with (
            patch(
                "backend.backtest.runner.get_session",
                new=_make_read_get_session(read_session),
            ),
            patch("backend.backtest.runner.run_pipeline", new=mock_pipeline),
        ):
            summary = await run_backtest(["AAPL"], _START, _END)

        mock_pipeline.assert_not_awaited()
        assert summary["total"] == 0

    @pytest.mark.asyncio
    async def test_pipeline_exception_is_caught_and_skipped(self):
        transcript = _make_transcript()
        snapshot = _make_snapshot()
        read_session = _make_mock_session([transcript], [snapshot])

        with (
            patch(
                "backend.backtest.runner.get_session",
                new=_make_read_get_session(read_session),
            ),
            patch(
                "backend.backtest.runner.run_pipeline",
                new=AsyncMock(side_effect=RuntimeError("LLM timeout")),
            ),
        ):
            summary = await run_backtest(["AAPL"], _START, _END)

        assert summary["total"] == 0

    @pytest.mark.asyncio
    async def test_second_transcript_processed_after_first_skipped(self):
        """If the first transcript has no snapshot, the second should still run."""
        t1 = _make_transcript(ticker="AAPL", filing_date=date(2024, 2, 1))
        t2 = _make_transcript(ticker="AAPL", filing_date=date(2024, 5, 1))
        # Only snapshot for t2
        s2 = _make_snapshot(ticker="AAPL", snapshot_date=date(2024, 5, 1), actual_direction="up")
        read_session = _make_mock_session([t1, t2], [s2])
        write_session = _make_write_session()

        with (
            patch(
                "backend.backtest.runner.get_session",
                new=_patch_sessions(read_session, [write_session]),
            ),
            patch(
                "backend.backtest.runner.run_pipeline",
                new=AsyncMock(return_value=_MOCK_PREDICTION_UP),
            ),
        ):
            summary = await run_backtest(["AAPL"], _START, _END)

        assert summary["total"] == 1
        assert summary["correct"] == 1
