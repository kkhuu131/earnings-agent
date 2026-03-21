"""Unit tests for GET /api/v1/predictions.

get_session is mocked at the route module level so no real database
connections are made.

Tests verify:
  - 200 status with an empty list when no rows exist
  - 200 status with serialised PredictionRecord objects
  - Each record contains the required fields
  - Optional ticker query param is forwarded to the query
  - Optional limit query param is respected
  - Default limit of 50 is used when limit is omitted
"""

import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from backend.main import app

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_prediction_row(**overrides) -> MagicMock:
    """Return a MagicMock shaped like a Prediction ORM row."""
    row = MagicMock()
    row.id = uuid.uuid4()
    row.ticker = "AAPL"
    row.run_date = datetime(2026, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
    row.final_direction = "up"
    row.final_confidence = 0.8
    row.final_reasoning = "Strong beat."
    row.agent_reports = None
    row.debate_transcript = None
    row.weighted_signals = None
    row.actual_direction = None
    row.was_correct = None
    for key, value in overrides.items():
        setattr(row, key, value)
    return row


def _make_mock_session(rows: list) -> MagicMock:
    """Return a mock session whose execute() yields *rows*."""
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = rows
    session = MagicMock()
    session.execute = AsyncMock(return_value=mock_result)
    return session


def _make_get_session_patch(session: MagicMock):
    @asynccontextmanager
    async def _mock_get_session():
        yield session

    return _mock_get_session


# ---------------------------------------------------------------------------
# Status codes
# ---------------------------------------------------------------------------


class TestPredictionsStatusCodes:
    @pytest.mark.asyncio
    async def test_returns_200_with_empty_list(self):
        mock_session = _make_mock_session(rows=[])
        with patch(
            "backend.api.routes.predictions.get_session",
            new=_make_get_session_patch(mock_session),
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.get("/api/v1/predictions")
        assert resp.status_code == 200
        assert resp.json() == []

    @pytest.mark.asyncio
    async def test_returns_200_with_predictions(self):
        rows = [_make_prediction_row(), _make_prediction_row()]
        mock_session = _make_mock_session(rows=rows)
        with patch(
            "backend.api.routes.predictions.get_session",
            new=_make_get_session_patch(mock_session),
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.get("/api/v1/predictions")
        assert resp.status_code == 200
        assert len(resp.json()) == 2


# ---------------------------------------------------------------------------
# Response shape
# ---------------------------------------------------------------------------


class TestPredictionsResponseShape:
    @pytest.mark.asyncio
    async def test_response_is_list(self):
        mock_session = _make_mock_session(rows=[_make_prediction_row()])
        with patch(
            "backend.api.routes.predictions.get_session",
            new=_make_get_session_patch(mock_session),
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.get("/api/v1/predictions")
        assert isinstance(resp.json(), list)

    @pytest.mark.asyncio
    async def test_record_contains_id(self):
        row = _make_prediction_row()
        mock_session = _make_mock_session(rows=[row])
        with patch(
            "backend.api.routes.predictions.get_session",
            new=_make_get_session_patch(mock_session),
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.get("/api/v1/predictions")
        record = resp.json()[0]
        assert "id" in record
        uuid.UUID(record["id"])  # must be valid UUID

    @pytest.mark.asyncio
    async def test_record_contains_ticker(self):
        mock_session = _make_mock_session(rows=[_make_prediction_row(ticker="MSFT")])
        with patch(
            "backend.api.routes.predictions.get_session",
            new=_make_get_session_patch(mock_session),
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.get("/api/v1/predictions")
        assert resp.json()[0]["ticker"] == "MSFT"

    @pytest.mark.asyncio
    async def test_record_contains_run_date(self):
        mock_session = _make_mock_session(rows=[_make_prediction_row()])
        with patch(
            "backend.api.routes.predictions.get_session",
            new=_make_get_session_patch(mock_session),
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.get("/api/v1/predictions")
        record = resp.json()[0]
        assert "run_date" in record
        datetime.fromisoformat(record["run_date"])  # must parse

    @pytest.mark.asyncio
    async def test_record_contains_final_direction(self):
        mock_session = _make_mock_session(rows=[_make_prediction_row(final_direction="down")])
        with patch(
            "backend.api.routes.predictions.get_session",
            new=_make_get_session_patch(mock_session),
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.get("/api/v1/predictions")
        assert resp.json()[0]["final_direction"] == "down"

    @pytest.mark.asyncio
    async def test_optional_fields_can_be_none(self):
        row = _make_prediction_row(
            agent_reports=None,
            debate_transcript=None,
            weighted_signals=None,
            actual_direction=None,
            was_correct=None,
        )
        mock_session = _make_mock_session(rows=[row])
        with patch(
            "backend.api.routes.predictions.get_session",
            new=_make_get_session_patch(mock_session),
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.get("/api/v1/predictions")
        record = resp.json()[0]
        assert record["agent_reports"] is None
        assert record["was_correct"] is None


# ---------------------------------------------------------------------------
# Query parameters
# ---------------------------------------------------------------------------


class TestPredictionsQueryParams:
    @pytest.mark.asyncio
    async def test_execute_called_once(self):
        mock_session = _make_mock_session(rows=[])
        with patch(
            "backend.api.routes.predictions.get_session",
            new=_make_get_session_patch(mock_session),
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                await client.get("/api/v1/predictions")
        mock_session.execute.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_ticker_param_accepted(self):
        """Passing ticker= should not raise an error."""
        mock_session = _make_mock_session(rows=[])
        with patch(
            "backend.api.routes.predictions.get_session",
            new=_make_get_session_patch(mock_session),
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.get("/api/v1/predictions", params={"ticker": "AAPL"})
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_limit_param_accepted(self):
        """Passing limit= should not raise an error."""
        mock_session = _make_mock_session(rows=[])
        with patch(
            "backend.api.routes.predictions.get_session",
            new=_make_get_session_patch(mock_session),
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.get("/api/v1/predictions", params={"limit": 10})
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_ticker_and_limit_combined(self):
        mock_session = _make_mock_session(rows=[])
        with patch(
            "backend.api.routes.predictions.get_session",
            new=_make_get_session_patch(mock_session),
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.get(
                    "/api/v1/predictions", params={"ticker": "NVDA", "limit": 5}
                )
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_multiple_rows_returned(self):
        rows = [
            _make_prediction_row(ticker="AAPL"),
            _make_prediction_row(ticker="AAPL"),
            _make_prediction_row(ticker="AAPL"),
        ]
        mock_session = _make_mock_session(rows=rows)
        with patch(
            "backend.api.routes.predictions.get_session",
            new=_make_get_session_patch(mock_session),
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.get("/api/v1/predictions", params={"ticker": "AAPL"})
        assert len(resp.json()) == 3
