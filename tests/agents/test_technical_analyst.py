"""Unit tests for backend/agents/technical_analyst.py.

All LLM calls are intercepted via AsyncMock — no network access or API keys
required.  Tests verify:
  - analyze() returns a valid signal dict on good LLM output
  - analyze() raises ValueError when the LLM returns non-JSON
  - The prompt forwarded to _call_llm contains the price_data values
  - use_deep_model=False is used (technical extraction uses the quick model)
  - The agent inherits from BaseAgent
  - Missing "price_data" key in context raises KeyError
"""

import pytest
from unittest.mock import AsyncMock, patch

from backend.agents.base_agent import BaseAgent
from backend.agents.technical_analyst import TechnicalAnalyst
from backend.config import Settings


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_VALID_RESPONSE = {
    "signal": "bearish",
    "key_points": [
        "Stock up 18% in the 30 days before earnings — likely priced for perfection",
        "RSI at 74 indicates overbought conditions heading into the print",
        "Volume declining over the past week suggests distribution",
        "Implied move of 8% exceeds historical average of 5%",
    ],
    "confidence": 0.68,
}

_SAMPLE_PRICE_DATA = {
    "5d_return": 0.042,
    "30d_return": 0.18,
    "rsi": 74.3,
    "volume_trend": "declining",
    "implied_move": 0.08,
    "historical_move": 0.05,
}


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


def _make_agent(**setting_overrides) -> TechnicalAnalyst:
    return TechnicalAnalyst(settings=_make_settings(**setting_overrides))


# ---------------------------------------------------------------------------
# Inheritance and construction
# ---------------------------------------------------------------------------


class TestTechnicalAnalystConstruction:
    def test_inherits_from_base_agent(self):
        assert issubclass(TechnicalAnalyst, BaseAgent)

    def test_instantiates_with_default_settings(self):
        """Constructor must not raise when called without arguments."""
        with patch("backend.agents.technical_analyst.Settings"):
            agent = _make_agent()
        assert isinstance(agent, TechnicalAnalyst)

    def test_accepts_custom_settings(self):
        settings = _make_settings(quick_model="custom-quick")
        agent = TechnicalAnalyst(settings=settings)
        assert agent._settings.quick_model == "custom-quick"


# ---------------------------------------------------------------------------
# analyze() — happy path
# ---------------------------------------------------------------------------


class TestTechnicalAnalystAnalyze:
    def setup_method(self):
        self.agent = _make_agent()

    @pytest.mark.asyncio
    async def test_returns_signal_dict_on_valid_response(self):
        self.agent._call_llm = AsyncMock(return_value=_VALID_RESPONSE)
        result = await self.agent.analyze({"price_data": _SAMPLE_PRICE_DATA})
        assert result == _VALID_RESPONSE

    @pytest.mark.asyncio
    async def test_signal_is_one_of_allowed_values(self):
        for signal in ("bullish", "bearish", "neutral"):
            response = {**_VALID_RESPONSE, "signal": signal}
            self.agent._call_llm = AsyncMock(return_value=response)
            result = await self.agent.analyze({"price_data": _SAMPLE_PRICE_DATA})
            assert result["signal"] == signal

    @pytest.mark.asyncio
    async def test_key_points_is_list(self):
        self.agent._call_llm = AsyncMock(return_value=_VALID_RESPONSE)
        result = await self.agent.analyze({"price_data": _SAMPLE_PRICE_DATA})
        assert isinstance(result["key_points"], list)
        assert len(result["key_points"]) > 0

    @pytest.mark.asyncio
    async def test_confidence_is_float(self):
        self.agent._call_llm = AsyncMock(return_value=_VALID_RESPONSE)
        result = await self.agent.analyze({"price_data": _SAMPLE_PRICE_DATA})
        assert isinstance(result["confidence"], float)
        assert 0.0 <= result["confidence"] <= 1.0


# ---------------------------------------------------------------------------
# analyze() — prompt construction
# ---------------------------------------------------------------------------


class TestTechnicalAnalystPrompt:
    def setup_method(self):
        self.agent = _make_agent()

    @pytest.mark.asyncio
    async def test_prompt_contains_price_data_values(self):
        """Each value from price_data must appear in the prompt."""
        captured = {}

        async def capture_call(prompt, use_deep_model=False):
            captured["prompt"] = prompt
            captured["use_deep_model"] = use_deep_model
            return _VALID_RESPONSE

        self.agent._call_llm = capture_call
        await self.agent.analyze({"price_data": _SAMPLE_PRICE_DATA})
        for key, value in _SAMPLE_PRICE_DATA.items():
            assert str(value) in captured["prompt"], (
                f"Expected price_data value {key}={value!r} in prompt"
            )

    @pytest.mark.asyncio
    async def test_prompt_contains_price_data_keys(self):
        """Each key from price_data must appear in the prompt."""
        captured = {}

        async def capture_call(prompt, use_deep_model=False):
            captured["prompt"] = prompt
            return _VALID_RESPONSE

        self.agent._call_llm = capture_call
        await self.agent.analyze({"price_data": _SAMPLE_PRICE_DATA})
        for key in _SAMPLE_PRICE_DATA:
            assert key in captured["prompt"], (
                f"Expected price_data key {key!r} in prompt"
            )

    @pytest.mark.asyncio
    async def test_uses_quick_model(self):
        """Technical extraction must use use_deep_model=False."""
        captured = {}

        async def capture_call(prompt, use_deep_model=False):
            captured["use_deep_model"] = use_deep_model
            return _VALID_RESPONSE

        self.agent._call_llm = capture_call
        await self.agent.analyze({"price_data": _SAMPLE_PRICE_DATA})
        assert captured["use_deep_model"] is False

    @pytest.mark.asyncio
    async def test_prompt_instructs_json_only_output(self):
        """Prompt must tell the model to return raw JSON with no prose."""
        captured = {}

        async def capture_call(prompt, use_deep_model=False):
            captured["prompt"] = prompt
            return _VALID_RESPONSE

        self.agent._call_llm = capture_call
        await self.agent.analyze({"price_data": _SAMPLE_PRICE_DATA})
        assert "json" in captured["prompt"].lower()

    @pytest.mark.asyncio
    async def test_different_price_data_produces_different_prompts(self):
        """Two different price_data inputs must produce two different prompts."""
        prompts = []

        async def capture_call(prompt, use_deep_model=False):
            prompts.append(prompt)
            return _VALID_RESPONSE

        self.agent._call_llm = capture_call
        await self.agent.analyze({"price_data": {"rsi": 30, "5d_return": -0.05}})
        await self.agent.analyze({"price_data": {"rsi": 75, "5d_return": 0.10}})
        assert prompts[0] != prompts[1]

    @pytest.mark.asyncio
    async def test_prompt_covers_technical_dimensions(self):
        """Prompt must reference RSI, volume, and implied move analysis."""
        captured = {}

        async def capture_call(prompt, use_deep_model=False):
            captured["prompt"] = prompt
            return _VALID_RESPONSE

        self.agent._call_llm = capture_call
        await self.agent.analyze({"price_data": _SAMPLE_PRICE_DATA})
        prompt_lower = captured["prompt"].lower()
        assert "rsi" in prompt_lower
        assert "volume" in prompt_lower
        assert "implied" in prompt_lower


# ---------------------------------------------------------------------------
# analyze() — error handling
# ---------------------------------------------------------------------------


class TestTechnicalAnalystErrorHandling:
    def setup_method(self):
        self.agent = _make_agent()

    @pytest.mark.asyncio
    async def test_raises_value_error_on_non_json_llm_response(self):
        """When the LLM returns prose instead of JSON, ValueError must propagate."""
        self.agent._call_llm = AsyncMock(
            side_effect=ValueError("LLM response is not valid JSON")
        )
        with pytest.raises(ValueError, match="not valid JSON"):
            await self.agent.analyze({"price_data": _SAMPLE_PRICE_DATA})

    @pytest.mark.asyncio
    async def test_raises_key_error_on_missing_price_data(self):
        """Missing 'price_data' key in context must raise KeyError immediately."""
        with pytest.raises(KeyError):
            await self.agent.analyze({})

    @pytest.mark.asyncio
    async def test_raises_key_error_on_empty_context(self):
        with pytest.raises(KeyError):
            await self.agent.analyze({"ticker": "AAPL"})

    @pytest.mark.asyncio
    async def test_raises_key_error_when_transcript_provided_instead(self):
        """Wrong context key must raise KeyError — not silently succeed."""
        with pytest.raises(KeyError):
            await self.agent.analyze({"transcript": "Some transcript text"})

    @pytest.mark.asyncio
    async def test_empty_price_data_dict_is_forwarded(self):
        """An empty price_data dict is valid input — let the LLM handle it."""
        captured = {}

        async def capture_call(prompt, use_deep_model=False):
            captured["prompt"] = prompt
            return _VALID_RESPONSE

        self.agent._call_llm = capture_call
        await self.agent.analyze({"price_data": {}})
        assert "prompt" in captured
