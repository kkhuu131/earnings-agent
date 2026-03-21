"""BullResearcher agent.

Receives the three analyst reports (fundamentals, sentiment, technical) and
synthesises the bullish investment case.  Supports a rebuttal round where the
prior bear argument is supplied as additional context, enabling a configurable
multi-round debate loop with BearResearcher.

Output contract (both analyze and analyze_rebuttal):
    {
        "argument":  "<string>",   # full bullish thesis or updated rebuttal
        "confidence": 0.0–1.0,
        "rebuttals": ["<string>", ...]  # specific counters to bear points
    }

Usage:
    from backend.agents.bull_researcher import BullResearcher

    agent = BullResearcher()
    result = await agent.analyze({
        "fundamentals": {"signal": "bullish", "key_points": [...], "confidence": 0.8},
        "sentiment":    {"signal": "neutral",  "key_points": [...], "confidence": 0.6},
        "technical":    {"signal": "bullish",  "key_points": [...], "confidence": 0.7},
    })
    # result == {"argument": "...", "confidence": 0.82, "rebuttals": [...]}

    # Rebuttal round — pass the bear's prior argument back:
    rebuttal = await agent.analyze_rebuttal({
        "fundamentals":    {...},
        "sentiment":       {...},
        "technical":       {...},
        "opposing_argument": "Bear case: margins will compress due to ...",
    })
"""

from backend.agents.base_agent import BaseAgent
from backend.config import Settings

_ANALYZE_PROMPT = """\
You are an experienced equity researcher building the BULLISH case for a stock \
ahead of an earnings reaction.

You have received signal reports from three specialist analysts.  Your job is to \
synthesise a compelling bullish thesis and pre-empt the most likely bearish \
counter-arguments.

Return ONLY a raw JSON object — no markdown, no prose, no code fences — \
with this exact structure:

{{
  "argument": "<full bullish thesis as a single string>",
  "confidence": <float 0.0–1.0>,
  "rebuttals": ["<rebuttal to anticipated bear point 1>", "<rebuttal 2>"]
}}

Rules:
- "argument" must be a non-empty string summarising the bull case
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
You are an experienced equity researcher building the BULLISH case for a stock \
ahead of an earnings reaction.

You have received signal reports from three specialist analysts AND a bearish \
counter-argument from your debate opponent.  Your job is to defend and strengthen \
the bullish thesis by directly rebutting the bear's specific claims.

Return ONLY a raw JSON object — no markdown, no prose, no code fences — \
with this exact structure:

{{
  "argument": "<updated bullish thesis that addresses the bear's argument>",
  "confidence": <float 0.0–1.0>,
  "rebuttals": ["<direct rebuttal to bear point 1>", "<direct rebuttal 2>"]
}}

Rules:
- "argument" must be a non-empty string
- "confidence" must be a float between 0.0 and 1.0 inclusive
- "rebuttals" must be a non-empty list of strings that directly address the bear's claims
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

BEAR ARGUMENT TO REBUT:
{opposing_argument}
"""


def _format_points(key_points: list) -> str:
    return "\n".join(f"- {p}" for p in key_points)


class BullResearcher(BaseAgent):
    """Researcher agent that synthesises the bullish investment case.

    Inherits from :class:`~backend.agents.base_agent.BaseAgent` and always
    uses the deep model (debate and thesis construction are reasoning-heavy).

    Args:
        settings: Optional Settings override for testing.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        super().__init__(settings)

    async def analyze(self, context: dict) -> dict:
        """Build the initial bullish thesis from all three analyst reports.

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
        """Produce a rebuttal response after receiving the bear's argument.

        Args:
            context: Must contain ``"fundamentals"``, ``"sentiment"``,
                ``"technical"`` (same shape as :meth:`analyze`), plus
                ``"opposing_argument"`` — the bear researcher's prior output
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
