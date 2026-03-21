"""Unit tests for backend/db/session.py.

No real database connection is required — the engine and session factory are
replaced with AsyncMock objects.  Tests verify:
  - _coerce_asyncpg_url rewrites plain postgresql:// and postgres:// URLs
  - get_session() commits on clean exit
  - get_session() rolls back and re-raises on exception
  - get_session() always closes the session (even after an error)
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.db.session import _coerce_asyncpg_url, get_session


# ---------------------------------------------------------------------------
# _coerce_asyncpg_url
# ---------------------------------------------------------------------------


class TestCoerceAsyncpgUrl:
    def test_passthrough_already_asyncpg(self):
        url = "postgresql+asyncpg://user:pw@host/db"
        assert _coerce_asyncpg_url(url) == url

    def test_rewrites_postgresql_scheme(self):
        url = "postgresql://user:pw@host/db"
        result = _coerce_asyncpg_url(url)
        assert result == "postgresql+asyncpg://user:pw@host/db"

    def test_rewrites_postgres_alias(self):
        url = "postgres://user:pw@host/db"
        result = _coerce_asyncpg_url(url)
        assert result == "postgresql+asyncpg://user:pw@host/db"

    def test_does_not_double_rewrite(self):
        url = "postgresql+asyncpg://user:pw@host/db"
        # Calling twice must be idempotent
        assert _coerce_asyncpg_url(_coerce_asyncpg_url(url)) == url

    def test_leaves_other_schemes_unchanged(self):
        url = "sqlite+aiosqlite:///./test.db"
        assert _coerce_asyncpg_url(url) == url


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_session():
    """Return a mock AsyncSession with async commit / rollback / close."""
    session = MagicMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    session.close = AsyncMock()
    return session


# ---------------------------------------------------------------------------
# get_session — happy path
# ---------------------------------------------------------------------------


class TestGetSessionHappyPath:
    async def test_commits_on_clean_exit(self):
        mock_session = _make_mock_session()

        with patch("backend.db.session._AsyncSessionFactory", return_value=mock_session):
            async with get_session() as session:
                assert session is mock_session

        mock_session.commit.assert_awaited_once()
        mock_session.rollback.assert_not_awaited()

    async def test_closes_on_clean_exit(self):
        mock_session = _make_mock_session()

        with patch("backend.db.session._AsyncSessionFactory", return_value=mock_session):
            async with get_session():
                pass

        mock_session.close.assert_awaited_once()

    async def test_yields_the_session_object(self):
        mock_session = _make_mock_session()

        with patch("backend.db.session._AsyncSessionFactory", return_value=mock_session):
            async with get_session() as session:
                assert session is mock_session


# ---------------------------------------------------------------------------
# get_session — error path
# ---------------------------------------------------------------------------


class TestGetSessionErrorPath:
    async def test_rolls_back_on_exception(self):
        mock_session = _make_mock_session()

        with patch("backend.db.session._AsyncSessionFactory", return_value=mock_session):
            with pytest.raises(ValueError, match="boom"):
                async with get_session():
                    raise ValueError("boom")

        mock_session.rollback.assert_awaited_once()
        mock_session.commit.assert_not_awaited()

    async def test_closes_even_after_exception(self):
        mock_session = _make_mock_session()

        with patch("backend.db.session._AsyncSessionFactory", return_value=mock_session):
            with pytest.raises(RuntimeError):
                async with get_session():
                    raise RuntimeError("db error")

        mock_session.close.assert_awaited_once()

    async def test_reraises_the_original_exception(self):
        mock_session = _make_mock_session()

        class _CustomError(Exception):
            pass

        with patch("backend.db.session._AsyncSessionFactory", return_value=mock_session):
            with pytest.raises(_CustomError):
                async with get_session():
                    raise _CustomError("original")

    async def test_does_not_commit_after_rollback(self):
        """Ensure commit is never called when the block raises."""
        mock_session = _make_mock_session()

        with patch("backend.db.session._AsyncSessionFactory", return_value=mock_session):
            with pytest.raises(Exception):
                async with get_session():
                    raise Exception("error")

        mock_session.commit.assert_not_awaited()
        mock_session.rollback.assert_awaited_once()
