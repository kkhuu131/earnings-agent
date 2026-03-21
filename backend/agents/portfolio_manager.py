"""PortfolioManager agent.

Receives the three analyst reports (fundamentals, sentiment, technical) plus the
full debate transcript (a list of round dicts, each with ``"bull"`` and ``"bear"``
keys containing the researcher output for that round).

Applies equal weighting (0.2 per agent) across all five signal sources
initially — reputation weighting is added in Step 10.

Output contract:
    {
        "direction":  "up" | "down" | "neutral",
        "confidence": 0.0–1.0,
        "reasoning":  "<string>",
        "weighted_signals": {
            "fundamentals": { "signal": "bullish|bearish|neutral", "weight": 0.2 },
            "sentiment":    { "signal": "bullish|bearish|neutral", "weight": 0.2 },
            "technical":    { "signal": "bullish|bearish|neutral", "weight": 0.2 },
            "bull":         { "signal": "bullish",                 "weight": 0.2 },
            "bear":         { "signal": "bearish",                 "weight": 0.2 }
        }
    }

Usage:
    from backend.agents.portfolio_manager import PortfolioManager

    agent = PortfolioManager()
    result = await agent.analyze({
        "fundamentals": {"signal": "bullish", "key_points": [...], "confidence": 0.8},
        "sentiment":    {"signal": "neutral",  "key_points": [...], "confidence": 0.6},
        "technical":    {"signal": "bullish",  "key_points": [...], "confidence": 0.7},
        "debate": [
            {
                "bull": {"argument": "...", "confidence": 0.8, "rebuttals": [...]},
                "bear": {"argument": "...", "confidence": 0.6, "rebuttals": [...]},
            },
        ],
    })
    # result == {
    #     "direction": "up",
    #     "confidence": 0.74,
    #     "reasoning": "...",
    #     "weighted_signals": { ... }
    # }
"""

from backend.agents.base_agent import BaseAgent
from backend.config import Settings

_ANALYZE_PROMPT = """\
You are an experienced portfolio manager making a final directional prediction \
on a stock's price movement in the 30 days following its earnings release.

You have received signal reports from three specialist analysts and a full \
debate transcript between a bull researcher and a bear researcher.  Your job \
is to weigh all five perspectives equally and make a single final call.

Return ONLY a raw JSON object — no markdown, no prose, no code fences — \
with this exact structure:

{{
  "direction": "<up|down|neutral>",
  "confidence": <float 0.0–1.0>,
  "reasoning": "<concise explanation of your final call>",
  "weighted_signals": {{
    "fundamentals": {{ "signal": "<bullish|bearish|neutral>", "weight": 0.2 }},
    "sentiment":    {{ "signal": "<bullish|bearish|neutral>", "weight": 0.2 }},
    "technical":    {{ "signal": "<bullish|bearish|neutral>", "weight": 0.2 }},
    "bull":         {{ "signal": "bullish",                   "weight": 0.2 }},
    "bear":         {{ "signal": "bearish",                   "weight": 0.2 }}
  }}
}}

Rules:
- "direction" must be exactly one of: "up", "down", "neutral"
- "confidence" must be a float between 0.0 and 1.0 inclusive
- "reasoning" must be a non-empty string
- All five agents in "weighted_signals" must be present with weight 0.2 (equal weighting)
- "fundamentals", "sentiment", and "technical" signals must match the analyst reports below
- "bull" signal is always "bullish"; "bear" signal is always "bearish"
- Do NOT include any text outside the JSON object

ANALYST REPORTS:

Fundamentals signal: {fundamentals_signal}
Fundamentals confidence: {fundamentals_confidence}
Fundamentals key points:
{fundamentals_points}

Sentiment signal: {sentiment_signal}
Sentiment confidence: {sentiment_confidence}
Sentiment key points:
{sentiment_points}

Technical signal: {technical_signal}
Technical confidence: {technical_confidence}
Technical key points:
{technical_points}

DEBATE TRANSCRIPT:
{debate_text}
"""


def _format_points(key_points: list) -> str:
    return "\n".join(f"- {p}" for p in key_points)


def _format_debate(debate: list) -> str:
    if not debate:
        return "(no debate rounds)"
    lines = []
    for i, round_dict in enumerate(debate, start=1):
        lines.append(f"Round {i}:")
        bull = round_dict["bull"]
        bear = round_dict["bear"]
        lines.append(f"  Bull argument: {bull['argument']}")
        if bull.get("rebuttals"):
            for r in bull["rebuttals"]:
                lines.append(f"    Bull rebuttal: {r}")
        lines.append(f"  Bear argument: {bear['argument']}")
        if bear.get("rebuttals"):
            for r in bear["rebuttals"]:
                lines.append(f"    Bear rebuttal: {r}")
    return "\n".join(lines)


class PortfolioManager(BaseAgent):
    """Agent that synthesises all analyst and researcher outputs into a final prediction.

    Applies equal weights (0.2) to all five signal sources.  Reputation-based
    weighting is deferred to Step 10.

    Always uses the deep model — the final investment decision is the most
    reasoning-heavy task in the pipeline.

    Args:
        settings: Optional Settings override for testing.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        super().__init__(settings)

    async def analyze(self, context: dict) -> dict:
        """Synthesise all signals and return a final directional prediction.

        Args:
            context: Must contain keys:
                - ``"fundamentals"``: analyst report dict (``signal``, ``key_points``,
                  ``confidence``)
                - ``"sentiment"``:    analyst report dict (same shape)
                - ``"technical"``:    analyst report dict (same shape)
                - ``"debate"``:       list of round dicts, each with ``"bull"`` and
                  ``"bear"`` keys whose values are researcher output dicts
                  (``argument``, ``confidence``, ``rebuttals``).

        Returns:
            A dict with keys: ``direction`` (str), ``confidence`` (float),
            ``reasoning`` (str), ``weighted_signals`` (dict).

        Raises:
            KeyError: If any of the four required context keys are missing, or if
                a debate round dict is missing ``"bull"`` or ``"bear"``.
            ValueError: If the LLM returns a non-JSON response.
        """
        fundamentals = context["fundamentals"]
        sentiment = context["sentiment"]
        technical = context["technical"]
        debate: list = context["debate"]

        # Validate debate structure eagerly so KeyError surfaces before the LLM call
        for round_dict in debate:
            _ = round_dict["bull"]
            _ = round_dict["bear"]

        prompt = _ANALYZE_PROMPT.format(
            fundamentals_signal=fundamentals["signal"],
            fundamentals_confidence=fundamentals["confidence"],
            fundamentals_points=_format_points(fundamentals["key_points"]),
            sentiment_signal=sentiment["signal"],
            sentiment_confidence=sentiment["confidence"],
            sentiment_points=_format_points(sentiment["key_points"]),
            technical_signal=technical["signal"],
            technical_confidence=technical["confidence"],
            technical_points=_format_points(technical["key_points"]),
            debate_text=_format_debate(debate),
        )
        return await self._call_llm(prompt, use_deep_model=True)
