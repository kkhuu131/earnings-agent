"""Unit tests for backend/agents/bull_researcher.py.

All LLM calls are intercepted via AsyncMock — no network access or API keys
required.  Tests verify:
  - analyze() returns a valid argument dict on good LLM output
  - analyze() raises ValueError when the LLM returns non-JSON
  - Prompt forwarded to _call_llm contains all three analyst signal values
  - use_deep_model=True is used (debate construction uses the deep model)
  - The agent inherits from BaseAgent
  - Missing required context keys raise KeyError
  - analyze_rebuttal() prompt contains the opposing argument string
  - analyze_rebuttal() output schema is identical to analyze()
  - Missing "opposing_argument" in rebuttal context raises KeyError
"""

import pytest
from unittest.mock import AsyncMock

from backend.agents.base_agent import BaseAgent
from backend.agents.bull_researcher import BullResearcher
from backend.config import Settings


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_VALID_RESPONSE = {
    "argument": (
        "Strong revenue growth of 18% YoY combined with confident management "
        "tone and bullish technical setup signals meaningful upside post-print."
    ),
    "confidence": 0.82,
    "rebuttals": [
        "Margin compression concerns are already priced in at current multiples.",
        "Volume surge indicates institutional accumulation, not distribution.",
    ],
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

_OPPOSING_ARGUMENT = (
    "Bear case: margins will compress next quarter as input costs rise and "
    "management guidance was vague on capex trajectory."
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


def _make_agent(**setting_overrides) -> BullResearcher:
    return BullResearcher(settings=_make_settings(**setting_overrides))


# ---------------------------------------------------------------------------
# Inheritance and construction
# ---------------------------------------------------------------------------


class TestBullResearcherConstruction:
    def test_inherits_from_base_agent(self):
        assert issubclass(BullResearcher, BaseAgent)

    def test_accepts_custom_settings(self):
        settings = _make_settings(deep_model="custom-deep")
        agent = BullResearcher(settings=settings)
        assert agent._settings.deep_model == "custom-deep"


# ---------------------------------------------------------------------------
# analyze() — happy path
# ---------------------------------------------------------------------------


class TestBullResearcherAnalyze:
    def setup_method(self):
        self.agent = _make_agent()

    @pytest.mark.asyncio
    async def test_returns_argument_dict_on_valid_response(self):
        self.agent._call_llm = AsyncMock(return_value=_VALID_RESPONSE)
        result = await self.agent.analyze(_ANALYST_REPORTS)
        assert result == _VALID_RESPONSE

    @pytest.mark.asyncio
    async def test_argument_is_non_empty_string(self):
        self.agent._call_llm = AsyncMock(return_value=_VALID_RESPONSE)
        result = await self.agent.analyze(_ANALYST_REPORTS)
        assert isinstance(result["argument"], str)
        assert len(result["argument"]) > 0

    @pytest.mark.asyncio
    async def test_confidence_is_float_in_range(self):
        self.agent._call_llm = AsyncMock(return_value=_VALID_RESPONSE)
        result = await self.agent.analyze(_ANALYST_REPORTS)
        assert isinstance(result["confidence"], float)
        assert 0.0 <= result["confidence"] <= 1.0

    @pytest.mark.asyncio
    async def test_rebuttals_is_list(self):
        self.agent._call_llm = AsyncMock(return_value=_VALID_RESPONSE)
        result = await self.agent.analyze(_ANALYST_REPORTS)
        assert isinstance(result["rebuttals"], list)

    @pytest.mark.asyncio
    async def test_rebuttals_can_be_empty(self):
        response = {**_VALID_RESPONSE, "rebuttals": []}
        self.agent._call_llm = AsyncMock(return_value=response)
        result = await self.agent.analyze(_ANALYST_REPORTS)
        assert result["rebuttals"] == []


# ---------------------------------------------------------------------------
# analyze() — prompt construction
# ---------------------------------------------------------------------------


class TestBullResearcherPrompt:
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
        await self.agent.analyze(_ANALYST_REPORTS)
        assert _ANALYST_REPORTS["fundamentals"]["signal"] in captured["prompt"]

    @pytest.mark.asyncio
    async def test_prompt_contains_sentiment_signal(self):
        captured = {}

        async def capture(prompt, use_deep_model=False):
            captured["prompt"] = prompt
            return _VALID_RESPONSE

        self.agent._call_llm = capture
        await self.agent.analyze(_ANALYST_REPORTS)
        assert _ANALYST_REPORTS["sentiment"]["signal"] in captured["prompt"]

    @pytest.mark.asyncio
    async def test_prompt_contains_technical_signal(self):
        captured = {}

        async def capture(prompt, use_deep_model=False):
            captured["prompt"] = prompt
            return _VALID_RESPONSE

        self.agent._call_llm = capture
        await self.agent.analyze(_ANALYST_REPORTS)
        assert _ANALYST_REPORTS["technical"]["signal"] in captured["prompt"]

    @pytest.mark.asyncio
    async def test_prompt_contains_fundamentals_key_points(self):
        captured = {}

        async def capture(prompt, use_deep_model=False):
            captured["prompt"] = prompt
            return _VALID_RESPONSE

        self.agent._call_llm = capture
        await self.agent.analyze(_ANALYST_REPORTS)
        for point in _ANALYST_REPORTS["fundamentals"]["key_points"]:
            assert point in captured["prompt"]

    @pytest.mark.asyncio
    async def test_uses_deep_model(self):
        captured = {}

        async def capture(prompt, use_deep_model=False):
            captured["use_deep_model"] = use_deep_model
            return _VALID_RESPONSE

        self.agent._call_llm = capture
        await self.agent.analyze(_ANALYST_REPORTS)
        assert captured["use_deep_model"] is True

    @pytest.mark.asyncio
    async def test_prompt_instructs_json_only_output(self):
        captured = {}

        async def capture(prompt, use_deep_model=False):
            captured["prompt"] = prompt
            return _VALID_RESPONSE

        self.agent._call_llm = capture
        await self.agent.analyze(_ANALYST_REPORTS)
        assert "json" in captured["prompt"].lower()

    @pytest.mark.asyncio
    async def test_different_reports_produce_different_prompts(self):
        prompts = []

        async def capture(prompt, use_deep_model=False):
            prompts.append(prompt)
            return _VALID_RESPONSE

        self.agent._call_llm = capture
        reports_a = {**_ANALYST_REPORTS, "fundamentals": {**_ANALYST_REPORTS["fundamentals"], "signal": "bullish"}}
        reports_b = {**_ANALYST_REPORTS, "fundamentals": {**_ANALYST_REPORTS["fundamentals"], "signal": "bearish"}}
        await self.agent.analyze(reports_a)
        await self.agent.analyze(reports_b)
        assert prompts[0] != prompts[1]


# ---------------------------------------------------------------------------
# analyze() — error handling
# ---------------------------------------------------------------------------


class TestBullResearcherErrorHandling:
    def setup_method(self):
        self.agent = _make_agent()

    @pytest.mark.asyncio
    async def test_raises_value_error_on_non_json_llm_response(self):
        self.agent._call_llm = AsyncMock(
            side_effect=ValueError("LLM response is not valid JSON")
        )
        with pytest.raises(ValueError, match="not valid JSON"):
            await self.agent.analyze(_ANALYST_REPORTS)

    @pytest.mark.asyncio
    async def test_raises_key_error_on_missing_fundamentals(self):
        context = {k: v for k, v in _ANALYST_REPORTS.items() if k != "fundamentals"}
        with pytest.raises(KeyError):
            await self.agent.analyze(context)

    @pytest.mark.asyncio
    async def test_raises_key_error_on_missing_sentiment(self):
        context = {k: v for k, v in _ANALYST_REPORTS.items() if k != "sentiment"}
        with pytest.raises(KeyError):
            await self.agent.analyze(context)

    @pytest.mark.asyncio
    async def test_raises_key_error_on_missing_technical(self):
        context = {k: v for k, v in _ANALYST_REPORTS.items() if k != "technical"}
        with pytest.raises(KeyError):
            await self.agent.analyze(context)

    @pytest.mark.asyncio
    async def test_raises_key_error_on_empty_context(self):
        with pytest.raises(KeyError):
            await self.agent.analyze({})


# ---------------------------------------------------------------------------
# analyze_rebuttal() — happy path
# ---------------------------------------------------------------------------


class TestBullResearcherRebuttal:
    def setup_method(self):
        self.agent = _make_agent()

    @pytest.mark.asyncio
    async def test_rebuttal_returns_same_schema(self):
        self.agent._call_llm = AsyncMock(return_value=_VALID_RESPONSE)
        context = {**_ANALYST_REPORTS, "opposing_argument": _OPPOSING_ARGUMENT}
        result = await self.agent.analyze_rebuttal(context)
        assert "argument" in result
        assert "confidence" in result
        assert "rebuttals" in result

    @pytest.mark.asyncio
    async def test_rebuttal_prompt_contains_opposing_argument(self):
        captured = {}

        async def capture(prompt, use_deep_model=False):
            captured["prompt"] = prompt
            return _VALID_RESPONSE

        self.agent._call_llm = capture
        context = {**_ANALYST_REPORTS, "opposing_argument": _OPPOSING_ARGUMENT}
        await self.agent.analyze_rebuttal(context)
        assert _OPPOSING_ARGUMENT in captured["prompt"]

    @pytest.mark.asyncio
    async def test_rebuttal_prompt_contains_all_signals(self):
        captured = {}

        async def capture(prompt, use_deep_model=False):
            captured["prompt"] = prompt
            return _VALID_RESPONSE

        self.agent._call_llm = capture
        context = {**_ANALYST_REPORTS, "opposing_argument": _OPPOSING_ARGUMENT}
        await self.agent.analyze_rebuttal(context)
        assert _ANALYST_REPORTS["fundamentals"]["signal"] in captured["prompt"]
        assert _ANALYST_REPORTS["sentiment"]["signal"] in captured["prompt"]
        assert _ANALYST_REPORTS["technical"]["signal"] in captured["prompt"]

    @pytest.mark.asyncio
    async def test_rebuttal_uses_deep_model(self):
        captured = {}

        async def capture(prompt, use_deep_model=False):
            captured["use_deep_model"] = use_deep_model
            return _VALID_RESPONSE

        self.agent._call_llm = capture
        context = {**_ANALYST_REPORTS, "opposing_argument": _OPPOSING_ARGUMENT}
        await self.agent.analyze_rebuttal(context)
        assert captured["use_deep_model"] is True

    @pytest.mark.asyncio
    async def test_rebuttal_raises_key_error_on_missing_opposing_argument(self):
        with pytest.raises(KeyError):
            await self.agent.analyze_rebuttal(_ANALYST_REPORTS)

    @pytest.mark.asyncio
    async def test_rebuttal_raises_key_error_on_missing_fundamentals(self):
        context = {
            k: v for k, v in _ANALYST_REPORTS.items() if k != "fundamentals"
        }
        context["opposing_argument"] = _OPPOSING_ARGUMENT
        with pytest.raises(KeyError):
            await self.agent.analyze_rebuttal(context)

    @pytest.mark.asyncio
    async def test_rebuttal_prompt_differs_from_analyze_prompt(self):
        """Rebuttal prompt must include the opposing argument; analyze prompt must not."""
        prompts = []

        async def capture(prompt, use_deep_model=False):
            prompts.append(prompt)
            return _VALID_RESPONSE

        self.agent._call_llm = capture
        await self.agent.analyze(_ANALYST_REPORTS)
        context = {**_ANALYST_REPORTS, "opposing_argument": _OPPOSING_ARGUMENT}
        await self.agent.analyze_rebuttal(context)

        assert _OPPOSING_ARGUMENT not in prompts[0]
        assert _OPPOSING_ARGUMENT in prompts[1]
