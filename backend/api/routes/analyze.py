"""POST /analyze — run the full earnings analysis pipeline.

Calls run_pipeline, persists the result to the predictions table, and
returns an AnalyzeResponse with the stored prediction_id.
"""

import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException

from backend.api.schemas import AnalyzeRequest, AnalyzeResponse
from backend.db.models import Prediction
from backend.db.session import get_session
from backend.graph.earnings_graph import run_pipeline

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/analyze", response_model=AnalyzeResponse)
async def analyze(body: AnalyzeRequest) -> AnalyzeResponse:
    """Run the agent pipeline on the provided transcript and price data.

    1. Calls ``run_pipeline`` with the transcript and price data.
    2. Persists the prediction to the ``predictions`` table.
    3. Returns the prediction result plus the newly created ``prediction_id``.
    """
    ticker = body.ticker.upper()

    try:
        result = await run_pipeline(body.transcript, body.price_data)
    except Exception as exc:
        logger.exception("Pipeline failed for ticker %s", ticker)
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    prediction_id = uuid.uuid4()
    run_date = datetime.now(timezone.utc)

    record = Prediction(
        id=prediction_id,
        ticker=ticker,
        run_date=run_date,
        final_direction=result.get("direction"),
        final_confidence=result.get("confidence"),
        final_reasoning=result.get("reasoning"),
        agent_reports=result.get("agent_reports"),
        debate_transcript=result.get("debate_transcript"),
        weighted_signals=result.get("weighted_signals"),
    )

    async with get_session() as session:
        session.add(record)

    return AnalyzeResponse(
        prediction_id=prediction_id,
        ticker=ticker,
        run_date=run_date,
        direction=result.get("direction", "neutral"),
        confidence=float(result.get("confidence", 0.0)),
        reasoning=result.get("reasoning", ""),
        weighted_signals=result.get("weighted_signals", {}),
    )
