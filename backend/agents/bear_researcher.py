"""BearResearcher agent.

Receives the three analyst reports (fundamentals, sentiment, technical) and
synthesises the bearish investment case.  Supports a rebuttal round where the
prior bull argument is supplied as additional context, enabling a configurable
multi-round debate loop with BullResearcher.

Output contract (both analyze and analyze_rebuttal):
    {
        "argument":  "<string>",   # full bearish thesis or updated rebuttal
        "confidence": 0.0–1.0,
        "rebuttals": ["<string>", ...]  # specific counters to bull points
    }

Usage:
    from backend.agents.bear_researcher import BearResearcher

    agent = BearResearcher()
    result = await agent.analyze({
        "fundamentals": {"signal": "bullish", "key_points": [...], "confidence": 0.8},
        "sentiment":    {"signal": "neutral",  "key_points": [...], "confidence": 0.6},
        "technical":    {"signal": "bullish",  "key_points": [...], "confidence": 0.7},
    })
    # result == {"argument": "...", "confidence": 0.71, "rebuttals": [...]}

    # Rebuttal round — pass the bull's prior argument back:
    rebuttal = await agent.analyze_rebuttal({
        "fundamentals":    {...},
        "sentiment":       {...},
        "technical":       {...},
        "opposing_argument": "Bull case: strong revenue growth driven by ...",
    })
"""

from backend.agents.base_agent import BaseAgent
from backend.config import Settings

_ANALYZE_PROMPT = """\
You are an experienced equity researcher building the BEARISH case for a stock \
ahead of an earnings reaction.

You have received signal reports from three specialist analysts.  Your job is to \
synthesise a compelling bearish thesis and pre-empt the most likely bullish \
counter-arguments.

Return ONLY a raw JSON object — no markdown, no prose, no code fences — \
with this exact structure:

{{
  "argument": "<full bearish thesis as a single string>",
  "confidence": <float 0.0–1.0>,
  "rebuttals": ["<rebuttal to anticipated bull point 1>", "<rebuttal 2>"]
}}

Rules:
- "argument" must be a non-empty string summarising the bear case
- "confidence" must be a float between 0.0 and 1.0 inclusive
- "rebuttals" must be a list of strings (may be empty if there is nothing to rebut)
- Do NOT include any text outside the JSON object

ANALYST REPORTS:

Fundamentals signal: {fundamentals_signal}
Fundamentals key points:
{fundamentals_points}

Sentiment signal: {sentiment_signal}
Sentiment key points:
{sentiment_points}

Technical signal: {technical_signal}
Technical key points:
{technical_points}
"""

_REBUTTAL_PROMPT = """\
You are an experienced equity researcher building the BEARISH case for a stock \
ahead of an earnings reaction.

You have received signal reports from three specialist analysts AND a bullish \
counter-argument from your debate opponent.  Your job is to defend and strengthen \
the bearish thesis by directly rebutting the bull's specific claims.

Return ONLY a raw JSON object — no markdown, no prose, no code fences — \
with this exact structure:

{{
  "argument": "<updated bearish thesis that addresses the bull's argument>",
  "confidence": <float 0.0–1.0>,
  "rebuttals": ["<direct rebuttal to bull point 1>", "<direct rebuttal 2>"]
}}

Rules:
- "argument" must be a non-empty string
- "confidence" must be a float between 0.0 and 1.0 inclusive
- "rebuttals" must be a non-empty list of strings that directly address the bull's claims
- Do NOT include any text outside the JSON object

ANALYST REPORTS:

Fundamentals signal: {fundamentals_signal}
Fundamentals key points:
{fundamentals_points}

Sentiment signal: {sentiment_signal}
Sentiment key points:
{sentiment_points}

Technical signal: {technical_signal}
Technical key points:
{technical_points}

BULL ARGUMENT TO REBUT:
{opposing_argument}
"""


def _format_points(key_points: list) -> str:
    return "\n".join(f"- {p}" for p in key_points)


class BearResearcher(BaseAgent):
    """Researcher agent that synthesises the bearish investment case.

    Inherits from :class:`~backend.agents.base_agent.BaseAgent` and always
    uses the deep model (debate and thesis construction are reasoning-heavy).

    Args:
        settings: Optional Settings override for testing.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        super().__init__(settings)

    async def analyze(self, context: dict) -> dict:
        """Build the initial bearish thesis from all three analyst reports.

        Args:
            context: Must contain keys ``"fundamentals"``, ``"sentiment"``,
                and ``"technical"``, each a signal dict with ``"signal"``,
                ``"key_points"``, and ``"confidence"``.

        Returns:
            A dict with keys: ``argument`` (str), ``confidence`` (float),
            ``rebuttals`` (list[str]).

        Raises:
            KeyError: If any of the three required analyst report keys are missing.
            ValueError: If the LLM returns a non-JSON response.
        """
        fundamentals = context["fundamentals"]
        sentiment = context["sentiment"]
        technical = context["technical"]

        prompt = _ANALYZE_PROMPT.format(
            fundamentals_signal=fundamentals["signal"],
            fundamentals_points=_format_points(fundamentals["key_points"]),
            sentiment_signal=sentiment["signal"],
            sentiment_points=_format_points(sentiment["key_points"]),
            technical_signal=technical["signal"],
            technical_points=_format_points(technical["key_points"]),
        )
        return await self._call_llm(prompt, use_deep_model=True)

    async def analyze_rebuttal(self, context: dict) -> dict:
        """Produce a rebuttal response after receiving the bull's argument.

        Args:
            context: Must contain ``"fundamentals"``, ``"sentiment"``,
                ``"technical"`` (same shape as :meth:`analyze`), plus
                ``"opposing_argument"`` — the bull researcher's prior output
                as a string.

        Returns:
            A dict with keys: ``argument`` (str), ``confidence`` (float),
            ``rebuttals`` (list[str]).

        Raises:
            KeyError: If any required key is missing from context.
            ValueError: If the LLM returns a non-JSON response.
        """
        fundamentals = context["fundamentals"]
        sentiment = context["sentiment"]
        technical = context["technical"]
        opposing_argument: str = context["opposing_argument"]

        prompt = _REBUTTAL_PROMPT.format(
            fundamentals_signal=fundamentals["signal"],
            fundamentals_points=_format_points(fundamentals["key_points"]),
            sentiment_signal=sentiment["signal"],
            sentiment_points=_format_points(sentiment["key_points"]),
            technical_signal=technical["signal"],
            technical_points=_format_points(technical["key_points"]),
            opposing_argument=opposing_argument,
        )
        return await self._call_llm(prompt, use_deep_model=True)
