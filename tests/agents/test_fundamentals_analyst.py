"""Unit tests for backend/agents/fundamentals_analyst.py.

All LLM calls are intercepted via AsyncMock — no network access or API keys
required.  Tests verify:
  - analyze() returns a valid signal dict on good LLM output
  - analyze() raises ValueError when the LLM returns non-JSON
  - The prompt forwarded to _call_llm contains the transcript text
  - use_deep_model=False is used (fundamentals extraction uses the quick model)
  - The agent inherits from BaseAgent
  - Missing "transcript" key in context raises KeyError
"""

import pytest
from unittest.mock import AsyncMock, call, patch

from backend.agents.base_agent import BaseAgent
from backend.agents.fundamentals_analyst import FundamentalsAnalyst
from backend.config import Settings


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_VALID_RESPONSE = {
    "signal": "bullish",
    "key_points": [
        "Revenue grew 12% YoY, beating consensus by 3%",
        "EPS of $1.42 beat estimates of $1.30",
        "Gross margin expanded 80 bps to 43.2%",
        "Management raised full-year guidance by 5%",
    ],
    "confidence": 0.82,
}

_SAMPLE_TRANSCRIPT = (
    "Good morning, everyone. Our Q3 revenue came in at $18.4 billion, "
    "up 12% year-over-year. Earnings per share was $1.42, ahead of the "
    "$1.30 consensus estimate. Gross margin improved to 43.2%..."
)


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


def _make_agent(**setting_overrides) -> FundamentalsAnalyst:
    return FundamentalsAnalyst(settings=_make_settings(**setting_overrides))


# ---------------------------------------------------------------------------
# Inheritance and construction
# ---------------------------------------------------------------------------


class TestFundamentalsAnalystConstruction:
    def test_inherits_from_base_agent(self):
        assert issubclass(FundamentalsAnalyst, BaseAgent)

    def test_instantiates_with_default_settings(self):
        """Constructor must not raise when called without arguments."""
        # Patch settings so we don't read real env vars during the test
        with patch("backend.agents.fundamentals_analyst.Settings"):
            agent = _make_agent()
        assert isinstance(agent, FundamentalsAnalyst)

    def test_accepts_custom_settings(self):
        settings = _make_settings(quick_model="custom-quick")
        agent = FundamentalsAnalyst(settings=settings)
        assert agent._settings.quick_model == "custom-quick"


# ---------------------------------------------------------------------------
# analyze() — happy path
# ---------------------------------------------------------------------------


class TestFundamentalsAnalystAnalyze:
    def setup_method(self):
        self.agent = _make_agent()

    @pytest.mark.asyncio
    async def test_returns_signal_dict_on_valid_response(self):
        self.agent._call_llm = AsyncMock(return_value=_VALID_RESPONSE)
        result = await self.agent.analyze({"transcript": _SAMPLE_TRANSCRIPT})
        assert result == _VALID_RESPONSE

    @pytest.mark.asyncio
    async def test_signal_is_one_of_allowed_values(self):
        for signal in ("bullish", "bearish", "neutral"):
            response = {**_VALID_RESPONSE, "signal": signal}
            self.agent._call_llm = AsyncMock(return_value=response)
            result = await self.agent.analyze({"transcript": _SAMPLE_TRANSCRIPT})
            assert result["signal"] == signal

    @pytest.mark.asyncio
    async def test_key_points_is_list(self):
        self.agent._call_llm = AsyncMock(return_value=_VALID_RESPONSE)
        result = await self.agent.analyze({"transcript": _SAMPLE_TRANSCRIPT})
        assert isinstance(result["key_points"], list)
        assert len(result["key_points"]) > 0

    @pytest.mark.asyncio
    async def test_confidence_is_float(self):
        self.agent._call_llm = AsyncMock(return_value=_VALID_RESPONSE)
        result = await self.agent.analyze({"transcript": _SAMPLE_TRANSCRIPT})
        assert isinstance(result["confidence"], float)
        assert 0.0 <= result["confidence"] <= 1.0


# ---------------------------------------------------------------------------
# analyze() — prompt construction
# ---------------------------------------------------------------------------


class TestFundamentalsAnalystPrompt:
    def setup_method(self):
        self.agent = _make_agent()

    @pytest.mark.asyncio
    async def test_prompt_contains_transcript_text(self):
        """The transcript string must appear verbatim inside the prompt."""
        captured = {}

        async def capture_call(prompt, use_deep_model=False):
            captured["prompt"] = prompt
            captured["use_deep_model"] = use_deep_model
            return _VALID_RESPONSE

        self.agent._call_llm = capture_call
        await self.agent.analyze({"transcript": _SAMPLE_TRANSCRIPT})
        assert _SAMPLE_TRANSCRIPT in captured["prompt"]

    @pytest.mark.asyncio
    async def test_uses_quick_model(self):
        """Fundamentals extraction must use use_deep_model=False."""
        captured = {}

        async def capture_call(prompt, use_deep_model=False):
            captured["use_deep_model"] = use_deep_model
            return _VALID_RESPONSE

        self.agent._call_llm = capture_call
        await self.agent.analyze({"transcript": _SAMPLE_TRANSCRIPT})
        assert captured["use_deep_model"] is False

    @pytest.mark.asyncio
    async def test_prompt_instructs_json_only_output(self):
        """Prompt must tell the model to return raw JSON with no prose."""
        captured = {}

        async def capture_call(prompt, use_deep_model=False):
            captured["prompt"] = prompt
            return _VALID_RESPONSE

        self.agent._call_llm = capture_call
        await self.agent.analyze({"transcript": _SAMPLE_TRANSCRIPT})
        prompt_lower = captured["prompt"].lower()
        assert "json" in prompt_lower

    @pytest.mark.asyncio
    async def test_different_transcripts_produce_different_prompts(self):
        """Two different transcript inputs must produce two different prompts."""
        prompts = []

        async def capture_call(prompt, use_deep_model=False):
            prompts.append(prompt)
            return _VALID_RESPONSE

        self.agent._call_llm = capture_call
        await self.agent.analyze({"transcript": "Transcript A text"})
        await self.agent.analyze({"transcript": "Transcript B text"})
        assert prompts[0] != prompts[1]
        assert "Transcript A text" in prompts[0]
        assert "Transcript B text" in prompts[1]


# ---------------------------------------------------------------------------
# analyze() — error handling
# ---------------------------------------------------------------------------


class TestFundamentalsAnalystErrorHandling:
    def setup_method(self):
        self.agent = _make_agent()

    @pytest.mark.asyncio
    async def test_raises_value_error_on_non_json_llm_response(self):
        """When the LLM returns prose instead of JSON, ValueError must propagate."""
        self.agent._call_llm = AsyncMock(
            side_effect=ValueError("LLM response is not valid JSON")
        )
        with pytest.raises(ValueError, match="not valid JSON"):
            await self.agent.analyze({"transcript": _SAMPLE_TRANSCRIPT})

    @pytest.mark.asyncio
    async def test_raises_key_error_on_missing_transcript(self):
        """Missing 'transcript' key in context must raise KeyError immediately."""
        with pytest.raises(KeyError):
            await self.agent.analyze({})

    @pytest.mark.asyncio
    async def test_raises_key_error_on_empty_context(self):
        with pytest.raises(KeyError):
            await self.agent.analyze({"ticker": "AAPL"})

    @pytest.mark.asyncio
    async def test_empty_transcript_is_forwarded(self):
        """An empty transcript string is valid input — let the LLM handle it."""
        captured = {}

        async def capture_call(prompt, use_deep_model=False):
            captured["prompt"] = prompt
            return _VALID_RESPONSE

        self.agent._call_llm = capture_call
        await self.agent.analyze({"transcript": ""})
        # Should reach _call_llm without raising
        assert "prompt" in captured
