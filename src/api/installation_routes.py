"""Read-only Teams installation API."""

from fastapi import APIRouter, Request

from src.schemas.installation import InstallationsResponse

router = APIRouter(tags=["installations"])


@router.get("/api/installations", response_model=InstallationsResponse)
async def installations(request: Request) -> InstallationsResponse:
    """Return safe installation metadata and tenant/team-matched channels."""
    service = request.app.state.container.installation_service
    data = await service.list_installations()
    return InstallationsResponse(success=True, data=data, error=None)
