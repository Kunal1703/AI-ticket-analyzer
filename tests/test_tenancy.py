"""
Tests for the multi-tenancy data layer (Milestone M2.1).

Schema-level checks run without a database. A round-trip integration test
(skipped unless ``DATABASE_URL`` is set) verifies tenant rows persist and that
tickets remain creatable without an organization (back-compat).
"""

import os

import pytest
from app.db import models
from app.db.base import Base
from app.db.session import create_db_engine, create_sessionmaker
from sqlalchemy import select

DB_URL = os.environ.get("DATABASE_URL")


def test_tenancy_tables_registered() -> None:
    expected = {"organizations", "users", "memberships", "api_keys"}
    assert expected <= set(Base.metadata.tables)


def test_org_id_columns_are_nullable() -> None:
    assert models.Ticket.__table__.columns["organization_id"].nullable is True
    assert models.Analysis.__table__.columns["organization_id"].nullable is True


def test_membership_has_unique_org_user_constraint() -> None:
    constraint_cols = {
        tuple(sorted(c.name for c in constraint.columns))
        for constraint in models.Membership.__table__.constraints  # type: ignore[attr-defined]
        if constraint.__class__.__name__ == "UniqueConstraint"
    }
    assert ("organization_id", "user_id") in constraint_cols


@pytest.mark.anyio
@pytest.mark.skipif(not DB_URL, reason="DATABASE_URL not set; skipping DB integration test")
async def test_tenant_round_trip() -> None:
    assert DB_URL is not None  # guaranteed by skipif
    engine = create_db_engine(DB_URL)
    sessionmaker = create_sessionmaker(engine)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        async with sessionmaker() as session:
            org = models.Organization(name="Acme", slug="acme")
            user = models.User(email="owner@acme.test")
            session.add_all([org, user])
            await session.flush()
            session.add(models.Membership(organization_id=org.id, user_id=user.id, role="owner"))
            session.add(
                models.ApiKey(
                    organization_id=org.id, name="default", key_hash="hash-1", prefix="ak_test"
                )
            )
            scoped = models.Ticket(raw_text="scoped", text_hash="h-scoped", organization_id=org.id)
            session.add(scoped)
            await session.commit()
            org_id, scoped_id = org.id, scoped.id

        async with sessionmaker() as session:
            loaded = (
                await session.execute(select(models.Ticket).where(models.Ticket.id == scoped_id))
            ).scalar_one()
            assert loaded.organization_id == org_id

            # Back-compat: a ticket with no organization is still valid.
            legacy = models.Ticket(raw_text="legacy", text_hash="h-legacy")
            session.add(legacy)
            await session.commit()
            assert legacy.organization_id is None
    finally:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
        await engine.dispose()
