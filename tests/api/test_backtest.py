"""Unit tests for POST /api/v1/backtest.

run_backtest is mocked at the route module level so no real database
connections or pipeline calls are made.

Tests verify:
  - 200 status on a valid request
  - All BacktestResponse fields are present and correctly typed
  - run_backtest is called with the correct tickers, start_date, end_date
  - per_ticker breakdown is included in the response
  - 422 is returned when required fields are missing
  - 500 is returned when run_backtest raises an exception
  - Empty tickers list is accepted and returns zero-filled response
"""

from datetime import date
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from backend.main import app

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

_MOCK_SUMMARY = {
    "total": 4,
    "correct": 3,
    "accuracy": 0.75,
    "per_ticker": {
        "AAPL": {"total": 2, "correct": 2, "accuracy": 1.0},
        "MSFT": {"total": 2, "correct": 1, "accuracy": 0.5},
    },
}

_MOCK_EMPTY_SUMMARY = {
    "total": 0,
    "correct": 0,
    "accuracy": 0.0,
    "per_ticker": {},
}

_BACKTEST_PAYLOAD = {
    "tickers": ["AAPL", "MSFT"],
    "start_date": "2024-01-01",
    "end_date": "2024-12-31",
}


# ---------------------------------------------------------------------------
# Status codes
# ---------------------------------------------------------------------------


class TestBacktestStatusCodes:
    @pytest.mark.asyncio
    async def test_returns_200_on_valid_request(self):
        with patch(
            "backend.api.routes.backtest.run_backtest",
            new=AsyncMock(return_value=_MOCK_SUMMARY),
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.post("/api/v1/backtest", json=_BACKTEST_PAYLOAD)
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_returns_422_when_tickers_missing(self):
        payload = {k: v for k, v in _BACKTEST_PAYLOAD.items() if k != "tickers"}
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post("/api/v1/backtest", json=payload)
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_returns_422_when_start_date_missing(self):
        payload = {k: v for k, v in _BACKTEST_PAYLOAD.items() if k != "start_date"}
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post("/api/v1/backtest", json=payload)
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_returns_422_when_end_date_missing(self):
        payload = {k: v for k, v in _BACKTEST_PAYLOAD.items() if k != "end_date"}
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post("/api/v1/backtest", json=payload)
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_returns_500_when_run_backtest_raises(self):
        with patch(
            "backend.api.routes.backtest.run_backtest",
            new=AsyncMock(side_effect=RuntimeError("DB unreachable")),
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.post("/api/v1/backtest", json=_BACKTEST_PAYLOAD)
        assert resp.status_code == 500

    @pytest.mark.asyncio
    async def test_returns_200_with_empty_tickers(self):
        with patch(
            "backend.api.routes.backtest.run_backtest",
            new=AsyncMock(return_value=_MOCK_EMPTY_SUMMARY),
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.post(
                    "/api/v1/backtest",
                    json={**_BACKTEST_PAYLOAD, "tickers": []},
                )
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Response shape
# ---------------------------------------------------------------------------


class TestBacktestResponseShape:
    async def _post(self, payload=None, summary=None) -> dict:
        with patch(
            "backend.api.routes.backtest.run_backtest",
            new=AsyncMock(return_value=summary or _MOCK_SUMMARY),
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.post(
                    "/api/v1/backtest", json=payload or _BACKTEST_PAYLOAD
                )
        assert resp.status_code == 200
        return resp.json()

    @pytest.mark.asyncio
    async def test_response_contains_total(self):
        data = await self._post()
        assert "total" in data
        assert isinstance(data["total"], int)

    @pytest.mark.asyncio
    async def test_response_contains_correct(self):
        data = await self._post()
        assert "correct" in data
        assert isinstance(data["correct"], int)

    @pytest.mark.asyncio
    async def test_response_contains_accuracy(self):
        data = await self._post()
        assert "accuracy" in data
        assert isinstance(data["accuracy"], float)

    @pytest.mark.asyncio
    async def test_response_contains_per_ticker(self):
        data = await self._post()
        assert "per_ticker" in data
        assert isinstance(data["per_ticker"], dict)

    @pytest.mark.asyncio
    async def test_total_matches_summary(self):
        data = await self._post()
        assert data["total"] == _MOCK_SUMMARY["total"]

    @pytest.mark.asyncio
    async def test_correct_matches_summary(self):
        data = await self._post()
        assert data["correct"] == _MOCK_SUMMARY["correct"]

    @pytest.mark.asyncio
    async def test_accuracy_matches_summary(self):
        data = await self._post()
        assert data["accuracy"] == pytest.approx(_MOCK_SUMMARY["accuracy"])

    @pytest.mark.asyncio
    async def test_per_ticker_keys_present(self):
        data = await self._post()
        assert set(data["per_ticker"].keys()) == {"AAPL", "MSFT"}

    @pytest.mark.asyncio
    async def test_per_ticker_entry_has_total(self):
        data = await self._post()
        assert "total" in data["per_ticker"]["AAPL"]

    @pytest.mark.asyncio
    async def test_per_ticker_entry_has_correct(self):
        data = await self._post()
        assert "correct" in data["per_ticker"]["AAPL"]

    @pytest.mark.asyncio
    async def test_per_ticker_entry_has_accuracy(self):
        data = await self._post()
        assert "accuracy" in data["per_ticker"]["AAPL"]

    @pytest.mark.asyncio
    async def test_per_ticker_accuracy_value(self):
        data = await self._post()
        assert data["per_ticker"]["AAPL"]["accuracy"] == pytest.approx(1.0)
        assert data["per_ticker"]["MSFT"]["accuracy"] == pytest.approx(0.5)

    @pytest.mark.asyncio
    async def test_empty_tickers_returns_zero_summary(self):
        data = await self._post(
            payload={**_BACKTEST_PAYLOAD, "tickers": []},
            summary=_MOCK_EMPTY_SUMMARY,
        )
        assert data["total"] == 0
        assert data["accuracy"] == pytest.approx(0.0)
        assert data["per_ticker"] == {}


# ---------------------------------------------------------------------------
# run_backtest call args
# ---------------------------------------------------------------------------


class TestBacktestCallArgs:
    @pytest.mark.asyncio
    async def test_run_backtest_called_once(self):
        mock_runner = AsyncMock(return_value=_MOCK_SUMMARY)
        with patch("backend.api.routes.backtest.run_backtest", new=mock_runner):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                await client.post("/api/v1/backtest", json=_BACKTEST_PAYLOAD)
        mock_runner.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_run_backtest_called_with_tickers(self):
        mock_runner = AsyncMock(return_value=_MOCK_SUMMARY)
        with patch("backend.api.routes.backtest.run_backtest", new=mock_runner):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                await client.post("/api/v1/backtest", json=_BACKTEST_PAYLOAD)
        _, kwargs = mock_runner.call_args
        assert kwargs["tickers"] == _BACKTEST_PAYLOAD["tickers"]

    @pytest.mark.asyncio
    async def test_run_backtest_called_with_start_date(self):
        mock_runner = AsyncMock(return_value=_MOCK_SUMMARY)
        with patch("backend.api.routes.backtest.run_backtest", new=mock_runner):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                await client.post("/api/v1/backtest", json=_BACKTEST_PAYLOAD)
        _, kwargs = mock_runner.call_args
        assert kwargs["start_date"] == date(2024, 1, 1)

    @pytest.mark.asyncio
    async def test_run_backtest_called_with_end_date(self):
        mock_runner = AsyncMock(return_value=_MOCK_SUMMARY)
        with patch("backend.api.routes.backtest.run_backtest", new=mock_runner):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                await client.post("/api/v1/backtest", json=_BACKTEST_PAYLOAD)
        _, kwargs = mock_runner.call_args
        assert kwargs["end_date"] == date(2024, 12, 31)
