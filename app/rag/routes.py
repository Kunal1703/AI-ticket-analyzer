"""
Knowledge-base (RAG) HTTP routes (M5.2).

Per-tenant KB document management under ``/v1/orgs/{org_id}/documents`` (owner/
admin to create/delete, membership to list/read/search), plus a retrieval
``/search`` endpoint. Documents are chunked + embedded on create and used to
ground the tenant-scoped analyze path (see ``app.services.analyze``).
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from app.db.models import Document, Membership
from app.dependencies import (
    get_rag_service,
    get_vector_store,
    require_org_membership,
    require_role,
)
from app.embeddings.base import EmbeddingError
from app.models import (
    CreateDocumentRequest,
    DocumentCreatedResponse,
    DocumentDetail,
    DocumentSummary,
    PaginatedDocuments,
    RetrievalResponse,
    RetrievedChunkResponse,
)
from app.rag.base import VectorStore
from app.rag.service import RagService

router = APIRouter(prefix="/v1", tags=["Knowledge Base"])

# Module-level dependency singleton (avoids a call inside Depends()).
_require_owner_or_admin = require_role("owner", "admin")


def _summary(document: Document) -> DocumentSummary:
    return DocumentSummary(
        id=str(document.id),
        title=document.title,
        source=document.source,
        created_at=document.created_at.isoformat(),
    )


@router.post(
    "/orgs/{org_id}/documents",
    response_model=DocumentCreatedResponse,
    status_code=201,
    summary="Add a knowledge-base document",
    responses={
        502: {"description": "Embedding provider failure"},
        503: {"description": "Embeddings not configured / database required"},
    },
)
async def create_document(
    org_id: uuid.UUID,
    payload: CreateDocumentRequest,
    _membership: Membership = Depends(_require_owner_or_admin),
    service: RagService = Depends(get_rag_service),
) -> DocumentCreatedResponse:
    """Chunk, embed, and store a document for retrieval-augmented analysis."""
    try:
        document, chunk_count = await service.ingest(
            organization_id=org_id,
            title=payload.title,
            content=payload.content,
            source=payload.source,
        )
    except EmbeddingError as exc:
        raise HTTPException(status_code=502, detail="Failed to embed document") from exc
    return DocumentCreatedResponse(**_summary(document).model_dump(), chunk_count=chunk_count)


@router.get(
    "/orgs/{org_id}/documents",
    response_model=PaginatedDocuments,
    summary="List knowledge-base documents",
)
async def list_documents(
    org_id: uuid.UUID,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    _membership: Membership = Depends(require_org_membership),
    store: VectorStore = Depends(get_vector_store),
) -> PaginatedDocuments:
    items = await store.list_documents(org_id, limit=limit, offset=offset)
    total = await store.count_documents(org_id)
    return PaginatedDocuments(
        items=[_summary(d) for d in items], total=total, limit=limit, offset=offset
    )


@router.get(
    "/orgs/{org_id}/documents/search",
    response_model=RetrievalResponse,
    summary="Retrieve relevant knowledge-base chunks for a query",
    responses={503: {"description": "Embeddings not configured / database required"}},
)
async def search_documents(
    org_id: uuid.UUID,
    q: str = Query(..., min_length=1, max_length=5000),
    k: int = Query(default=4, ge=1, le=20),
    _membership: Membership = Depends(require_org_membership),
    service: RagService = Depends(get_rag_service),
) -> RetrievalResponse:
    """Embed the query and return the org's nearest KB chunks (ranked)."""
    results = await service.retrieve(organization_id=org_id, query=q, k=k)
    return RetrievalResponse(
        query=q,
        results=[
            RetrievedChunkResponse(document_id=str(r.document_id), content=r.content, score=r.score)
            for r in results
        ],
    )


@router.get(
    "/orgs/{org_id}/documents/{document_id}",
    response_model=DocumentDetail,
    summary="Get a knowledge-base document",
    responses={404: {"description": "Document not found in this organization"}},
)
async def get_document(
    org_id: uuid.UUID,
    document_id: uuid.UUID,
    _membership: Membership = Depends(require_org_membership),
    store: VectorStore = Depends(get_vector_store),
) -> DocumentDetail:
    document = await store.get_document(org_id, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")
    chunk_count = await store.count_chunks(org_id, document_id)
    return DocumentDetail(
        **_summary(document).model_dump(),
        content=document.content,
        chunk_count=chunk_count,
    )


@router.delete(
    "/orgs/{org_id}/documents/{document_id}",
    status_code=204,
    summary="Delete a knowledge-base document",
    responses={404: {"description": "Document not found in this organization"}},
)
async def delete_document(
    org_id: uuid.UUID,
    document_id: uuid.UUID,
    _membership: Membership = Depends(_require_owner_or_admin),
    store: VectorStore = Depends(get_vector_store),
) -> Response:
    if not await store.delete_document(org_id, document_id):
        raise HTTPException(status_code=404, detail="Document not found")
    return Response(status_code=204)
