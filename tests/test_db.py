"""
Tests for the database foundation (Milestone M1.1).

Most checks run without a database. The persistence round-trip is an
integration test that is skipped unless ``DATABASE_URL`` is set, so the suite
stays green in environments without Postgres.
"""

import os

import pytest
from app.config import Settings
from app.db import models
from app.db.base import Base
from app.db.session import create_db_engine, create_sessionmaker
from sqlalchemy import select

DB_URL = os.environ.get("DATABASE_URL")


def test_database_url_is_optional() -> None:
    """The app must be configurable without a database."""
    settings = Settings(_env_file=None, llm_api_key="sk-test-dummy")  # type: ignore[call-arg]
    assert settings.database_url is None


def test_metadata_registers_expected_tables() -> None:
    """Importing the ORM models registers the expected tables on the metadata."""
    assert {"tickets", "analyses"} <= set(Base.metadata.tables)


@pytest.mark.anyio
async def test_engine_and_sessionmaker_build_without_connecting() -> None:
    """Engine/sessionmaker construction is lazy and needs no live database."""
    engine = create_db_engine("postgresql+psycopg://user:pw@localhost:5432/db")
    try:
        sessionmaker = create_sessionmaker(engine)
        assert sessionmaker is not None
    finally:
        await engine.dispose()


@pytest.mark.anyio
@pytest.mark.skipif(not DB_URL, reason="DATABASE_URL not set; skipping DB integration test")
async def test_persist_and_read_back() -> None:
    """A ticket and its analysis can be persisted and read back."""
    assert DB_URL is not None  # guaranteed by skipif
    engine = create_db_engine(DB_URL)
    sessionmaker = create_sessionmaker(engine)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        async with sessionmaker() as session:
            ticket = models.Ticket(raw_text="My account is locked.", text_hash="abc123")
            ticket.analyses.append(
                models.Analysis(
                    summary="Customer cannot log in.",
                    category="Account Access",
                    priority="High",
                    next_actions=["Reset password"],
                    model="gpt-4o-2024-08-06",
                )
            )
            session.add(ticket)
            await session.commit()
            ticket_id = ticket.id

        async with sessionmaker() as session:
            loaded = (
                await session.execute(select(models.Ticket).where(models.Ticket.id == ticket_id))
            ).scalar_one()
            assert loaded.raw_text == "My account is locked."

            analyses = (
                (
                    await session.execute(
                        select(models.Analysis).where(models.Analysis.ticket_id == ticket_id)
                    )
                )
                .scalars()
                .all()
            )
            assert len(analyses) == 1
            assert analyses[0].category == "Account Access"
    finally:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
        await engine.dispose()
