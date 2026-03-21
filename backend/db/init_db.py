"""Bootstrap script: create all database tables from the ORM models.

Run this once against a fresh database to create the schema.
Idempotent — uses ``CREATE TABLE IF NOT EXISTS`` semantics via
``Base.metadata.create_all``.  Full Alembic migrations will replace this
when the schema stabilises.

Usage:
    python -m backend.db.init_db
"""

import asyncio
import logging

from backend.db.models import Base
from backend.db.session import engine

logger = logging.getLogger(__name__)


async def create_tables() -> None:
    """Create all tables that do not already exist."""
    async with engine.begin() as conn:
        logger.info("Running create_all against %s", engine.url)
        await conn.run_sync(Base.metadata.create_all)
        logger.info("Schema bootstrap complete.")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    asyncio.run(create_tables())
