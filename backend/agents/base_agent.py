"""Abstract base class for all analyst and researcher agents.

All agents inherit from BaseAgent and call `_call_llm()` for every LLM
interaction.  The method routes to the configured provider, parses the
response as JSON, and raises ValueError on any non-JSON output — enforcing
the structured-output contract defined in CLAUDE.md.

Usage:
    class MyAgent(BaseAgent):
        async def analyze(self, context: dict) -> dict:
            prompt = build_prompt(context)
            return await self._call_llm(prompt, use_deep_model=True)
"""

import json
import logging
import re
from abc import ABC, abstractmethod
from typing import Any

from backend.config import Settings, settings as _default_settings

logger = logging.getLogger(__name__)


class BaseAgent(ABC):
    """Abstract base for all agents in the earnings-agent pipeline.

    Subclasses must implement :meth:`analyze`.  All LLM calls go through
    :meth:`_call_llm`, which guarantees a parsed ``dict`` return or raises
    ``ValueError`` on non-JSON output.

    Args:
        settings: Application settings.  Defaults to the module-level singleton
            so production code never needs to pass this explicitly.  Tests pass
            a custom instance to avoid touching real environment variables.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or _default_settings

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    @abstractmethod
    async def analyze(self, context: dict) -> dict:
        """Run the agent's analysis and return a structured JSON result.

        Args:
            context: Input data for the agent.  The required keys vary by
                subclass — see each agent's docstring.

        Returns:
            A dict matching the agent's output schema.
        """
        raise NotImplementedError

    # ------------------------------------------------------------------
    # LLM dispatch
    # ------------------------------------------------------------------

    async def _call_llm(self, prompt: str, use_deep_model: bool = False) -> dict:
        """Call the configured LLM and return parsed JSON.

        Args:
            prompt: The full prompt to send to the model.
            use_deep_model: When True, use ``settings.deep_model`` (for
                reasoning-heavy tasks like debate and final decision).
                When False, use ``settings.quick_model`` (cheaper, faster).

        Returns:
            Parsed JSON response as a dict.

        Raises:
            ValueError: If the LLM response cannot be parsed as a JSON object.
            ValueError: If the configured provider is not recognised.
        """
        model = self._settings.deep_model if use_deep_model else self._settings.quick_model
        provider = self._settings.llm_provider.lower()

        logger.debug("Calling %s model=%s deep=%s", provider, model, use_deep_model)

        if provider == "anthropic":
            raw = await self._call_anthropic(prompt, model)
        elif provider == "openai":
            raw = await self._call_openai(prompt, model)
        elif provider == "google":
            raw = await self._call_google(prompt, model)
        elif provider == "ollama":
            raw = await self._call_ollama(prompt, model)
        else:
            raise ValueError(f"Unknown LLM provider: {provider!r}. Choose from: anthropic, openai, google, ollama")

        return self._parse_json(raw)

    # ------------------------------------------------------------------
    # JSON parsing
    # ------------------------------------------------------------------

    def _parse_json(self, text: str) -> dict:
        """Strip optional markdown fences and parse JSON.

        Args:
            text: Raw text returned by the LLM.

        Returns:
            Parsed dict.

        Raises:
            ValueError: If the text is not valid JSON or does not decode to a dict.
        """
        # Strip leading/trailing whitespace then remove markdown code fences
        # e.g. ```json\n{...}\n``` or ```\n{...}\n```
        cleaned = text.strip()
        cleaned = re.sub(r"^```(?:json)?\s*\n?", "", cleaned)
        cleaned = re.sub(r"\n?```\s*$", "", cleaned)
        cleaned = cleaned.strip()

        try:
            result: Any = json.loads(cleaned)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"LLM response is not valid JSON: {exc}\n"
                f"Raw response: {text!r}"
            ) from exc

        if not isinstance(result, dict):
            raise ValueError(
                f"LLM response parsed as {type(result).__name__}, expected a JSON object (dict). "
                f"Raw response: {text!r}"
            )

        return result

    # ------------------------------------------------------------------
    # Provider-specific call methods
    # ------------------------------------------------------------------

    async def _call_anthropic(self, prompt: str, model: str) -> str:
        """Call the Anthropic Messages API and return the text response."""
        import anthropic

        client = anthropic.AsyncAnthropic(api_key=self._settings.anthropic_api_key)
        message = await client.messages.create(
            model=model,
            max_tokens=1024,
            temperature=self._settings.temperature,
            messages=[{"role": "user", "content": prompt}],
        )
        return message.content[0].text

    async def _call_openai(self, prompt: str, model: str) -> str:
        """Call the OpenAI Chat Completions API and return the text response."""
        from openai import AsyncOpenAI

        client = AsyncOpenAI(api_key=self._settings.openai_api_key)
        response = await client.chat.completions.create(
            model=model,
            temperature=self._settings.temperature,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.choices[0].message.content

    async def _call_google(self, prompt: str, model: str) -> str:
        """Call the Google Gemini API and return the text response."""
        import google.generativeai as genai

        genai.configure(api_key=self._settings.google_api_key)
        gemini_model = genai.GenerativeModel(model)
        response = await gemini_model.generate_content_async(prompt)
        return response.text

    async def _call_ollama(self, prompt: str, model: str) -> str:
        """Call a locally running Ollama instance and return the text response."""
        import httpx

        async with httpx.AsyncClient() as client:
            response = await client.post(
                "http://localhost:11434/api/generate",
                json={"model": model, "prompt": prompt, "stream": False},
                timeout=120.0,
            )
            response.raise_for_status()
            return response.json()["response"]
