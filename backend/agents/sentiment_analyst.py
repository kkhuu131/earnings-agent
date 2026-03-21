"""SentimentAnalyst agent.

Reads an earnings call transcript and returns a structured signal based on
qualitative sentiment indicators: management tone, language hedging, certainty
of language, and Q&A defensiveness.

Output contract:
    {
        "signal": "bullish" | "bearish" | "neutral",
        "key_points": ["<string>", ...],   # 1–5 concise observations
        "confidence": 0.0–1.0
    }

Usage:
    from backend.agents.sentiment_analyst import SentimentAnalyst

    agent = SentimentAnalyst()
    result = await agent.analyze({"transcript": transcript_text})
    # result == {"signal": "bullish", "key_points": [...], "confidence": 0.75}
"""

from backend.agents.base_agent import BaseAgent
from backend.config import Settings

_PROMPT_TEMPLATE = """\
You are a senior equity analyst specialising in qualitative sentiment analysis \
of earnings calls.

Your task is to read the transcript below and produce a JSON signal assessing \
the sentiment and tone of management as revealed by this earnings call.

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
- Management tone: optimism, enthusiasm, or caution in prepared remarks
- Language hedging: frequency of qualifiers like "potentially", "may", "subject to"
- Certainty of language: how definitively management speaks about targets and outcomes
- Q&A defensiveness: evasiveness, deflection, or short answers to analyst questions
- Contrast between prepared remarks and Q&A responses

TRANSCRIPT:
{transcript}
"""


class SentimentAnalyst(BaseAgent):
    """Analyst agent that extracts sentiment signals from earnings call transcripts.

    Inherits from :class:`~backend.agents.base_agent.BaseAgent` and uses the
    quick model by default (sentiment extraction is a structured extraction
    task, not a reasoning-heavy one).

    Args:
        settings: Optional Settings override for testing.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        super().__init__(settings)

    async def analyze(self, context: dict) -> dict:
        """Analyze a transcript for management sentiment signals.

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
