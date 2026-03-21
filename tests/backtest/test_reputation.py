"""Unit tests for backend.backtest.reputation.update_reputation.

The DB session is mocked throughout — no real database is required.

Tests verify:
  - No-op when there are no predictions with was_correct set
  - No-op when predictions have no weighted_signals data
  - Accuracy is computed correctly (correct / total)
  - Weights are normalised and sum to 1.0 across all agents
  - Equal-weight fallback when all agent accuracies are zero
  - Upsert: session.add called for new agents (none existing)
  - Upsert: existing row attributes mutated, no session.add for known agents
  - Runner calls update_reputation after processing at least one prediction
  - Runner does NOT call update_reputation when no predictions were processed
"""

import uuid
from contextlib import asynccontextmanager
from datetime import date, datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.backtest.reputation import _update_reputation_with_session as update_reputation


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_prediction(
    actual_direction: str | None = "up",
    was_correct: bool | None = True,
    weighted_signals: dict | None = None,
) -> MagicMock:
    """Build a mock Prediction ORM row."""
    p = MagicMock()
    p.id = uuid.uuid4()
    p.actual_direction = actual_direction
    p.was_correct = was_correct
    p.weighted_signals = weighted_signals or {
        "fundamentals": {"signal": "bullish", "weight": 0.2},
        "sentiment":    {"signal": "bullish", "weight": 0.2},
        "technical":    {"signal": "bullish", "weight": 0.2},
        "bull":         {"signal": "bullish", "weight": 0.2},
        "bear":         {"signal": "bearish", "weight": 0.2},
    }
    return p


def _make_rep_row(
    agent_name: str,
    correct: int = 0,
    total: int = 0,
    accuracy: float = 0.0,
    weight: float = 0.2,
) -> MagicMock:
    """Build a mock AgentReputation ORM row."""
    row = MagicMock()
    row.agent_name = agent_name
    row.correct_predictions = correct
    row.total_predictions = total
    row.accuracy = Decimal(str(accuracy))
    row.weight = Decimal(str(weight))
    return row


def _make_session(
    predictions: list,
    existing_reps: list | None = None,
) -> MagicMock:
    """Return a mock async session with two execute side-effects.

    First execute → Prediction rows.
    Second execute → AgentReputation rows (defaults to empty list).
    """
    if existing_reps is None:
        existing_reps = []

    pred_result = MagicMock()
    pred_result.scalars.return_value.all.return_value = predictions

    rep_result = MagicMock()
    rep_result.scalars.return_value.all.return_value = existing_reps

    session = MagicMock()
    session.execute = AsyncMock(side_effect=[pred_result, rep_result])
    session.add = MagicMock()
    return session


# ---------------------------------------------------------------------------
# No-op cases
# ---------------------------------------------------------------------------


class TestNoOp:
    @pytest.mark.asyncio
    async def test_no_predictions_returns_early(self):
        """When there are no resolved predictions, execute is called once for
        the Prediction query and never for AgentReputation."""
        pred_result = MagicMock()
        pred_result.scalars.return_value.all.return_value = []

        session = MagicMock()
        session.execute = AsyncMock(return_value=pred_result)
        session.add = MagicMock()

        await update_reputation(session)

        # Only the Prediction SELECT should have been issued
        assert session.execute.call_count == 1
        session.add.assert_not_called()

    @pytest.mark.asyncio
    async def test_predictions_with_no_weighted_signals_skipped(self):
        """Predictions with ``weighted_signals=None`` contribute nothing."""
        pred = _make_prediction(was_correct=True, weighted_signals=None)
        # Override the default we set in helper
        pred.weighted_signals = None

        pred_result = MagicMock()
        pred_result.scalars.return_value.all.return_value = [pred]

        session = MagicMock()
        session.execute = AsyncMock(return_value=pred_result)
        session.add = MagicMock()

        await update_reputation(session)

        # No AgentReputation SELECT or INSERT should happen
        assert session.execute.call_count == 1
        session.add.assert_not_called()

    @pytest.mark.asyncio
    async def test_predictions_with_no_actual_direction_skipped(self):
        """Predictions missing ``actual_direction`` do not count toward tallies."""
        pred = _make_prediction(actual_direction=None, was_correct=None)

        # The query filters was_correct IS NOT NULL so this row wouldn't
        # normally be returned, but test defensiveness of the inner loop too.
        pred_result = MagicMock()
        pred_result.scalars.return_value.all.return_value = [pred]

        session = MagicMock()
        session.execute = AsyncMock(return_value=pred_result)
        session.add = MagicMock()

        await update_reputation(session)

        assert session.execute.call_count == 1
        session.add.assert_not_called()


# ---------------------------------------------------------------------------
# Accuracy computation
# ---------------------------------------------------------------------------


class TestAccuracyComputation:
    @pytest.mark.asyncio
    async def test_all_correct_gives_accuracy_one(self):
        """Agent whose signal always matches actual direction → accuracy 1.0."""
        pred = _make_prediction(
            actual_direction="up",
            was_correct=True,
            weighted_signals={"fundamentals": {"signal": "bullish", "weight": 0.2}},
        )
        session = _make_session([pred])

        await update_reputation(session)

        (rep,), _ = session.add.call_args
        assert rep.correct_predictions == 1
        assert rep.total_predictions == 1
        assert rep.accuracy == Decimal("1.0")

    @pytest.mark.asyncio
    async def test_no_correct_gives_accuracy_zero(self):
        """Agent whose signal never matches actual direction → accuracy 0.0."""
        pred = _make_prediction(
            actual_direction="down",
            was_correct=False,
            weighted_signals={"fundamentals": {"signal": "bullish", "weight": 0.2}},
        )
        session = _make_session([pred])

        await update_reputation(session)

        (rep,), _ = session.add.call_args
        assert rep.correct_predictions == 0
        assert rep.total_predictions == 1
        assert rep.accuracy == Decimal("0.0")

    @pytest.mark.asyncio
    async def test_partial_correct_accuracy(self):
        """Two predictions, one correct → accuracy 0.5."""
        pred1 = _make_prediction(
            actual_direction="up",
            was_correct=True,
            weighted_signals={"fundamentals": {"signal": "bullish", "weight": 0.2}},
        )
        pred2 = _make_prediction(
            actual_direction="down",
            was_correct=False,
            weighted_signals={"fundamentals": {"signal": "bullish", "weight": 0.2}},
        )
        session = _make_session([pred1, pred2])

        await update_reputation(session)

        (rep,), _ = session.add.call_args
        assert rep.correct_predictions == 1
        assert rep.total_predictions == 2
        assert rep.accuracy == Decimal("0.5")

    @pytest.mark.asyncio
    async def test_bearish_signal_correct_when_direction_down(self):
        """'bearish' signal is correct when actual_direction is 'down'."""
        pred = _make_prediction(
            actual_direction="down",
            was_correct=True,
            weighted_signals={"bear": {"signal": "bearish", "weight": 0.2}},
        )
        session = _make_session([pred])

        await update_reputation(session)

        (rep,), _ = session.add.call_args
        assert rep.correct_predictions == 1

    @pytest.mark.asyncio
    async def test_neutral_signal_correct_when_direction_neutral(self):
        """'neutral' signal is correct when actual_direction is 'neutral'."""
        pred = _make_prediction(
            actual_direction="neutral",
            was_correct=None,  # was_correct set by final direction, not individual
            weighted_signals={"sentiment": {"signal": "neutral", "weight": 0.2}},
        )
        # Override mock so was_correct is not None (so the outer filter passes)
        pred.was_correct = True

        session = _make_session([pred])

        await update_reputation(session)

        (rep,), _ = session.add.call_args
        assert rep.correct_predictions == 1


# ---------------------------------------------------------------------------
# Weight normalisation
# ---------------------------------------------------------------------------


class TestWeightNormalisation:
    @pytest.mark.asyncio
    async def test_weights_sum_to_one(self):
        """Weights across all agents must sum to 1.0."""
        pred = _make_prediction(
            actual_direction="up",
            was_correct=True,
            weighted_signals={
                "fundamentals": {"signal": "bullish", "weight": 0.2},
                "sentiment":    {"signal": "neutral",  "weight": 0.2},
                "technical":    {"signal": "bullish",  "weight": 0.2},
                "bull":         {"signal": "bullish",  "weight": 0.2},
                "bear":         {"signal": "bearish",  "weight": 0.2},
            },
        )
        session = _make_session([pred])

        await update_reputation(session)

        total_weight = sum(float(call[0][0].weight) for call in session.add.call_args_list)
        assert abs(total_weight - 1.0) < 1e-4

    @pytest.mark.asyncio
    async def test_higher_accuracy_gets_higher_weight(self):
        """Agent with higher accuracy should receive a larger weight."""
        pred1 = _make_prediction(
            actual_direction="up",
            was_correct=True,
            weighted_signals={
                "fundamentals": {"signal": "bullish", "weight": 0.2},
                "sentiment":    {"signal": "bearish",  "weight": 0.2},
            },
        )
        pred2 = _make_prediction(
            actual_direction="up",
            was_correct=True,
            weighted_signals={
                "fundamentals": {"signal": "bullish", "weight": 0.2},
                "sentiment":    {"signal": "bearish",  "weight": 0.2},
            },
        )
        # fundamentals: 2/2 = 1.0, sentiment: 0/2 = 0.0
        session = _make_session([pred1, pred2])

        await update_reputation(session)

        reps = {call[0][0].agent_name: call[0][0] for call in session.add.call_args_list}
        assert float(reps["fundamentals"].weight) > float(reps["sentiment"].weight)

    @pytest.mark.asyncio
    async def test_equal_weight_fallback_when_all_zero(self):
        """When every agent has 0 accuracy, fall back to equal weights."""
        pred = _make_prediction(
            actual_direction="down",
            was_correct=False,
            weighted_signals={
                "fundamentals": {"signal": "bullish", "weight": 0.2},
                "sentiment":    {"signal": "bullish",  "weight": 0.2},
            },
        )
        session = _make_session([pred])

        await update_reputation(session)

        reps = {call[0][0].agent_name: call[0][0] for call in session.add.call_args_list}
        assert float(reps["fundamentals"].weight) == pytest.approx(0.5)
        assert float(reps["sentiment"].weight) == pytest.approx(0.5)

    @pytest.mark.asyncio
    async def test_equal_weight_fallback_sums_to_one(self):
        """Equal-weight fallback with three agents → each weight ≈ 1/3."""
        pred = _make_prediction(
            actual_direction="down",
            was_correct=False,
            weighted_signals={
                "fundamentals": {"signal": "bullish", "weight": 0.2},
                "sentiment":    {"signal": "bullish",  "weight": 0.2},
                "technical":    {"signal": "bullish",  "weight": 0.2},
            },
        )
        session = _make_session([pred])

        await update_reputation(session)

        total_weight = sum(float(call[0][0].weight) for call in session.add.call_args_list)
        assert abs(total_weight - 1.0) < 1e-3


# ---------------------------------------------------------------------------
# Upsert behaviour
# ---------------------------------------------------------------------------


class TestUpsert:
    @pytest.mark.asyncio
    async def test_new_agent_added_via_session_add(self):
        """When no existing reputation row exists, session.add is called."""
        pred = _make_prediction(
            actual_direction="up",
            was_correct=True,
            weighted_signals={"fundamentals": {"signal": "bullish", "weight": 0.2}},
        )
        session = _make_session([pred], existing_reps=[])

        await update_reputation(session)

        session.add.assert_called_once()
        (rep,), _ = session.add.call_args
        assert rep.agent_name == "fundamentals"

    @pytest.mark.asyncio
    async def test_existing_agent_row_mutated_not_added(self):
        """When a row already exists for an agent, attributes are mutated and
        session.add is NOT called for that agent."""
        pred = _make_prediction(
            actual_direction="up",
            was_correct=True,
            weighted_signals={"fundamentals": {"signal": "bullish", "weight": 0.2}},
        )
        existing_row = _make_rep_row("fundamentals", correct=0, total=0)
        session = _make_session([pred], existing_reps=[existing_row])

        await update_reputation(session)

        session.add.assert_not_called()
        assert existing_row.correct_predictions == 1
        assert existing_row.total_predictions == 1

    @pytest.mark.asyncio
    async def test_upsert_called_once_per_agent(self):
        """session.add is called exactly once for each new agent."""
        pred = _make_prediction(
            actual_direction="up",
            was_correct=True,
            weighted_signals={
                "fundamentals": {"signal": "bullish", "weight": 0.2},
                "sentiment":    {"signal": "bullish",  "weight": 0.2},
                "technical":    {"signal": "bullish",  "weight": 0.2},
            },
        )
        session = _make_session([pred], existing_reps=[])

        await update_reputation(session)

        assert session.add.call_count == 3
        added_names = {call[0][0].agent_name for call in session.add.call_args_list}
        assert added_names == {"fundamentals", "sentiment", "technical"}

    @pytest.mark.asyncio
    async def test_mix_of_new_and_existing_agents(self):
        """New agents are added; existing agents are mutated in-place."""
        pred = _make_prediction(
            actual_direction="up",
            was_correct=True,
            weighted_signals={
                "fundamentals": {"signal": "bullish", "weight": 0.2},
                "sentiment":    {"signal": "bearish",  "weight": 0.2},
            },
        )
        existing_row = _make_rep_row("fundamentals", correct=5, total=10)
        session = _make_session([pred], existing_reps=[existing_row])

        await update_reputation(session)

        # Only sentiment should have been added
        assert session.add.call_count == 1
        (rep,), _ = session.add.call_args
        assert rep.agent_name == "sentiment"

        # Existing fundamentals row should be updated
        assert existing_row.correct_predictions == 1
        assert existing_row.total_predictions == 1


# ---------------------------------------------------------------------------
# Runner integration
# ---------------------------------------------------------------------------


class TestRunnerIntegration:
    """Verify that run_backtest wires update_reputation correctly."""

    def _make_read_session(self, transcripts, snapshots):
        t_result = MagicMock()
        t_result.scalars.return_value.all.return_value = transcripts
        s_result = MagicMock()
        s_result.scalars.return_value.all.return_value = snapshots
        session = MagicMock()
        session.execute = AsyncMock(side_effect=[t_result, s_result])
        return session

    def _make_write_session(self):
        session = MagicMock()
        session.add = MagicMock()
        return session

    def _make_rep_session(self):
        session = MagicMock()
        session.add = MagicMock()
        return session

    def _make_transcript(self, ticker="AAPL", filing_date=date(2024, 2, 1)):
        t = MagicMock()
        t.id = uuid.uuid4()
        t.ticker = ticker
        t.filing_date = filing_date
        t.transcript_text = "Revenue grew 18%..."
        return t

    def _make_snapshot(self, ticker="AAPL", snapshot_date=date(2024, 2, 1)):
        s = MagicMock()
        s.ticker = ticker
        s.snapshot_date = snapshot_date
        s.close_price = 182.0
        s.price_30d_later = 195.0
        s.actual_direction = "up"
        return s

    @pytest.mark.asyncio
    async def test_runner_calls_update_reputation_when_predictions_processed(self):
        from contextlib import asynccontextmanager

        transcript = self._make_transcript()
        snapshot = self._make_snapshot()
        read_session = self._make_read_session([transcript], [snapshot])
        write_session = self._make_write_session()
        rep_session = self._make_rep_session()

        sessions = iter([read_session, write_session, rep_session])

        @asynccontextmanager
        async def _mock_get_session():
            yield next(sessions)

        mock_pipeline = AsyncMock(return_value={
            "direction": "up",
            "confidence": 0.8,
            "reasoning": "Bullish.",
            "weighted_signals": {},
            "agent_reports": {},
            "debate_transcript": {},
        })
        mock_update = AsyncMock()

        with (
            patch("backend.backtest.runner.get_session", new=_mock_get_session),
            patch("backend.backtest.runner.run_pipeline", new=mock_pipeline),
            patch("backend.backtest.runner.update_reputation", new=mock_update),
        ):
            from backend.backtest.runner import run_backtest
            await run_backtest(["AAPL"], date(2024, 1, 1), date(2024, 12, 31))

        mock_update.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_runner_skips_update_reputation_when_no_predictions_processed(self):
        """If all transcripts are skipped, update_reputation is never called."""
        from contextlib import asynccontextmanager

        # Transcript exists but has no matching snapshot → skipped
        transcript = self._make_transcript()
        read_session = self._make_read_session([transcript], [])

        @asynccontextmanager
        async def _mock_get_session():
            yield read_session

        mock_update = AsyncMock()

        with (
            patch("backend.backtest.runner.get_session", new=_mock_get_session),
            patch("backend.backtest.runner.update_reputation", new=mock_update),
        ):
            from backend.backtest.runner import run_backtest
            await run_backtest(["AAPL"], date(2024, 1, 1), date(2024, 12, 31))

        mock_update.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_runner_skips_update_reputation_when_no_transcripts(self):
        """Empty transcript list → update_reputation never called."""
        from contextlib import asynccontextmanager

        read_session = self._make_read_session([], [])

        @asynccontextmanager
        async def _mock_get_session():
            yield read_session

        mock_update = AsyncMock()

        with (
            patch("backend.backtest.runner.get_session", new=_mock_get_session),
            patch("backend.backtest.runner.update_reputation", new=mock_update),
        ):
            from backend.backtest.runner import run_backtest
            await run_backtest(["AAPL"], date(2024, 1, 1), date(2024, 12, 31))

        mock_update.assert_not_awaited()
