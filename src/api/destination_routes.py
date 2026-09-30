"""Destination resolution API."""

from fastapi import APIRouter, Request

from src.schemas.destination import (
    DestinationApiResponse,
    DestinationResolveRequest,
    DestinationResolveResponse,
)

router = APIRouter(tags=["destinations"])


@router.post("/api/destinations/resolve", response_model=DestinationResolveResponse)
async def resolve_destination(
    payload: DestinationResolveRequest, request: Request
) -> DestinationResolveResponse:
    """Resolve a trusted discovered channel into an outbound destination."""
    service = request.app.state.container.destination_service
    destination = await service.resolve_discovered_channel(
        payload.tenant_id, payload.team_id, payload.channel_id
    )
    return DestinationResolveResponse(
        success=True,
        data=DestinationApiResponse.model_validate(destination.model_dump()),
        error=None,
    )
