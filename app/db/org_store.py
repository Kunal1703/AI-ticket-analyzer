"""SQLAlchemy implementation of the tenancy ``OrgStore`` port."""

import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Membership, Organization


class SqlAlchemyOrgStore:
    """Organizations + memberships via SQLAlchemy."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, *, name: str, slug: str, owner_id: uuid.UUID) -> Organization:
        org = Organization(name=name, slug=slug)
        self._session.add(org)
        await self._session.flush()  # assign org.id
        self._session.add(Membership(organization_id=org.id, user_id=owner_id, role="owner"))
        await self._session.flush()
        return org

    async def get(self, organization_id: uuid.UUID) -> Organization | None:
        return await self._session.get(Organization, organization_id)

    async def list_for_user(self, user_id: uuid.UUID) -> Sequence[Organization]:
        result = await self._session.execute(
            select(Organization)
            .join(Membership, Membership.organization_id == Organization.id)
            .where(Membership.user_id == user_id)
            .order_by(Organization.created_at)
        )
        return result.scalars().all()

    async def get_membership(
        self, organization_id: uuid.UUID, user_id: uuid.UUID
    ) -> Membership | None:
        result = await self._session.execute(
            select(Membership).where(
                Membership.organization_id == organization_id,
                Membership.user_id == user_id,
            )
        )
        return result.scalars().first()
