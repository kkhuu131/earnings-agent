"""Unit tests for POST /api/v1/analyze.

run_pipeline and get_session are mocked at the route module level so no
real LLM calls or database connections are made.

Tests verify:
  - 200 status on a valid request
  - All AnalyzeResponse fields are present and correctly typed
  - run_pipeline is called with the transcript and price_data from the body
  - The Prediction record is added to the session before the response returns
  - The ticker in the response is upper-cased
  - 422 is returned when required fields are missing
  - 500 is returned when run_pipeline raises an exception
"""

import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from backend.main import app

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

_MOCK_PREDICTION = {
    "direction": "up",
    "confidence": 0.78,
    "reasoning": "Strong revenue beat with confident management tone.",
    "weighted_signals": {
        "fundamentals": {"signal": "bullish", "weight": 0.2},
        "sentiment":    {"signal": "bullish", "weight": 0.2},
        "technical":    {"signal": "neutral", "weight": 0.2},
        "bull":         {"signal": "bullish", "weight": 0.2},
        "bear":         {"signal": "bearish", "weight": 0.2},
    },
    "agent_reports": {},
    "debate_transcript": {},
}

_ANALYZE_PAYLOAD = {
    "ticker": "aapl",
    "transcript": "Revenue grew 18% year-over-year...",
    "price_data": {"close": 182.5, "rsi": 56.2},
}


def _make_mock_session() -> MagicMock:
    session = MagicMock()
    session.flush = AsyncMock()
    return session


def _make_get_session_patch(session: MagicMock):
    """Return an asynccontextmanager factory that yields *session*."""

    @asynccontextmanager
    async def _mock_get_session():
        yield session

    return _mock_get_session


# ---------------------------------------------------------------------------
# Status codes
# ---------------------------------------------------------------------------


class TestAnalyzeStatusCodes:
    @pytest.mark.asyncio
    async def test_returns_200_on_valid_request(self):
        mock_session = _make_mock_session()
        with (
            patch(
                "backend.api.routes.analyze.run_pipeline",
                new=AsyncMock(return_value=_MOCK_PREDICTION),
            ),
            patch(
                "backend.api.routes.analyze.get_session",
                new=_make_get_session_patch(mock_session),
            ),
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.post("/api/v1/analyze", json=_ANALYZE_PAYLOAD)
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_returns_422_when_ticker_missing(self):
        payload = {k: v for k, v in _ANALYZE_PAYLOAD.items() if k != "ticker"}
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post("/api/v1/analyze", json=payload)
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_returns_422_when_transcript_missing(self):
        payload = {k: v for k, v in _ANALYZE_PAYLOAD.items() if k != "transcript"}
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post("/api/v1/analyze", json=payload)
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_returns_422_when_price_data_missing(self):
        payload = {k: v for k, v in _ANALYZE_PAYLOAD.items() if k != "price_data"}
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post("/api/v1/analyze", json=payload)
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_returns_500_when_pipeline_raises(self):
        mock_session = _make_mock_session()
        with (
            patch(
                "backend.api.routes.analyze.run_pipeline",
                new=AsyncMock(side_effect=RuntimeError("LLM unreachable")),
            ),
            patch(
                "backend.api.routes.analyze.get_session",
                new=_make_get_session_patch(mock_session),
            ),
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.post("/api/v1/analyze", json=_ANALYZE_PAYLOAD)
        assert resp.status_code == 500


# ---------------------------------------------------------------------------
# Response shape
# ---------------------------------------------------------------------------


class TestAnalyzeResponseShape:
    async def _post(self, payload=None) -> dict:
        mock_session = _make_mock_session()
        with (
            patch(
                "backend.api.routes.analyze.run_pipeline",
                new=AsyncMock(return_value=_MOCK_PREDICTION),
            ),
            patch(
                "backend.api.routes.analyze.get_session",
                new=_make_get_session_patch(mock_session),
            ),
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.post(
                    "/api/v1/analyze", json=payload or _ANALYZE_PAYLOAD
                )
        assert resp.status_code == 200
        return resp.json()

    @pytest.mark.asyncio
    async def test_response_contains_prediction_id(self):
        data = await self._post()
        assert "prediction_id" in data
        uuid.UUID(data["prediction_id"])  # must be valid UUID

    @pytest.mark.asyncio
    async def test_response_contains_ticker(self):
        data = await self._post()
        assert "ticker" in data

    @pytest.mark.asyncio
    async def test_response_contains_run_date(self):
        data = await self._post()
        assert "run_date" in data
        datetime.fromisoformat(data["run_date"])  # must be valid datetime

    @pytest.mark.asyncio
    async def test_response_contains_direction(self):
        data = await self._post()
        assert "direction" in data
        assert data["direction"] in ("up", "down", "neutral")

    @pytest.mark.asyncio
    async def test_response_contains_confidence(self):
        data = await self._post()
        assert "confidence" in data
        assert isinstance(data["confidence"], float)

    @pytest.mark.asyncio
    async def test_response_contains_reasoning(self):
        data = await self._post()
        assert "reasoning" in data
        assert isinstance(data["reasoning"], str)

    @pytest.mark.asyncio
    async def test_response_contains_weighted_signals(self):
        data = await self._post()
        assert "weighted_signals" in data
        assert isinstance(data["weighted_signals"], dict)

    @pytest.mark.asyncio
    async def test_ticker_is_uppercased(self):
        data = await self._post()
        assert data["ticker"] == _ANALYZE_PAYLOAD["ticker"].upper()

    @pytest.mark.asyncio
    async def test_direction_matches_pipeline_output(self):
        data = await self._post()
        assert data["direction"] == _MOCK_PREDICTION["direction"]

    @pytest.mark.asyncio
    async def test_confidence_matches_pipeline_output(self):
        data = await self._post()
        assert data["confidence"] == pytest.approx(_MOCK_PREDICTION["confidence"])

    @pytest.mark.asyncio
    async def test_reasoning_matches_pipeline_output(self):
        data = await self._post()
        assert data["reasoning"] == _MOCK_PREDICTION["reasoning"]


# ---------------------------------------------------------------------------
# Pipeline integration
# ---------------------------------------------------------------------------


class TestAnalyzePipelineCall:
    @pytest.mark.asyncio
    async def test_run_pipeline_called_once(self):
        mock_pipeline = AsyncMock(return_value=_MOCK_PREDICTION)
        mock_session = _make_mock_session()
        with (
            patch("backend.api.routes.analyze.run_pipeline", new=mock_pipeline),
            patch(
                "backend.api.routes.analyze.get_session",
                new=_make_get_session_patch(mock_session),
            ),
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                await client.post("/api/v1/analyze", json=_ANALYZE_PAYLOAD)
        mock_pipeline.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_run_pipeline_called_with_transcript(self):
        mock_pipeline = AsyncMock(return_value=_MOCK_PREDICTION)
        mock_session = _make_mock_session()
        with (
            patch("backend.api.routes.analyze.run_pipeline", new=mock_pipeline),
            patch(
                "backend.api.routes.analyze.get_session",
                new=_make_get_session_patch(mock_session),
            ),
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                await client.post("/api/v1/analyze", json=_ANALYZE_PAYLOAD)
        args, _ = mock_pipeline.call_args
        assert args[0] == _ANALYZE_PAYLOAD["transcript"]

    @pytest.mark.asyncio
    async def test_run_pipeline_called_with_price_data(self):
        mock_pipeline = AsyncMock(return_value=_MOCK_PREDICTION)
        mock_session = _make_mock_session()
        with (
            patch("backend.api.routes.analyze.run_pipeline", new=mock_pipeline),
            patch(
                "backend.api.routes.analyze.get_session",
                new=_make_get_session_patch(mock_session),
            ),
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                await client.post("/api/v1/analyze", json=_ANALYZE_PAYLOAD)
        args, _ = mock_pipeline.call_args
        assert args[1] == _ANALYZE_PAYLOAD["price_data"]


# ---------------------------------------------------------------------------
# Database persistence
# ---------------------------------------------------------------------------


class TestAnalyzePersistence:
    @pytest.mark.asyncio
    async def test_prediction_record_added_to_session(self):
        mock_pipeline = AsyncMock(return_value=_MOCK_PREDICTION)
        mock_session = _make_mock_session()
        with (
            patch("backend.api.routes.analyze.run_pipeline", new=mock_pipeline),
            patch(
                "backend.api.routes.analyze.get_session",
                new=_make_get_session_patch(mock_session),
            ),
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                await client.post("/api/v1/analyze", json=_ANALYZE_PAYLOAD)
        mock_session.add.assert_called_once()

    @pytest.mark.asyncio
    async def test_persisted_record_has_correct_ticker(self):
        mock_pipeline = AsyncMock(return_value=_MOCK_PREDICTION)
        mock_session = _make_mock_session()
        with (
            patch("backend.api.routes.analyze.run_pipeline", new=mock_pipeline),
            patch(
                "backend.api.routes.analyze.get_session",
                new=_make_get_session_patch(mock_session),
            ),
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                await client.post("/api/v1/analyze", json=_ANALYZE_PAYLOAD)
        (record,), _ = mock_session.add.call_args
        assert record.ticker == _ANALYZE_PAYLOAD["ticker"].upper()

    @pytest.mark.asyncio
    async def test_persisted_record_has_correct_direction(self):
        mock_pipeline = AsyncMock(return_value=_MOCK_PREDICTION)
        mock_session = _make_mock_session()
        with (
            patch("backend.api.routes.analyze.run_pipeline", new=mock_pipeline),
            patch(
                "backend.api.routes.analyze.get_session",
                new=_make_get_session_patch(mock_session),
            ),
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                await client.post("/api/v1/analyze", json=_ANALYZE_PAYLOAD)
        (record,), _ = mock_session.add.call_args
        assert record.final_direction == _MOCK_PREDICTION["direction"]

    @pytest.mark.asyncio
    async def test_persisted_record_has_uuid_id(self):
        mock_pipeline = AsyncMock(return_value=_MOCK_PREDICTION)
        mock_session = _make_mock_session()
        with (
            patch("backend.api.routes.analyze.run_pipeline", new=mock_pipeline),
            patch(
                "backend.api.routes.analyze.get_session",
                new=_make_get_session_patch(mock_session),
            ),
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                await client.post("/api/v1/analyze", json=_ANALYZE_PAYLOAD)
        (record,), _ = mock_session.add.call_args
        assert isinstance(record.id, uuid.UUID)

    @pytest.mark.asyncio
    async def test_response_prediction_id_matches_persisted_record_id(self):
        mock_pipeline = AsyncMock(return_value=_MOCK_PREDICTION)
        mock_session = _make_mock_session()
        with (
            patch("backend.api.routes.analyze.run_pipeline", new=mock_pipeline),
            patch(
                "backend.api.routes.analyze.get_session",
                new=_make_get_session_patch(mock_session),
            ),
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.post("/api/v1/analyze", json=_ANALYZE_PAYLOAD)
        (record,), _ = mock_session.add.call_args
        assert str(record.id) == resp.json()["prediction_id"]
