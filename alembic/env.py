"""
Alembic migration environment for AI Ticket Analyzer.

The database URL is read from the ``DATABASE_URL`` environment variable (falling
back to ``sqlalchemy.url`` in alembic.ini). Migrations run synchronously using
the psycopg driver; the same ``postgresql+psycopg`` URL also serves the app's
async engine.
"""

import os
from logging.config import fileConfig

from alembic import context
from app.db import models  # noqa: F401  (imported for side-effect: table registration)

# Import metadata + models so 'autogenerate' and table creation see all tables.
from app.db.base import Base
from sqlalchemy import engine_from_config, pool

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _database_url() -> str:
    url = os.environ.get("DATABASE_URL") or config.get_main_option("sqlalchemy.url")
    if not url:
        raise RuntimeError(
            "DATABASE_URL is not set. Provide it via the environment, e.g. "
            "DATABASE_URL=postgresql+psycopg://user:pw@localhost:5432/db"
        )
    return url


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (emit SQL without a DBAPI connection)."""
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode against a live database connection."""
    configuration = config.get_section(config.config_ini_section) or {}
    configuration["sqlalchemy.url"] = _database_url()
    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
