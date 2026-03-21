"""Unit tests for backend/agents/base_agent.py.

No real LLM calls are made — provider methods are replaced with AsyncMock so
tests run instantly without network access or API keys.

Tests verify:
  - _parse_json returns a dict for valid JSON
  - _parse_json strips markdown code fences before parsing
  - _parse_json raises ValueError on non-JSON text
  - _parse_json raises ValueError when JSON is valid but not a dict (e.g. list)
  - _call_llm routes to the correct provider method
  - _call_llm selects quick_model when use_deep_model=False
  - _call_llm selects deep_model when use_deep_model=True
  - _call_llm raises ValueError for an unknown provider
  - _call_llm propagates ValueError from _parse_json on bad LLM output
"""

import pytest
from unittest.mock import AsyncMock, patch

from backend.agents.base_agent import BaseAgent
from backend.config import Settings


# ---------------------------------------------------------------------------
# Concrete subclass used only in tests (BaseAgent is abstract)
# ---------------------------------------------------------------------------


class _DummyAgent(BaseAgent):
    """Minimal concrete subclass for testing BaseAgent methods."""

    async def analyze(self, context: dict) -> dict:  # pragma: no cover
        return {}


def _make_settings(**overrides) -> Settings:
    """Build a Settings instance with safe test defaults, allowing overrides."""
    base = {
        "database_url": "postgresql+asyncpg://localhost/test",
        "llm_provider": "anthropic",
        "quick_model": "test-quick-model",
        "deep_model": "test-deep-model",
        "temperature": 0.0,
        "anthropic_api_key": "test-key",
        "openai_api_key": "test-key",
        "google_api_key": "test-key",
    }
    base.update(overrides)
    return Settings(**base)


# ---------------------------------------------------------------------------
# _parse_json
# ---------------------------------------------------------------------------


class TestParseJson:
    def setup_method(self):
        self.agent = _DummyAgent(settings=_make_settings())

    def test_valid_json_returns_dict(self):
        raw = '{"signal": "bullish", "confidence": 0.9}'
        result = self.agent._parse_json(raw)
        assert result == {"signal": "bullish", "confidence": 0.9}

    def test_strips_json_code_fence(self):
        raw = '```json\n{"signal": "bearish"}\n```'
        result = self.agent._parse_json(raw)
        assert result == {"signal": "bearish"}

    def test_strips_plain_code_fence(self):
        raw = '```\n{"signal": "neutral"}\n```'
        result = self.agent._parse_json(raw)
        assert result == {"signal": "neutral"}

    def test_strips_leading_trailing_whitespace(self):
        raw = '   \n{"key": "value"}\n   '
        result = self.agent._parse_json(raw)
        assert result == {"key": "value"}

    def test_non_json_raises_value_error(self):
        with pytest.raises(ValueError, match="not valid JSON"):
            self.agent._parse_json("This is just plain text, not JSON.")

    def test_empty_string_raises_value_error(self):
        with pytest.raises(ValueError, match="not valid JSON"):
            self.agent._parse_json("")

    def test_json_array_raises_value_error(self):
        """A JSON array is valid JSON but not a dict — must raise."""
        with pytest.raises(ValueError, match="expected a JSON object"):
            self.agent._parse_json('[{"signal": "bullish"}]')

    def test_json_string_raises_value_error(self):
        with pytest.raises(ValueError, match="expected a JSON object"):
            self.agent._parse_json('"bullish"')

    def test_json_null_raises_value_error(self):
        with pytest.raises(ValueError, match="expected a JSON object"):
            self.agent._parse_json("null")

    def test_nested_json_preserved(self):
        raw = '{"signal": "bullish", "key_points": ["a", "b"], "confidence": 0.75}'
        result = self.agent._parse_json(raw)
        assert result["key_points"] == ["a", "b"]
        assert result["confidence"] == 0.75

    def test_markdown_fence_with_extra_whitespace(self):
        """Fences with spaces/newlines between the fence and content are handled."""
        raw = "```json\n\n  {\"x\": 1}\n\n```"
        result = self.agent._parse_json(raw)
        assert result == {"x": 1}


# ---------------------------------------------------------------------------
# _call_llm — model selection
# ---------------------------------------------------------------------------


class TestCallLlmModelSelection:
    """Verify that _call_llm passes the right model name to the provider method."""

    def setup_method(self):
        self.settings = _make_settings(
            llm_provider="anthropic",
            quick_model="quick-model-id",
            deep_model="deep-model-id",
        )
        self.agent = _DummyAgent(settings=self.settings)

    @pytest.mark.asyncio
    async def test_quick_model_selected_by_default(self):
        captured = {}

        async def fake_call_anthropic(prompt, model):
            captured["model"] = model
            return '{"ok": true}'

        self.agent._call_anthropic = fake_call_anthropic
        await self.agent._call_llm("test prompt", use_deep_model=False)
        assert captured["model"] == "quick-model-id"

    @pytest.mark.asyncio
    async def test_deep_model_selected_when_flag_set(self):
        captured = {}

        async def fake_call_anthropic(prompt, model):
            captured["model"] = model
            return '{"ok": true}'

        self.agent._call_anthropic = fake_call_anthropic
        await self.agent._call_llm("test prompt", use_deep_model=True)
        assert captured["model"] == "deep-model-id"


# ---------------------------------------------------------------------------
# _call_llm — provider routing
# ---------------------------------------------------------------------------


class TestCallLlmProviderRouting:
    """Verify that _call_llm dispatches to the correct provider method."""

    def _make_agent(self, provider: str) -> _DummyAgent:
        return _DummyAgent(settings=_make_settings(llm_provider=provider))

    @pytest.mark.asyncio
    async def test_routes_to_anthropic(self):
        agent = self._make_agent("anthropic")
        mock = AsyncMock(return_value='{"signal": "bullish"}')
        agent._call_anthropic = mock
        await agent._call_llm("prompt")
        mock.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_routes_to_openai(self):
        agent = self._make_agent("openai")
        mock = AsyncMock(return_value='{"signal": "bearish"}')
        agent._call_openai = mock
        await agent._call_llm("prompt")
        mock.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_routes_to_google(self):
        agent = self._make_agent("google")
        mock = AsyncMock(return_value='{"signal": "neutral"}')
        agent._call_google = mock
        await agent._call_llm("prompt")
        mock.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_routes_to_ollama(self):
        agent = self._make_agent("ollama")
        mock = AsyncMock(return_value='{"signal": "bullish"}')
        agent._call_ollama = mock
        await agent._call_llm("prompt")
        mock.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_unknown_provider_raises_value_error(self):
        agent = self._make_agent("unknown_provider")
        with pytest.raises(ValueError, match="Unknown LLM provider"):
            await agent._call_llm("prompt")

    @pytest.mark.asyncio
    async def test_provider_name_is_case_insensitive(self):
        """'ANTHROPIC' should route the same as 'anthropic'."""
        agent = self._make_agent("ANTHROPIC")
        mock = AsyncMock(return_value='{"signal": "bullish"}')
        agent._call_anthropic = mock
        await agent._call_llm("prompt")
        mock.assert_awaited_once()


# ---------------------------------------------------------------------------
# _call_llm — JSON parsing and error propagation
# ---------------------------------------------------------------------------


class TestCallLlmJsonParsing:
    def setup_method(self):
        self.agent = _DummyAgent(settings=_make_settings(llm_provider="anthropic"))

    @pytest.mark.asyncio
    async def test_returns_parsed_dict_on_valid_json(self):
        self.agent._call_anthropic = AsyncMock(
            return_value='{"signal": "bullish", "confidence": 0.8}'
        )
        result = await self.agent._call_llm("prompt")
        assert result == {"signal": "bullish", "confidence": 0.8}

    @pytest.mark.asyncio
    async def test_raises_value_error_on_non_json_response(self):
        self.agent._call_anthropic = AsyncMock(
            return_value="Sorry, I cannot provide a JSON response right now."
        )
        with pytest.raises(ValueError, match="not valid JSON"):
            await self.agent._call_llm("prompt")

    @pytest.mark.asyncio
    async def test_raises_value_error_on_json_array_response(self):
        self.agent._call_anthropic = AsyncMock(return_value='[{"signal": "bullish"}]')
        with pytest.raises(ValueError, match="expected a JSON object"):
            await self.agent._call_llm("prompt")

    @pytest.mark.asyncio
    async def test_strips_markdown_fence_from_provider_response(self):
        self.agent._call_anthropic = AsyncMock(
            return_value='```json\n{"signal": "neutral"}\n```'
        )
        result = await self.agent._call_llm("prompt")
        assert result["signal"] == "neutral"

    @pytest.mark.asyncio
    async def test_prompt_is_forwarded_to_provider(self):
        """The exact prompt string must reach the provider method unchanged."""
        received_prompt = {}

        async def capture(prompt, model):
            received_prompt["value"] = prompt
            return '{"ok": true}'

        self.agent._call_anthropic = capture
        await self.agent._call_llm("my exact prompt text")
        assert received_prompt["value"] == "my exact prompt text"
