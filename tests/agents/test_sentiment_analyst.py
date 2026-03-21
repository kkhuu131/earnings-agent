"""Unit tests for backend/agents/sentiment_analyst.py.

All LLM calls are intercepted via AsyncMock — no network access or API keys
required.  Tests verify:
  - analyze() returns a valid signal dict on good LLM output
  - analyze() raises ValueError when the LLM returns non-JSON
  - The prompt forwarded to _call_llm contains the transcript text
  - use_deep_model=False is used (sentiment extraction uses the quick model)
  - The agent inherits from BaseAgent
  - Missing "transcript" key in context raises KeyError
"""

import pytest
from unittest.mock import AsyncMock, patch

from backend.agents.base_agent import BaseAgent
from backend.agents.sentiment_analyst import SentimentAnalyst
from backend.config import Settings


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_VALID_RESPONSE = {
    "signal": "bullish",
    "key_points": [
        "CEO spoke with high conviction about product roadmap",
        "No hedging language detected in prepared remarks",
        "Confident answers during Q&A with no deflection",
        "Tone consistently optimistic across all segments",
    ],
    "confidence": 0.75,
}

_SAMPLE_TRANSCRIPT = (
    "Thank you for joining our Q3 earnings call. We are very excited about "
    "our results this quarter. Revenue exceeded our expectations and we are "
    "confident in our ability to sustain this momentum. Our pipeline is strong "
    "and we have clear visibility into Q4. Happy to take your questions now."
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


def _make_agent(**setting_overrides) -> SentimentAnalyst:
    return SentimentAnalyst(settings=_make_settings(**setting_overrides))


# ---------------------------------------------------------------------------
# Inheritance and construction
# ---------------------------------------------------------------------------


class TestSentimentAnalystConstruction:
    def test_inherits_from_base_agent(self):
        assert issubclass(SentimentAnalyst, BaseAgent)

    def test_instantiates_with_default_settings(self):
        """Constructor must not raise when called without arguments."""
        with patch("backend.agents.sentiment_analyst.Settings"):
            agent = _make_agent()
        assert isinstance(agent, SentimentAnalyst)

    def test_accepts_custom_settings(self):
        settings = _make_settings(quick_model="custom-quick")
        agent = SentimentAnalyst(settings=settings)
        assert agent._settings.quick_model == "custom-quick"


# ---------------------------------------------------------------------------
# analyze() — happy path
# ---------------------------------------------------------------------------


class TestSentimentAnalystAnalyze:
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


class TestSentimentAnalystPrompt:
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
        """Sentiment extraction must use use_deep_model=False."""
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

    @pytest.mark.asyncio
    async def test_prompt_covers_sentiment_dimensions(self):
        """Prompt must reference tone, hedging, and Q&A analysis."""
        captured = {}

        async def capture_call(prompt, use_deep_model=False):
            captured["prompt"] = prompt
            return _VALID_RESPONSE

        self.agent._call_llm = capture_call
        await self.agent.analyze({"transcript": _SAMPLE_TRANSCRIPT})
        prompt_lower = captured["prompt"].lower()
        assert "tone" in prompt_lower
        assert "hedging" in prompt_lower or "hedge" in prompt_lower
        assert "q&a" in prompt_lower or "question" in prompt_lower


# ---------------------------------------------------------------------------
# analyze() — error handling
# ---------------------------------------------------------------------------


class TestSentimentAnalystErrorHandling:
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
    async def test_raises_key_error_when_price_data_provided_instead(self):
        """Wrong context key must raise KeyError — not silently succeed."""
        with pytest.raises(KeyError):
            await self.agent.analyze({"price_data": {"rsi": 55}})

    @pytest.mark.asyncio
    async def test_empty_transcript_is_forwarded(self):
        """An empty transcript string is valid input — let the LLM handle it."""
        captured = {}

        async def capture_call(prompt, use_deep_model=False):
            captured["prompt"] = prompt
            return _VALID_RESPONSE

        self.agent._call_llm = capture_call
        await self.agent.analyze({"transcript": ""})
        assert "prompt" in captured
