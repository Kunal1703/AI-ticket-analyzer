"""
Tenancy HTTP routes: organizations, API keys, and tenant context.

Organization/API-key management requires a logged-in user (JWT) who is a member
of the target org. The ``/v1/tenant`` endpoint demonstrates tenant-context
resolution from either an API key or a user token.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Response

from app.db.models import ApiKey, Membership, Organization, User
from app.dependencies import (
    get_api_key_service,
    get_current_user,
    get_org_service,
    get_tenant_context,
    require_org_membership,
    require_role,
)
from app.models import (
    ApiKeyCreatedResponse,
    ApiKeyResponse,
    CreateApiKeyRequest,
    CreateOrgRequest,
    OrgResponse,
    TenantContextResponse,
)
from app.tenancy.base import ApiKeyNotFoundError, TenantContext
from app.tenancy.service import ApiKeyService, OrganizationService

router = APIRouter(prefix="/v1", tags=["Tenancy"])

# Module-level dependency singleton (avoids a function call inside Depends()).
_require_owner_or_admin = require_role("owner", "admin")


def _org_response(org: Organization) -> OrgResponse:
    return OrgResponse(id=str(org.id), name=org.name, slug=org.slug, plan=org.plan)


def _api_key_response(key: ApiKey) -> ApiKeyResponse:
    return ApiKeyResponse(
        id=str(key.id),
        name=key.name,
        prefix=key.prefix,
        scopes=list(key.scopes or []),
        revoked=key.revoked_at is not None,
    )


@router.post("/orgs", response_model=OrgResponse, status_code=201, summary="Create organization")
async def create_org(
    payload: CreateOrgRequest,
    current_user: User = Depends(get_current_user),
    org_service: OrganizationService = Depends(get_org_service),
) -> OrgResponse:
    org = await org_service.create_org(name=payload.name, owner_id=current_user.id)
    return _org_response(org)


@router.get("/orgs", response_model=list[OrgResponse], summary="List my organizations")
async def list_orgs(
    current_user: User = Depends(get_current_user),
    org_service: OrganizationService = Depends(get_org_service),
) -> list[OrgResponse]:
    return [_org_response(o) for o in await org_service.list_orgs(current_user.id)]


@router.post(
    "/orgs/{org_id}/api-keys",
    response_model=ApiKeyCreatedResponse,
    status_code=201,
    summary="Create API key",
)
async def create_api_key(
    org_id: uuid.UUID,
    payload: CreateApiKeyRequest,
    _membership: Membership = Depends(_require_owner_or_admin),
    api_key_service: ApiKeyService = Depends(get_api_key_service),
) -> ApiKeyCreatedResponse:
    key, plaintext = await api_key_service.create_key(
        organization_id=org_id, name=payload.name, scopes=payload.scopes
    )
    base = _api_key_response(key)
    return ApiKeyCreatedResponse(**base.model_dump(), api_key=plaintext)


@router.get(
    "/orgs/{org_id}/api-keys",
    response_model=list[ApiKeyResponse],
    summary="List API keys",
)
async def list_api_keys(
    org_id: uuid.UUID,
    _membership: Membership = Depends(require_org_membership),
    api_key_service: ApiKeyService = Depends(get_api_key_service),
) -> list[ApiKeyResponse]:
    return [_api_key_response(k) for k in await api_key_service.list_keys(org_id)]


@router.delete(
    "/orgs/{org_id}/api-keys/{key_id}",
    status_code=204,
    summary="Revoke API key",
)
async def revoke_api_key(
    org_id: uuid.UUID,
    key_id: uuid.UUID,
    _membership: Membership = Depends(_require_owner_or_admin),
    api_key_service: ApiKeyService = Depends(get_api_key_service),
) -> Response:
    try:
        await api_key_service.revoke_key(org_id, key_id)
    except ApiKeyNotFoundError as exc:
        raise HTTPException(status_code=404, detail="API key not found") from exc
    return Response(status_code=204)


@router.get("/tenant", response_model=TenantContextResponse, summary="Current tenant context")
async def current_tenant(
    context: TenantContext = Depends(get_tenant_context),
) -> TenantContextResponse:
    return TenantContextResponse(
        organization_id=str(context.organization_id),
        principal_type=context.principal_type,
        scopes=list(context.scopes),
    )
