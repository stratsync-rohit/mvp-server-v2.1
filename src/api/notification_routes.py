"""Controlled notification send API."""

from fastapi import APIRouter, Request

from src.schemas.notification import (
    NotificationSendRequest,
    NotificationSendResponse,
    NotificationSendResponseData,
)

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
