"""GET /predictions — prediction history.

Supports optional filtering by ticker and a configurable result limit.
Results are returned newest-first.
"""

import logging
from typing import Optional

from fastapi import APIRouter
from sqlalchemy import select

from backend.api.schemas import PredictionRecord
from backend.db.models import Prediction
from backend.db.session import get_session

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/predictions", response_model=list[PredictionRecord])
async def list_predictions(
    ticker: Optional[str] = None,
    limit: int = 50,
) -> list[PredictionRecord]:
    """Return stored predictions, newest first.

    Args:
        ticker: Optional ticker symbol to filter by (case-insensitive).
        limit: Maximum number of records to return (default 50).
    """
    async with get_session() as session:
        stmt = select(Prediction).order_by(Prediction.run_date.desc()).limit(limit)
        if ticker:
            stmt = stmt.where(Prediction.ticker == ticker.upper())
        result = await session.execute(stmt)
        rows = result.scalars().all()

    return [PredictionRecord.model_validate(row) for row in rows]
