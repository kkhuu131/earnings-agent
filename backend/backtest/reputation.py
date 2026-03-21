"""Reputation update logic for the earnings-agent pipeline.

After every backtest run, this module:

1. Reads all Prediction rows where ``was_correct IS NOT NULL``.
2. For each prediction, inspects the ``weighted_signals`` JSONB column to
   determine every agent's individual signal.
3. Maps each agent signal to a direction (bullish → up, bearish → down,
   neutral → neutral) and checks it against ``actual_direction``.
4. Tallies per-agent ``correct_predictions`` and ``total_predictions``.
5. Upserts ``AgentReputation`` rows with refreshed accuracy values.
6. Recomputes normalised ``weight`` for every agent so that all weights sum
   to 1.0.  Falls back to equal weights when all accuracies are zero.

Called from ``backend.backtest.runner.run_backtest`` at the end of each run.
"""

import logging
import uuid
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import AgentReputation, Prediction
from backend.db.session import get_session

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Signal → direction mapping
# ---------------------------------------------------------------------------

_SIGNAL_TO_DIRECTION: dict[str, str] = {
    "bullish": "up",
    "bearish": "down",
    "neutral": "neutral",
}


def _signal_to_direction(signal: str) -> str | None:
    """Map an agent signal string to a price direction.

    Args:
        signal: One of ``"bullish"``, ``"bearish"``, ``"neutral"``.

    Returns:
        The corresponding direction string, or ``None`` if unrecognised.
    """
    return _SIGNAL_TO_DIRECTION.get(signal.lower() if signal else "")


# ---------------------------------------------------------------------------
# Core update function
# ---------------------------------------------------------------------------


async def _update_reputation_with_session(session: AsyncSession) -> None:
    """Core reputation update logic operating on an open *session*.

    Separated from :func:`update_reputation` so that tests can pass in a
    mock session directly without needing to mock ``get_session``.
    """
    # ------------------------------------------------------------------
    # 1. Load all resolved predictions
    # ------------------------------------------------------------------
    stmt = select(Prediction).where(Prediction.was_correct.is_not(None))
    result = await session.execute(stmt)
    predictions = result.scalars().all()

    if not predictions:
        logger.debug("update_reputation: no resolved predictions found — skipping")
        return

    # ------------------------------------------------------------------
    # 2. Tally per-agent correct / total across all predictions
    # ------------------------------------------------------------------
    agent_stats: dict[str, dict[str, int]] = {}

    for pred in predictions:
        if not pred.weighted_signals or not pred.actual_direction:
            continue

        for agent_name, signal_info in pred.weighted_signals.items():
            stats = agent_stats.setdefault(agent_name, {"correct": 0, "total": 0})
            stats["total"] += 1

            signal = signal_info.get("signal", "") if isinstance(signal_info, dict) else ""
            predicted_direction = _signal_to_direction(signal)

            if predicted_direction is not None and predicted_direction == pred.actual_direction:
                stats["correct"] += 1

    if not agent_stats:
        logger.debug("update_reputation: no agent signal data found — skipping")
        return

    # ------------------------------------------------------------------
    # 3. Compute accuracy per agent
    # ------------------------------------------------------------------
    accuracies: dict[str, float] = {
        name: s["correct"] / s["total"] if s["total"] > 0 else 0.0
        for name, s in agent_stats.items()
    }

    # ------------------------------------------------------------------
    # 4. Compute normalised weights (equal-weight fallback if all zero)
    # ------------------------------------------------------------------
    total_accuracy = sum(accuracies.values())
    n_agents = len(agent_stats)

    if total_accuracy == 0.0:
        weights: dict[str, float] = {name: 1.0 / n_agents for name in agent_stats}
    else:
        weights = {name: acc / total_accuracy for name, acc in accuracies.items()}

    # ------------------------------------------------------------------
    # 5. Load existing AgentReputation rows for upsert
    # ------------------------------------------------------------------
    rep_stmt = select(AgentReputation)
    rep_result = await session.execute(rep_stmt)
    existing: dict[str, AgentReputation] = {
        row.agent_name: row for row in rep_result.scalars().all()
    }

    # ------------------------------------------------------------------
    # 6. Upsert — update existing rows or insert new ones
    # ------------------------------------------------------------------
    for agent_name, stats in agent_stats.items():
        accuracy_val = Decimal(str(round(accuracies[agent_name], 4)))
        weight_val = Decimal(str(round(weights[agent_name], 4)))

        if agent_name in existing:
            row = existing[agent_name]
            row.correct_predictions = stats["correct"]
            row.total_predictions = stats["total"]
            row.accuracy = accuracy_val
            row.weight = weight_val
            logger.debug(
                "update_reputation: updated %s → accuracy=%s weight=%s",
                agent_name,
                accuracy_val,
                weight_val,
            )
        else:
            row = AgentReputation(
                id=uuid.uuid4(),
                agent_name=agent_name,
                correct_predictions=stats["correct"],
                total_predictions=stats["total"],
                accuracy=accuracy_val,
                weight=weight_val,
            )
            session.add(row)
            logger.debug(
                "update_reputation: inserted %s → accuracy=%s weight=%s",
                agent_name,
                accuracy_val,
                weight_val,
            )


async def update_reputation() -> None:
    """Recompute agent accuracy scores and reputation weights.

    Opens its own DB session, reads all resolved ``Prediction`` rows, and
    upserts ``AgentReputation`` rows for every agent found in
    ``weighted_signals``.  Normalised weights are recomputed so they sum to
    1.0; equal weights are used as a fallback when all accuracies are zero.
    """
    async with get_session() as session:
        await _update_reputation_with_session(session)
