"""SQLAlchemy implementation of the tenancy ``ApiKeyStore`` port."""

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ApiKey


class SqlAlchemyApiKeyStore:
    """API keys via SQLAlchemy."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        *,
        organization_id: uuid.UUID,
        name: str,
        key_hash: str,
        prefix: str,
        scopes: list[str] | None,
    ) -> ApiKey:
        key = ApiKey(
            organization_id=organization_id,
            name=name,
            key_hash=key_hash,
            prefix=prefix,
            scopes=scopes,
        )
        self._session.add(key)
        await self._session.flush()
        return key

    async def get_active_by_hash(self, key_hash: str) -> ApiKey | None:
        result = await self._session.execute(
            select(ApiKey).where(ApiKey.key_hash == key_hash, ApiKey.revoked_at.is_(None))
        )
        return result.scalars().first()

    async def list_by_org(self, organization_id: uuid.UUID) -> Sequence[ApiKey]:
        result = await self._session.execute(
            select(ApiKey)
            .where(ApiKey.organization_id == organization_id)
            .order_by(ApiKey.created_at)
        )
        return result.scalars().all()

    async def get(self, organization_id: uuid.UUID, key_id: uuid.UUID) -> ApiKey | None:
        result = await self._session.execute(
            select(ApiKey).where(ApiKey.id == key_id, ApiKey.organization_id == organization_id)
        )
        return result.scalars().first()

    async def revoke(self, api_key: ApiKey) -> None:
        api_key.revoked_at = datetime.now(UTC)
        await self._session.flush()

    async def touch(self, api_key: ApiKey) -> None:
        api_key.last_used_at = datetime.now(UTC)
