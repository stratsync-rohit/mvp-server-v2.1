"""Notification send and safe read APIs."""

from fastapi import APIRouter, Query, Request

from src.schemas.notification import (
    NotificationDetailResponse,
    NotificationListResponse,
    NotificationSendRequest,
    NotificationSendResponse,
    NotificationSendResponseData,
)
from src.schemas.reaction import NotificationReactionsResponse

router = APIRouter(tags=["notifications"])


@router.post("/api/notifications/send", response_model=NotificationSendResponse)
async def send_notification(
    payload: NotificationSendRequest, request: Request
) -> NotificationSendResponse:
    """Send one Adaptive Card through a previously resolved destination."""
    container = request.app.state.container
    risk = await container.risk_service.get(payload.risk_id)
    card = container.risk_card_renderer.render_notification(risk)
    notification_id = await container.notification_service.send(
        payload.destination_id, card, risk_id=payload.risk_id
    )
    return NotificationSendResponse(
        success=True,
        data=NotificationSendResponseData(
            notification_id=notification_id,
            destination_id=payload.destination_id,
            status="sent",
        ),
        error=None,
    )


@router.get("/api/notifications", response_model=NotificationListResponse)
async def list_notifications(
    request: Request,
    risk_id: str | None = Query(default=None),
    destination_id: str | None = Query(default=None),
    status: str | None = Query(default=None),
    notification_type: str | None = Query(default=None),
    view_type: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
) -> NotificationListResponse:
    """Return safe notifications newest first with active reaction summaries."""
    service = request.app.state.container.notification_service
    data = await service.list_notifications(
        risk_id=risk_id,
        destination_id=destination_id,
        status=status,
        notification_type=notification_type,
        view_type=view_type,
        limit=limit,
    )
    return NotificationListResponse(success=True, data=data, error=None)


@router.get(
    "/api/notifications/{notification_id}/reactions",
    response_model=NotificationReactionsResponse,
)
async def notification_reactions(
    notification_id: str,
    request: Request,
    include_inactive: bool = Query(default=False),
) -> NotificationReactionsResponse:
    """Return reaction state for one notification."""
    service = request.app.state.container.notification_service
    data = await service.get_reactions(
        notification_id, include_inactive=include_inactive
    )
    return NotificationReactionsResponse(success=True, data=data, error=None)


@router.get(
    "/api/notifications/{notification_id}",
    response_model=NotificationDetailResponse,
)
async def notification_detail(
    notification_id: str, request: Request
) -> NotificationDetailResponse:
    """Return safe metadata for one notification."""
    service = request.app.state.container.notification_service
    data = await service.get_notification(notification_id)
    return NotificationDetailResponse(success=True, data=data, error=None)
