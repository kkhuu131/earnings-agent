"""GET /reputation — return current agent reputation weights.

Returns all rows from the agent_reputation table ordered by weight descending.
An empty list is returned when no backtest has been run yet.
"""

import logging

from fastapi import APIRouter
from sqlalchemy import select

from backend.api.schemas import AgentReputationRecord
from backend.db.models import AgentReputation
from backend.db.session import get_session

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/reputation", response_model=list[AgentReputationRecord])
async def get_reputation() -> list[AgentReputationRecord]:
    """Return all agent reputation rows ordered by weight descending."""
    async with get_session() as session:
        stmt = select(AgentReputation).order_by(AgentReputation.weight.desc())
        result = await session.execute(stmt)
        rows = result.scalars().all()
    return [AgentReputationRecord.model_validate(row) for row in rows]
