"""FastAPI application entry point.

Mount all API routers here.  The lifespan handler is a placeholder — DB
initialisation (create_all / Alembic migrations) can be wired in here when
needed rather than at import time.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.api.routes.analyze import router as analyze_router
from backend.api.routes.backtest import router as backtest_router
from backend.api.routes.ingest import router as ingest_router
from backend.api.routes.predictions import router as predictions_router
from backend.api.routes.reputation import router as reputation_router
from backend.api.routes.transcripts import router as transcripts_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Placeholder: add startup/shutdown logic here (e.g. DB init, warm-up).
    yield


app = FastAPI(
    title="earnings-agent",
    description="Multi-agent LLM framework for earnings call transcript analysis.",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["GET", "POST", "PATCH"],
    allow_headers=["Content-Type"],
)

app.include_router(analyze_router, prefix="/api/v1")
app.include_router(backtest_router, prefix="/api/v1")
app.include_router(ingest_router, prefix="/api/v1")
app.include_router(predictions_router, prefix="/api/v1")
app.include_router(reputation_router, prefix="/api/v1")
app.include_router(transcripts_router, prefix="/api/v1")
