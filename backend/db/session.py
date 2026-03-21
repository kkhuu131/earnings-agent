"""Async SQLAlchemy engine and session factory for earnings-agent.

The module-level ``engine`` is created once at import time from the DATABASE_URL
in settings.  Use ``get_session()`` as an async context manager everywhere that
needs a database session — it commits on success, rolls back on error, and
always closes the session.

Usage:
    from backend.db.session import get_session

    async with get_session() as session:
        result = await session.execute(select(Transcript))
        transcripts = result.scalars().all()
"""

import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from backend.config import settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# URL coercion
# ---------------------------------------------------------------------------


def _coerce_asyncpg_url(url: str) -> str:
    """Ensure the URL uses the ``postgresql+asyncpg://`` dialect prefix.

    Supabase and most PaaS providers hand out plain ``postgresql://`` or
    ``postgres://`` connection strings, which SQLAlchemy's async engine does
    not accept without the driver suffix.
    """
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+asyncpg://", 1)
    return url


# ---------------------------------------------------------------------------
# Engine (module-level singleton)
# ---------------------------------------------------------------------------

engine: AsyncEngine = create_async_engine(
    _coerce_asyncpg_url(settings.database_url),
    echo=False,
    pool_pre_ping=True,       # discard stale connections before use
    pool_size=5,
    max_overflow=10,
)

_AsyncSessionFactory: async_sessionmaker[AsyncSession] = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,   # keep objects usable after commit
    autoflush=False,
    autocommit=False,
)


# ---------------------------------------------------------------------------
# Session context manager
# ---------------------------------------------------------------------------


@asynccontextmanager
async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Yield an ``AsyncSession``, committing or rolling back automatically.

    - Commits when the ``async with`` block exits cleanly.
    - Rolls back if any exception is raised inside the block.
    - Always closes the session (returns the connection to the pool).

    Usage::

        async with get_session() as session:
            session.add(some_model_instance)
    """
    session: AsyncSession = _AsyncSessionFactory()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()
