"""
SQLAlchemy implementation of the auth ``UserStore`` port.

Wraps an ``AsyncSession`` to provide user lookup/creation. Structurally
satisfies :class:`app.auth.base.UserStore`.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import User


class SqlAlchemyUserStore:
    """Persist and look up users via SQLAlchemy."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_email(self, email: str) -> User | None:
        result = await self._session.execute(select(User).where(User.email == email))
        return result.scalars().first()

    async def get_by_id(self, user_id: uuid.UUID) -> User | None:
        return await self._session.get(User, user_id)

    async def create(self, *, email: str, password_hash: str | None, name: str | None) -> User:
        user = User(email=email, password_hash=password_hash, name=name)
        self._session.add(user)
        await self._session.flush()  # assign id
        return user
