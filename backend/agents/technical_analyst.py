"""TechnicalAnalyst agent.

Reads pre-earnings price action data and returns a structured signal based on
technical indicators: 5-day and 30-day returns, RSI, volume trend, and implied
move vs historical move.

Output contract:
    {
        "signal": "bullish" | "bearish" | "neutral",
        "key_points": ["<string>", ...],   # 1–5 concise observations
        "confidence": 0.0–1.0
    }

Usage:
    from backend.agents.technical_analyst import TechnicalAnalyst

    agent = TechnicalAnalyst()
    result = await agent.analyze({"price_data": price_data_dict})
    # result == {"signal": "bearish", "key_points": [...], "confidence": 0.68}
"""

from backend.agents.base_agent import BaseAgent
from backend.config import Settings

_PROMPT_TEMPLATE = """\
You are a senior equity analyst specialising in technical analysis of \
pre-earnings price action.

Your task is to read the price data below and produce a JSON signal assessing \
the technical setup heading into earnings.

Return ONLY a raw JSON object — no markdown, no prose, no code fences — \
with this exact structure:

{{
  "signal": "<bullish|bearish|neutral>",
  "key_points": ["<point 1>", "<point 2>"],
  "confidence": <float 0.0–1.0>
}}

Rules:
- "signal" must be exactly one of: "bullish", "bearish", "neutral"
- "key_points" must be a non-empty list of up to 5 concise strings
- "confidence" must be a float between 0.0 and 1.0 inclusive
- Do NOT include any text outside the JSON object

Focus your analysis on:
- 5-day return: short-term momentum heading into earnings
- 30-day return: medium-term trend and whether the stock has run up or sold off
- RSI: overbought (>70) or oversold (<30) conditions before the print
- Volume trend: whether volume is rising (accumulation) or falling (distribution)
- Implied move vs historical move: whether options are pricing a larger or smaller \
move than the stock typically delivers on earnings day

PRICE DATA:
{price_data}
"""


class TechnicalAnalyst(BaseAgent):
    """Analyst agent that extracts technical signals from pre-earnings price data.

    Inherits from :class:`~backend.agents.base_agent.BaseAgent` and uses the
    quick model by default (technical extraction is a structured extraction
    task, not a reasoning-heavy one).

    Args:
        settings: Optional Settings override for testing.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        super().__init__(settings)

    async def analyze(self, context: dict) -> dict:
        """Analyze pre-earnings price data for technical signals.

        Args:
            context: Must contain a ``"price_data"`` key with a dict of price
                metrics (e.g. 5d_return, 30d_return, rsi, volume_trend,
                implied_move, historical_move).  The dict is formatted as text
                and injected into the prompt.

        Returns:
            A dict with keys: ``signal`` (str), ``key_points`` (list[str]),
            ``confidence`` (float).

        Raises:
            KeyError: If ``context`` does not contain ``"price_data"``.
            ValueError: If the LLM returns a non-JSON response.
        """
        price_data: dict = context["price_data"]
        price_data_text = "\n".join(f"{k}: {v}" for k, v in price_data.items())
        prompt = _PROMPT_TEMPLATE.format(price_data=price_data_text)
        return await self._call_llm(prompt, use_deep_model=False)
