"""LangGraph StateGraph wiring all six agents into the earnings analysis pipeline.

Graph structure
---------------
1. Analyst team (fan-out, parallel):
   - FundamentalsAnalyst — reads transcript
   - SentimentAnalyst    — reads transcript
   - TechnicalAnalyst    — reads price_data

2. Debate loop (sequential, settings.max_debate_rounds rounds):
   - BullResearcher.analyze()          (round 0 initial pass)
   - BearResearcher.analyze()          (round 0 initial pass)
   - BullResearcher.analyze_rebuttal() (rounds 1+ rebuttals)
   - BearResearcher.analyze_rebuttal() (rounds 1+ rebuttals)
   Each round appends {"bull": ..., "bear": ...} to state["debate"].

3. PortfolioManager — reads all accumulated state, writes state["prediction"].

Entry point
-----------
    result = await run_pipeline(transcript, price_data)
    # result == {"direction": "up|down|neutral", "confidence": ..., ...}
"""

import asyncio
import logging
from typing import Any, TypedDict

from langgraph.graph import END, StateGraph

from backend.agents.bear_researcher import BearResearcher
from backend.agents.bull_researcher import BullResearcher
from backend.agents.fundamentals_analyst import FundamentalsAnalyst
from backend.agents.portfolio_manager import PortfolioManager
from backend.agents.sentiment_analyst import SentimentAnalyst
from backend.agents.technical_analyst import TechnicalAnalyst
from backend.config import Settings, settings as _default_settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# State definition
# ---------------------------------------------------------------------------


class PipelineState(TypedDict):
    transcript: str
    price_data: dict
    fundamentals: dict
    sentiment: dict
    technical: dict
    debate: list  # list of {"bull": ..., "bear": ...} dicts
    prediction: dict | None


# ---------------------------------------------------------------------------
# Graph builder
# ---------------------------------------------------------------------------


def build_graph(settings: Settings | None = None) -> Any:
    """Compile and return the LangGraph StateGraph.

    Args:
        settings: Optional Settings override.  Defaults to the module-level
            singleton so production code never needs to pass this explicitly.

    Returns:
        A compiled LangGraph runnable that accepts a ``PipelineState`` dict
        and returns an updated ``PipelineState`` dict.
    """
    cfg = settings or _default_settings

    # Instantiate agents (injecting settings so tests can override)
    fundamentals_agent = FundamentalsAnalyst(settings=cfg)
    sentiment_agent = SentimentAnalyst(settings=cfg)
    technical_agent = TechnicalAnalyst(settings=cfg)
    bull_agent = BullResearcher(settings=cfg)
    bear_agent = BearResearcher(settings=cfg)
    pm_agent = PortfolioManager(settings=cfg)

    # -----------------------------------------------------------------------
    # Node definitions
    # -----------------------------------------------------------------------

    async def run_fundamentals(state: PipelineState) -> dict:
        logger.debug("Node: fundamentals_analyst")
        result = await fundamentals_agent.analyze({"transcript": state["transcript"]})
        return {"fundamentals": result}

    async def run_sentiment(state: PipelineState) -> dict:
        logger.debug("Node: sentiment_analyst")
        result = await sentiment_agent.analyze({"transcript": state["transcript"]})
        return {"sentiment": result}

    async def run_technical(state: PipelineState) -> dict:
        logger.debug("Node: technical_analyst")
        result = await technical_agent.analyze({"price_data": state["price_data"]})
        return {"technical": result}

    async def run_analysts_parallel(state: PipelineState) -> dict:
        """Fan-out: run all three analyst nodes concurrently."""
        logger.debug("Node: analysts_parallel")
        fundamentals_result, sentiment_result, technical_result = await asyncio.gather(
            fundamentals_agent.analyze({"transcript": state["transcript"]}),
            sentiment_agent.analyze({"transcript": state["transcript"]}),
            technical_agent.analyze({"price_data": state["price_data"]}),
        )
        return {
            "fundamentals": fundamentals_result,
            "sentiment": sentiment_result,
            "technical": technical_result,
        }

    async def run_debate(state: PipelineState) -> dict:
        """Sequential debate loop for settings.max_debate_rounds rounds.

        Round 0: both researchers call .analyze() with the analyst reports.
        Rounds 1+: both researchers call .analyze_rebuttal() with the
        opponent's previous argument.
        """
        logger.debug("Node: debate (max_rounds=%d)", cfg.max_debate_rounds)
        analyst_context = {
            "fundamentals": state["fundamentals"],
            "sentiment": state["sentiment"],
            "technical": state["technical"],
        }
        rounds: list = []

        if cfg.max_debate_rounds == 0:
            return {"debate": rounds}

        # Round 0 — initial positions
        bull_result = await bull_agent.analyze(analyst_context)
        bear_result = await bear_agent.analyze(analyst_context)
        rounds.append({"bull": bull_result, "bear": bear_result})

        # Rounds 1+ — rebuttals
        for _ in range(1, cfg.max_debate_rounds):
            bull_rebuttal_ctx = {
                **analyst_context,
                "opposing_argument": bear_result["argument"],
            }
            bear_rebuttal_ctx = {
                **analyst_context,
                "opposing_argument": bull_result["argument"],
            }
            bull_result = await bull_agent.analyze_rebuttal(bull_rebuttal_ctx)
            bear_result = await bear_agent.analyze_rebuttal(bear_rebuttal_ctx)
            rounds.append({"bull": bull_result, "bear": bear_result})

        return {"debate": rounds}

    async def run_portfolio_manager(state: PipelineState) -> dict:
        logger.debug("Node: portfolio_manager")
        result = await pm_agent.analyze(
            {
                "fundamentals": state["fundamentals"],
                "sentiment": state["sentiment"],
                "technical": state["technical"],
                "debate": state["debate"],
            }
        )
        return {"prediction": result}

    # -----------------------------------------------------------------------
    # Graph wiring
    # -----------------------------------------------------------------------

    graph = StateGraph(PipelineState)

    graph.add_node("analysts", run_analysts_parallel)
    graph.add_node("debate", run_debate)
    graph.add_node("portfolio_manager", run_portfolio_manager)

    graph.set_entry_point("analysts")
    graph.add_edge("analysts", "debate")
    graph.add_edge("debate", "portfolio_manager")
    graph.add_edge("portfolio_manager", END)

    return graph.compile()


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


async def run_pipeline(
    transcript: str,
    price_data: dict,
    settings: Settings | None = None,
) -> dict:
    """Run the full earnings analysis pipeline and return the final prediction.

    Args:
        transcript: Full text of the earnings call transcript.
        price_data: Price dict as returned by the data layer (prices.py).
            Must contain at minimum the keys the TechnicalAnalyst expects.
        settings: Optional Settings override.  Useful for tests.

    Returns:
        The PortfolioManager's prediction dict:
        ``{"direction": "up|down|neutral", "confidence": float,
           "reasoning": str, "weighted_signals": dict}``
    """
    compiled = build_graph(settings)
    initial_state: PipelineState = {
        "transcript": transcript,
        "price_data": price_data,
        "fundamentals": {},
        "sentiment": {},
        "technical": {},
        "debate": [],
        "prediction": None,
    }
    final_state = await compiled.ainvoke(initial_state)
    prediction = final_state["prediction"]
    prediction["debate_transcript"] = final_state.get("debate", [])
    prediction["agent_reports"] = {
        "fundamentals": final_state.get("fundamentals", {}),
        "sentiment": final_state.get("sentiment", {}),
        "technical": final_state.get("technical", {}),
    }
    return prediction
