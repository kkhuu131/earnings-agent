"""Unit tests for backend/agents/portfolio_manager.py.

All LLM calls are intercepted via AsyncMock — no network access or API keys
required.  Tests verify:
  - analyze() returns a valid prediction dict on good LLM output
  - analyze() raises ValueError when the LLM returns non-JSON
  - Prompt forwarded to _call_llm contains all three analyst signals
  - Prompt contains content from both sides of the debate transcript
  - use_deep_model=True is always used (final decision is reasoning-heavy)
  - Missing required context keys raise KeyError
  - weighted_signals has entries for all five agents
  - All weights sum to 1.0 (equal weighting: 0.2 each)
  - The agent inherits from BaseAgent
"""

import pytest
from unittest.mock import AsyncMock

from backend.agents.base_agent import BaseAgent
from backend.agents.portfolio_manager import PortfolioManager
from backend.config import Settings


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_VALID_RESPONSE = {
    "direction": "up",
    "confidence": 0.74,
    "reasoning": (
        "Three of five signals lean bullish.  The bull researcher's rebuttal "
        "convincingly addressed margin concerns.  Fundamentals beat is the "
        "strongest driver — initiating a long bias."
    ),
    "weighted_signals": {
        "fundamentals": {"signal": "bullish", "weight": 0.2},
        "sentiment":    {"signal": "bullish", "weight": 0.2},
        "technical":    {"signal": "neutral", "weight": 0.2},
        "bull":         {"signal": "bullish", "weight": 0.2},
        "bear":         {"signal": "bearish", "weight": 0.2},
    },
}

_ANALYST_REPORTS = {
    "fundamentals": {
        "signal": "bullish",
        "key_points": [
            "Revenue grew 18% YoY, ahead of 15% consensus",
            "EPS beat by $0.12",
            "Gross margin expanded 120bps",
        ],
        "confidence": 0.85,
    },
    "sentiment": {
        "signal": "bullish",
        "key_points": [
            "CEO spoke with high conviction",
            "No hedging language detected",
            "Confident Q&A responses",
        ],
        "confidence": 0.75,
    },
    "technical": {
        "signal": "neutral",
        "key_points": [
            "RSI at 58, not overbought",
            "5-day return flat ahead of print",
            "Volume trending higher",
        ],
        "confidence": 0.60,
    },
}

_DEBATE = [
    {
        "bull": {
            "argument": "Strong revenue growth signals sustained demand.",
            "confidence": 0.82,
            "rebuttals": ["Margin compression concerns are already priced in."],
        },
        "bear": {
            "argument": "Input costs will squeeze margins next quarter.",
            "confidence": 0.65,
            "rebuttals": ["Revenue beat may be a one-off channel fill."],
        },
    },
    {
        "bull": {
            "argument": "Management reiterated guidance; demand signals remain intact.",
            "confidence": 0.80,
            "rebuttals": ["Guidance reaffirmation directly contradicts the bear thesis."],
        },
        "bear": {
            "argument": "Guidance language was vague on capex trajectory.",
            "confidence": 0.60,
            "rebuttals": ["Reaffirmed guidance does not address cost structure."],
        },
    },
]

_FULL_CONTEXT = {**_ANALYST_REPORTS, "debate": _DEBATE}


def _make_settings(**overrides) -> Settings:
    base = {
        "database_url": "postgresql+asyncpg://localhost/test",
        "llm_provider": "anthropic",
        "quick_model": "test-quick-model",
        "deep_model": "test-deep-model",
        "temperature": 0.0,
        "anthropic_api_key": "test-key",
    }
    base.update(overrides)
    return Settings(**base)


def _make_agent(**setting_overrides) -> PortfolioManager:
    return PortfolioManager(settings=_make_settings(**setting_overrides))


# ---------------------------------------------------------------------------
# Inheritance and construction
# ---------------------------------------------------------------------------


class TestPortfolioManagerConstruction:
    def test_inherits_from_base_agent(self):
        assert issubclass(PortfolioManager, BaseAgent)

    def test_accepts_custom_settings(self):
        settings = _make_settings(deep_model="custom-deep")
        agent = PortfolioManager(settings=settings)
        assert agent._settings.deep_model == "custom-deep"


# ---------------------------------------------------------------------------
# analyze() — happy path
# ---------------------------------------------------------------------------


class TestPortfolioManagerAnalyze:
    def setup_method(self):
        self.agent = _make_agent()

    @pytest.mark.asyncio
    async def test_returns_prediction_dict_on_valid_response(self):
        self.agent._call_llm = AsyncMock(return_value=_VALID_RESPONSE)
        result = await self.agent.analyze(_FULL_CONTEXT)
        assert result == _VALID_RESPONSE

    @pytest.mark.asyncio
    async def test_direction_is_string(self):
        self.agent._call_llm = AsyncMock(return_value=_VALID_RESPONSE)
        result = await self.agent.analyze(_FULL_CONTEXT)
        assert isinstance(result["direction"], str)
        assert result["direction"] in ("up", "down", "neutral")

    @pytest.mark.asyncio
    async def test_confidence_is_float_in_range(self):
        self.agent._call_llm = AsyncMock(return_value=_VALID_RESPONSE)
        result = await self.agent.analyze(_FULL_CONTEXT)
        assert isinstance(result["confidence"], float)
        assert 0.0 <= result["confidence"] <= 1.0

    @pytest.mark.asyncio
    async def test_reasoning_is_non_empty_string(self):
        self.agent._call_llm = AsyncMock(return_value=_VALID_RESPONSE)
        result = await self.agent.analyze(_FULL_CONTEXT)
        assert isinstance(result["reasoning"], str)
        assert len(result["reasoning"]) > 0

    @pytest.mark.asyncio
    async def test_weighted_signals_present(self):
        self.agent._call_llm = AsyncMock(return_value=_VALID_RESPONSE)
        result = await self.agent.analyze(_FULL_CONTEXT)
        assert "weighted_signals" in result

    @pytest.mark.asyncio
    async def test_all_five_agents_in_weighted_signals(self):
        self.agent._call_llm = AsyncMock(return_value=_VALID_RESPONSE)
        result = await self.agent.analyze(_FULL_CONTEXT)
        ws = result["weighted_signals"]
        for key in ("fundamentals", "sentiment", "technical", "bull", "bear"):
            assert key in ws, f"missing key: {key}"

    @pytest.mark.asyncio
    async def test_weights_sum_to_one(self):
        self.agent._call_llm = AsyncMock(return_value=_VALID_RESPONSE)
        result = await self.agent.analyze(_FULL_CONTEXT)
        total = sum(v["weight"] for v in result["weighted_signals"].values())
        assert abs(total - 1.0) < 1e-9

    @pytest.mark.asyncio
    async def test_each_weight_is_0_2(self):
        self.agent._call_llm = AsyncMock(return_value=_VALID_RESPONSE)
        result = await self.agent.analyze(_FULL_CONTEXT)
        for agent_name, entry in result["weighted_signals"].items():
            assert entry["weight"] == pytest.approx(0.2), (
                f"Expected weight 0.2 for {agent_name}, got {entry['weight']}"
            )

    @pytest.mark.asyncio
    async def test_empty_debate_list_is_accepted(self):
        self.agent._call_llm = AsyncMock(return_value=_VALID_RESPONSE)
        context = {**_ANALYST_REPORTS, "debate": []}
        result = await self.agent.analyze(context)
        assert result == _VALID_RESPONSE


# ---------------------------------------------------------------------------
# analyze() — prompt construction
# ---------------------------------------------------------------------------


class TestPortfolioManagerPrompt:
    def setup_method(self):
        self.agent = _make_agent()

    @pytest.mark.asyncio
    async def test_prompt_contains_fundamentals_signal(self):
        captured = {}

        async def capture(prompt, use_deep_model=False):
            captured["prompt"] = prompt
            captured["use_deep_model"] = use_deep_model
            return _VALID_RESPONSE

        self.agent._call_llm = capture
        await self.agent.analyze(_FULL_CONTEXT)
        assert _ANALYST_REPORTS["fundamentals"]["signal"] in captured["prompt"]

    @pytest.mark.asyncio
    async def test_prompt_contains_sentiment_signal(self):
        captured = {}

        async def capture(prompt, use_deep_model=False):
            captured["prompt"] = prompt
            return _VALID_RESPONSE

        self.agent._call_llm = capture
        await self.agent.analyze(_FULL_CONTEXT)
        assert _ANALYST_REPORTS["sentiment"]["signal"] in captured["prompt"]

    @pytest.mark.asyncio
    async def test_prompt_contains_technical_signal(self):
        captured = {}

        async def capture(prompt, use_deep_model=False):
            captured["prompt"] = prompt
            return _VALID_RESPONSE

        self.agent._call_llm = capture
        await self.agent.analyze(_FULL_CONTEXT)
        assert _ANALYST_REPORTS["technical"]["signal"] in captured["prompt"]

    @pytest.mark.asyncio
    async def test_prompt_contains_fundamentals_key_points(self):
        captured = {}

        async def capture(prompt, use_deep_model=False):
            captured["prompt"] = prompt
            return _VALID_RESPONSE

        self.agent._call_llm = capture
        await self.agent.analyze(_FULL_CONTEXT)
        for point in _ANALYST_REPORTS["fundamentals"]["key_points"]:
            assert point in captured["prompt"]

    @pytest.mark.asyncio
    async def test_prompt_contains_bull_argument(self):
        captured = {}

        async def capture(prompt, use_deep_model=False):
            captured["prompt"] = prompt
            return _VALID_RESPONSE

        self.agent._call_llm = capture
        await self.agent.analyze(_FULL_CONTEXT)
        assert _DEBATE[0]["bull"]["argument"] in captured["prompt"]

    @pytest.mark.asyncio
    async def test_prompt_contains_bear_argument(self):
        captured = {}

        async def capture(prompt, use_deep_model=False):
            captured["prompt"] = prompt
            return _VALID_RESPONSE

        self.agent._call_llm = capture
        await self.agent.analyze(_FULL_CONTEXT)
        assert _DEBATE[0]["bear"]["argument"] in captured["prompt"]

    @pytest.mark.asyncio
    async def test_prompt_contains_second_round_arguments(self):
        captured = {}

        async def capture(prompt, use_deep_model=False):
            captured["prompt"] = prompt
            return _VALID_RESPONSE

        self.agent._call_llm = capture
        await self.agent.analyze(_FULL_CONTEXT)
        assert _DEBATE[1]["bull"]["argument"] in captured["prompt"]
        assert _DEBATE[1]["bear"]["argument"] in captured["prompt"]

    @pytest.mark.asyncio
    async def test_uses_deep_model(self):
        captured = {}

        async def capture(prompt, use_deep_model=False):
            captured["use_deep_model"] = use_deep_model
            return _VALID_RESPONSE

        self.agent._call_llm = capture
        await self.agent.analyze(_FULL_CONTEXT)
        assert captured["use_deep_model"] is True

    @pytest.mark.asyncio
    async def test_prompt_instructs_json_only_output(self):
        captured = {}

        async def capture(prompt, use_deep_model=False):
            captured["prompt"] = prompt
            return _VALID_RESPONSE

        self.agent._call_llm = capture
        await self.agent.analyze(_FULL_CONTEXT)
        assert "json" in captured["prompt"].lower()

    @pytest.mark.asyncio
    async def test_different_signals_produce_different_prompts(self):
        prompts = []

        async def capture(prompt, use_deep_model=False):
            prompts.append(prompt)
            return _VALID_RESPONSE

        self.agent._call_llm = capture
        ctx_a = {**_FULL_CONTEXT, "fundamentals": {**_ANALYST_REPORTS["fundamentals"], "signal": "bullish"}}
        ctx_b = {**_FULL_CONTEXT, "fundamentals": {**_ANALYST_REPORTS["fundamentals"], "signal": "bearish"}}
        await self.agent.analyze(ctx_a)
        await self.agent.analyze(ctx_b)
        assert prompts[0] != prompts[1]


# ---------------------------------------------------------------------------
# analyze() — error handling
# ---------------------------------------------------------------------------


class TestPortfolioManagerErrorHandling:
    def setup_method(self):
        self.agent = _make_agent()

    @pytest.mark.asyncio
    async def test_raises_value_error_on_non_json_llm_response(self):
        self.agent._call_llm = AsyncMock(
            side_effect=ValueError("LLM response is not valid JSON")
        )
        with pytest.raises(ValueError, match="not valid JSON"):
            await self.agent.analyze(_FULL_CONTEXT)

    @pytest.mark.asyncio
    async def test_raises_key_error_on_missing_fundamentals(self):
        context = {k: v for k, v in _FULL_CONTEXT.items() if k != "fundamentals"}
        with pytest.raises(KeyError):
            await self.agent.analyze(context)

    @pytest.mark.asyncio
    async def test_raises_key_error_on_missing_sentiment(self):
        context = {k: v for k, v in _FULL_CONTEXT.items() if k != "sentiment"}
        with pytest.raises(KeyError):
            await self.agent.analyze(context)

    @pytest.mark.asyncio
    async def test_raises_key_error_on_missing_technical(self):
        context = {k: v for k, v in _FULL_CONTEXT.items() if k != "technical"}
        with pytest.raises(KeyError):
            await self.agent.analyze(context)

    @pytest.mark.asyncio
    async def test_raises_key_error_on_missing_debate(self):
        context = {k: v for k, v in _FULL_CONTEXT.items() if k != "debate"}
        with pytest.raises(KeyError):
            await self.agent.analyze(context)

    @pytest.mark.asyncio
    async def test_raises_key_error_on_empty_context(self):
        with pytest.raises(KeyError):
            await self.agent.analyze({})

    @pytest.mark.asyncio
    async def test_raises_key_error_on_debate_round_missing_bull(self):
        bad_debate = [{"bear": _DEBATE[0]["bear"]}]
        context = {**_ANALYST_REPORTS, "debate": bad_debate}
        with pytest.raises(KeyError):
            await self.agent.analyze(context)

    @pytest.mark.asyncio
    async def test_raises_key_error_on_debate_round_missing_bear(self):
        bad_debate = [{"bull": _DEBATE[0]["bull"]}]
        context = {**_ANALYST_REPORTS, "debate": bad_debate}
        with pytest.raises(KeyError):
            await self.agent.analyze(context)
