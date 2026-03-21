"""Unit tests for backend/graph/earnings_graph.py.

All six agents are patched at the class level so no LLM calls or network
access occur.  Tests verify:
  - All three analyst nodes execute and their outputs appear in final state
  - Debate list has exactly max_debate_rounds entries
  - Each debate entry has both "bull" and "bear" keys
  - PortfolioManager receives state containing all analyst reports and the
    full debate list
  - run_pipeline returns the PortfolioManager's prediction dict
  - max_debate_rounds=0 produces an empty debate list and still reaches
    PortfolioManager
  - run_pipeline is async (awaitable)
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from backend.config import Settings
from backend.graph.earnings_graph import build_graph, run_pipeline


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

_FUNDAMENTALS_REPORT = {
    "signal": "bullish",
    "key_points": ["Revenue beat by 5%", "EPS above consensus"],
    "confidence": 0.85,
}
_SENTIMENT_REPORT = {
    "signal": "bullish",
    "key_points": ["CEO confident tone", "No hedging"],
    "confidence": 0.75,
}
_TECHNICAL_REPORT = {
    "signal": "neutral",
    "key_points": ["RSI at 55", "Volume flat"],
    "confidence": 0.60,
}
_BULL_REPORT = {
    "argument": "Strong demand signals.",
    "confidence": 0.80,
    "rebuttals": ["Margins priced in."],
}
_BEAR_REPORT = {
    "argument": "Cost pressure ahead.",
    "confidence": 0.65,
    "rebuttals": ["Revenue beat is one-off."],
}
_BULL_REBUTTAL = {
    "argument": "Demand remains intact post-rebuttal.",
    "confidence": 0.78,
    "rebuttals": ["Cost concerns overstated."],
}
_BEAR_REBUTTAL = {
    "argument": "Cost concerns remain even after bull rebuttal.",
    "confidence": 0.62,
    "rebuttals": ["Demand signals misleading."],
}
_PREDICTION = {
    "direction": "up",
    "confidence": 0.74,
    "reasoning": "Bull case prevails.",
    "weighted_signals": {
        "fundamentals": {"signal": "bullish", "weight": 0.2},
        "sentiment": {"signal": "bullish", "weight": 0.2},
        "technical": {"signal": "neutral", "weight": 0.2},
        "bull": {"signal": "bullish", "weight": 0.2},
        "bear": {"signal": "bearish", "weight": 0.2},
    },
}

_TRANSCRIPT = "We delivered strong Q3 results..."
_PRICE_DATA = {"ticker": "AAPL", "close": 180.0, "rsi": 55.0}


def _make_settings(max_debate_rounds: int = 2) -> Settings:
    return Settings(
        database_url="postgresql+asyncpg://localhost/test",
        llm_provider="anthropic",
        quick_model="test-quick",
        deep_model="test-deep",
        temperature=0.0,
        anthropic_api_key="test-key",
        max_debate_rounds=max_debate_rounds,
    )


def _patch_agents(max_debate_rounds: int = 2):
    """Return a context-manager stack that patches all six agent classes."""
    fa = MagicMock()
    fa.analyze = AsyncMock(return_value=_FUNDAMENTALS_REPORT)

    sa = MagicMock()
    sa.analyze = AsyncMock(return_value=_SENTIMENT_REPORT)

    ta = MagicMock()
    ta.analyze = AsyncMock(return_value=_TECHNICAL_REPORT)

    bull = MagicMock()
    bull.analyze = AsyncMock(return_value=_BULL_REPORT)
    bull.analyze_rebuttal = AsyncMock(return_value=_BULL_REBUTTAL)

    bear = MagicMock()
    bear.analyze = AsyncMock(return_value=_BEAR_REPORT)
    bear.analyze_rebuttal = AsyncMock(return_value=_BEAR_REBUTTAL)

    pm = MagicMock()
    pm.analyze = AsyncMock(return_value=_PREDICTION)

    patches = {
        "FundamentalsAnalyst": patch(
            "backend.graph.earnings_graph.FundamentalsAnalyst", return_value=fa
        ),
        "SentimentAnalyst": patch(
            "backend.graph.earnings_graph.SentimentAnalyst", return_value=sa
        ),
        "TechnicalAnalyst": patch(
            "backend.graph.earnings_graph.TechnicalAnalyst", return_value=ta
        ),
        "BullResearcher": patch(
            "backend.graph.earnings_graph.BullResearcher", return_value=bull
        ),
        "BearResearcher": patch(
            "backend.graph.earnings_graph.BearResearcher", return_value=bear
        ),
        "PortfolioManager": patch(
            "backend.graph.earnings_graph.PortfolioManager", return_value=pm
        ),
    }
    return patches, fa, sa, ta, bull, bear, pm


# ---------------------------------------------------------------------------
# Helper to run the graph with all agents mocked
# ---------------------------------------------------------------------------


async def _run(max_debate_rounds: int = 2) -> tuple[dict, dict]:
    """Run run_pipeline with mocked agents and return (final_state_prediction, mocks)."""
    patches, fa, sa, ta, bull, bear, pm = _patch_agents(max_debate_rounds)
    settings = _make_settings(max_debate_rounds)

    started = [p.start() for p in patches.values()]
    try:
        prediction = await run_pipeline(_TRANSCRIPT, _PRICE_DATA, settings=settings)
    finally:
        for p in patches.values():
            p.stop()

    mocks = {"fa": fa, "sa": sa, "ta": ta, "bull": bull, "bear": bear, "pm": pm}
    return prediction, mocks


# ---------------------------------------------------------------------------
# Test: analyst nodes execute
# ---------------------------------------------------------------------------


class TestAnalystNodes:
    @pytest.mark.asyncio
    async def test_fundamentals_analyst_called(self):
        _, mocks = await _run()
        mocks["fa"].analyze.assert_called_once()

    @pytest.mark.asyncio
    async def test_sentiment_analyst_called(self):
        _, mocks = await _run()
        mocks["sa"].analyze.assert_called_once()

    @pytest.mark.asyncio
    async def test_technical_analyst_called(self):
        _, mocks = await _run()
        mocks["ta"].analyze.assert_called_once()

    @pytest.mark.asyncio
    async def test_fundamentals_analyst_receives_transcript(self):
        _, mocks = await _run()
        call_kwargs = mocks["fa"].analyze.call_args[0][0]
        assert call_kwargs["transcript"] == _TRANSCRIPT

    @pytest.mark.asyncio
    async def test_sentiment_analyst_receives_transcript(self):
        _, mocks = await _run()
        call_kwargs = mocks["sa"].analyze.call_args[0][0]
        assert call_kwargs["transcript"] == _TRANSCRIPT

    @pytest.mark.asyncio
    async def test_technical_analyst_receives_price_data(self):
        _, mocks = await _run()
        call_kwargs = mocks["ta"].analyze.call_args[0][0]
        assert call_kwargs["price_data"] == _PRICE_DATA


# ---------------------------------------------------------------------------
# Test: debate loop
# ---------------------------------------------------------------------------


class TestDebateLoop:
    @pytest.mark.asyncio
    async def test_debate_has_correct_number_of_rounds(self):
        patches, fa, sa, ta, bull, bear, pm = _patch_agents(2)
        settings = _make_settings(2)

        # Capture what PortfolioManager receives
        received_state: dict = {}

        async def pm_analyze(ctx):
            received_state.update(ctx)
            return _PREDICTION

        pm.analyze = pm_analyze

        started = [p.start() for p in patches.values()]
        try:
            await run_pipeline(_TRANSCRIPT, _PRICE_DATA, settings=settings)
        finally:
            for p in patches.values():
                p.stop()

        assert len(received_state["debate"]) == 2

    @pytest.mark.asyncio
    async def test_each_debate_round_has_bull_and_bear_keys(self):
        patches, fa, sa, ta, bull, bear, pm = _patch_agents(2)
        settings = _make_settings(2)

        received_state: dict = {}

        async def pm_analyze(ctx):
            received_state.update(ctx)
            return _PREDICTION

        pm.analyze = pm_analyze

        started = [p.start() for p in patches.values()]
        try:
            await run_pipeline(_TRANSCRIPT, _PRICE_DATA, settings=settings)
        finally:
            for p in patches.values():
                p.stop()

        for i, round_dict in enumerate(received_state["debate"]):
            assert "bull" in round_dict, f"Round {i} missing 'bull'"
            assert "bear" in round_dict, f"Round {i} missing 'bear'"

    @pytest.mark.asyncio
    async def test_bull_analyze_called_once_for_first_round(self):
        _, mocks = await _run(max_debate_rounds=1)
        mocks["bull"].analyze.assert_called_once()
        mocks["bull"].analyze_rebuttal.assert_not_called()

    @pytest.mark.asyncio
    async def test_bear_analyze_called_once_for_first_round(self):
        _, mocks = await _run(max_debate_rounds=1)
        mocks["bear"].analyze.assert_called_once()
        mocks["bear"].analyze_rebuttal.assert_not_called()

    @pytest.mark.asyncio
    async def test_rebuttal_called_for_rounds_beyond_first(self):
        _, mocks = await _run(max_debate_rounds=3)
        # Initial analyze once, then rebuttal for rounds 1 and 2
        mocks["bull"].analyze.assert_called_once()
        assert mocks["bull"].analyze_rebuttal.call_count == 2
        mocks["bear"].analyze.assert_called_once()
        assert mocks["bear"].analyze_rebuttal.call_count == 2

    @pytest.mark.asyncio
    async def test_zero_debate_rounds_produces_empty_debate(self):
        patches, fa, sa, ta, bull, bear, pm = _patch_agents(0)
        settings = _make_settings(0)

        received_state: dict = {}

        async def pm_analyze(ctx):
            received_state.update(ctx)
            return _PREDICTION

        pm.analyze = pm_analyze

        started = [p.start() for p in patches.values()]
        try:
            await run_pipeline(_TRANSCRIPT, _PRICE_DATA, settings=settings)
        finally:
            for p in patches.values():
                p.stop()

        assert received_state["debate"] == []

    @pytest.mark.asyncio
    async def test_zero_debate_rounds_bull_not_called(self):
        patches, fa, sa, ta, bull, bear, pm = _patch_agents(0)
        settings = _make_settings(0)

        started = [p.start() for p in patches.values()]
        try:
            await run_pipeline(_TRANSCRIPT, _PRICE_DATA, settings=settings)
        finally:
            for p in patches.values():
                p.stop()

        bull.analyze.assert_not_called()
        bull.analyze_rebuttal.assert_not_called()

    @pytest.mark.asyncio
    async def test_bull_rebuttal_receives_bear_argument(self):
        patches, fa, sa, ta, bull, bear, pm = _patch_agents(2)
        settings = _make_settings(2)

        started = [p.start() for p in patches.values()]
        try:
            await run_pipeline(_TRANSCRIPT, _PRICE_DATA, settings=settings)
        finally:
            for p in patches.values():
                p.stop()

        rebuttal_ctx = bull.analyze_rebuttal.call_args[0][0]
        assert rebuttal_ctx["opposing_argument"] == _BEAR_REPORT["argument"]

    @pytest.mark.asyncio
    async def test_bear_rebuttal_receives_bull_argument(self):
        patches, fa, sa, ta, bull, bear, pm = _patch_agents(2)
        settings = _make_settings(2)

        started = [p.start() for p in patches.values()]
        try:
            await run_pipeline(_TRANSCRIPT, _PRICE_DATA, settings=settings)
        finally:
            for p in patches.values():
                p.stop()

        rebuttal_ctx = bear.analyze_rebuttal.call_args[0][0]
        assert rebuttal_ctx["opposing_argument"] == _BULL_REPORT["argument"]


# ---------------------------------------------------------------------------
# Test: PortfolioManager receives full state
# ---------------------------------------------------------------------------


class TestPortfolioManagerNode:
    @pytest.mark.asyncio
    async def test_portfolio_manager_called(self):
        _, mocks = await _run()
        mocks["pm"].analyze.assert_called_once()

    @pytest.mark.asyncio
    async def test_portfolio_manager_receives_fundamentals(self):
        patches, fa, sa, ta, bull, bear, pm = _patch_agents(2)
        settings = _make_settings(2)

        received: dict = {}

        async def pm_analyze(ctx):
            received.update(ctx)
            return _PREDICTION

        pm.analyze = pm_analyze

        started = [p.start() for p in patches.values()]
        try:
            await run_pipeline(_TRANSCRIPT, _PRICE_DATA, settings=settings)
        finally:
            for p in patches.values():
                p.stop()

        assert received["fundamentals"] == _FUNDAMENTALS_REPORT

    @pytest.mark.asyncio
    async def test_portfolio_manager_receives_sentiment(self):
        patches, fa, sa, ta, bull, bear, pm = _patch_agents(2)
        settings = _make_settings(2)

        received: dict = {}

        async def pm_analyze(ctx):
            received.update(ctx)
            return _PREDICTION

        pm.analyze = pm_analyze

        started = [p.start() for p in patches.values()]
        try:
            await run_pipeline(_TRANSCRIPT, _PRICE_DATA, settings=settings)
        finally:
            for p in patches.values():
                p.stop()

        assert received["sentiment"] == _SENTIMENT_REPORT

    @pytest.mark.asyncio
    async def test_portfolio_manager_receives_technical(self):
        patches, fa, sa, ta, bull, bear, pm = _patch_agents(2)
        settings = _make_settings(2)

        received: dict = {}

        async def pm_analyze(ctx):
            received.update(ctx)
            return _PREDICTION

        pm.analyze = pm_analyze

        started = [p.start() for p in patches.values()]
        try:
            await run_pipeline(_TRANSCRIPT, _PRICE_DATA, settings=settings)
        finally:
            for p in patches.values():
                p.stop()

        assert received["technical"] == _TECHNICAL_REPORT

    @pytest.mark.asyncio
    async def test_portfolio_manager_receives_full_debate(self):
        patches, fa, sa, ta, bull, bear, pm = _patch_agents(2)
        settings = _make_settings(2)

        received: dict = {}

        async def pm_analyze(ctx):
            received.update(ctx)
            return _PREDICTION

        pm.analyze = pm_analyze

        started = [p.start() for p in patches.values()]
        try:
            await run_pipeline(_TRANSCRIPT, _PRICE_DATA, settings=settings)
        finally:
            for p in patches.values():
                p.stop()

        assert len(received["debate"]) == 2

    @pytest.mark.asyncio
    async def test_zero_rounds_portfolio_manager_receives_empty_debate(self):
        patches, fa, sa, ta, bull, bear, pm = _patch_agents(0)
        settings = _make_settings(0)

        received: dict = {}

        async def pm_analyze(ctx):
            received.update(ctx)
            return _PREDICTION

        pm.analyze = pm_analyze

        started = [p.start() for p in patches.values()]
        try:
            await run_pipeline(_TRANSCRIPT, _PRICE_DATA, settings=settings)
        finally:
            for p in patches.values():
                p.stop()

        assert received["debate"] == []


# ---------------------------------------------------------------------------
# Test: run_pipeline return value
# ---------------------------------------------------------------------------


class TestRunPipeline:
    @pytest.mark.asyncio
    async def test_returns_prediction_dict(self):
        prediction, _ = await _run()
        assert prediction == _PREDICTION

    @pytest.mark.asyncio
    async def test_returns_direction_key(self):
        prediction, _ = await _run()
        assert "direction" in prediction
        assert prediction["direction"] in ("up", "down", "neutral")

    @pytest.mark.asyncio
    async def test_returns_confidence_key(self):
        prediction, _ = await _run()
        assert "confidence" in prediction

    @pytest.mark.asyncio
    async def test_returns_reasoning_key(self):
        prediction, _ = await _run()
        assert "reasoning" in prediction

    @pytest.mark.asyncio
    async def test_returns_weighted_signals_key(self):
        prediction, _ = await _run()
        assert "weighted_signals" in prediction

    @pytest.mark.asyncio
    async def test_run_pipeline_is_async(self):
        import inspect
        assert inspect.iscoroutinefunction(run_pipeline)

    @pytest.mark.asyncio
    async def test_zero_rounds_still_returns_prediction(self):
        patches, fa, sa, ta, bull, bear, pm = _patch_agents(0)
        settings = _make_settings(0)

        started = [p.start() for p in patches.values()]
        try:
            prediction = await run_pipeline(_TRANSCRIPT, _PRICE_DATA, settings=settings)
        finally:
            for p in patches.values():
                p.stop()

        assert prediction == _PREDICTION
