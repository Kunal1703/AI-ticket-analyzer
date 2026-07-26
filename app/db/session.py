"""
Async database engine / session helpers for AI Ticket Analyzer.

Pure factory functions with no global state. The application is expected to
create an engine + sessionmaker at startup (when ``DATABASE_URL`` is set) and
store them on ``app.state`` — mirroring how the AI provider is managed. The app
runs normally without a database; nothing here executes at import time.

The ``postgresql+psycopg`` URL scheme works for both the async engine here and
the synchronous engine used by Alembic, so a single driver (psycopg 3) covers
both paths.
"""

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


def create_db_engine(database_url: str, *, echo: bool = False) -> AsyncEngine:
    """Create an async SQLAlchemy engine.

    The engine is lazy — no connection is opened until it is first used.

    Args:
        database_url: SQLAlchemy URL, e.g. ``postgresql+psycopg://user:pw@host/db``.
        echo: Whether to log emitted SQL.

    Returns:
        A configured ``AsyncEngine``.
    """
    return create_async_engine(database_url, echo=echo, pool_pre_ping=True)


def create_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Create an async session factory bound to the given engine."""
    return async_sessionmaker(engine, expire_on_commit=False)
