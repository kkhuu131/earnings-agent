"""FundamentalsAnalyst agent.

Reads an earnings call transcript and returns a structured signal based on
fundamental financial indicators: revenue growth, EPS vs estimates, gross
margin, guidance, and capital expenditure.

Output contract:
    {
        "signal": "bullish" | "bearish" | "neutral",
        "key_points": ["<string>", ...],   # 1–5 concise observations
        "confidence": 0.0–1.0
    }

Usage:
    from backend.agents.fundamentals_analyst import FundamentalsAnalyst

    agent = FundamentalsAnalyst()
    result = await agent.analyze({"transcript": transcript_text})
    # result == {"signal": "bullish", "key_points": [...], "confidence": 0.82}
"""

from backend.agents.base_agent import BaseAgent
from backend.config import Settings

_PROMPT_TEMPLATE = """\
You are a senior equity analyst specialising in fundamental analysis of \
earnings calls.

Your task is to read the transcript below and produce a JSON signal \
assessing the fundamental health of the business as revealed by this \
earnings call.

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
- Revenue growth (quarter-over-quarter and year-over-year)
- EPS relative to analyst consensus estimates (beat / miss / in-line)
- Gross margin and operating margin trends
- Management guidance for the next quarter or full fiscal year
- Capital expenditure levels and investment trajectory

TRANSCRIPT:
{transcript}
"""


class FundamentalsAnalyst(BaseAgent):
    """Analyst agent that extracts fundamental financial signals from transcripts.

    Inherits from :class:`~backend.agents.base_agent.BaseAgent` and uses the
    quick model by default (fundamentals extraction is a structured extraction
    task, not a reasoning-heavy one).

    Args:
        settings: Optional Settings override for testing.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        super().__init__(settings)

    async def analyze(self, context: dict) -> dict:
        """Analyze a transcript for fundamental financial signals.

        Args:
            context: Must contain a ``"transcript"`` key with the full
                transcript text as a string.

        Returns:
            A dict with keys: ``signal`` (str), ``key_points`` (list[str]),
            ``confidence`` (float).

        Raises:
            KeyError: If ``context`` does not contain ``"transcript"``.
            ValueError: If the LLM returns a non-JSON response.
        """
        transcript: str = context["transcript"]
        prompt = _PROMPT_TEMPLATE.format(transcript=transcript)
        return await self._call_llm(prompt, use_deep_model=False)
