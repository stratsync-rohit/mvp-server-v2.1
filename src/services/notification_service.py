"""Internal notification card construction and delivery."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from src.clients.teams_conversation_client import TeamsConversationClient
from src.exceptions import AppError
from src.repositories.notification_repository import NotificationRepository
from src.schemas.destination import build_destination_id
from src.schemas.teams import TeamsContext
from src.services.destination_service import DestinationService


class NotificationService:
    """Send cards to exact resolved destinations and persist send state."""

    def __init__(self, repository: NotificationRepository, destination_service: DestinationService,
                 conversation_client: TeamsConversationClient) -> None:
        self.repository = repository
        self.destination_service = destination_service
        self.conversation_client = conversation_client

    async def send(self, destination_id: str, card: dict[str, Any], *, risk_id: str | None = None) -> str:
        """Persist pending state, send the card, and finalize send state."""
        destination = await self.destination_service.get(destination_id)
        if destination is None:
            raise AppError("DESTINATION_NOT_FOUND", "The destination was not found.", 404)
        if not destination.is_active or not destination.conversation_reference:
            raise AppError("DESTINATION_UNAVAILABLE", "The destination is not available for sending.", 409)
        notification_id = str(uuid4())
        await self.repository.create({"notification_id": notification_id,
                                      "destination_id": destination_id, "risk_id": risk_id,
                                      "tenant_id": destination.tenant_id,
                                      "team_id": destination.team_id,
                                      "channel_id": destination.channel_id,
                                      "card": card, "status": "pending"})
        try:
            result = await self.conversation_client.send_activity(destination.conversation_reference, card)
            message_id = self._message_id(result)
            await self.repository.mark_sent(notification_id, message_id)
            return notification_id
        except Exception as exc:
            await self.repository.mark_failed(notification_id, self._safe_error(exc))
            raise

    async def send_in_context(
        self,
        turn_context: Any,
        card: dict[str, Any],
        *,
        risk_id: str,
        view_type: str,
    ) -> str:
        """Persist and send one risk-view card in the authenticated channel."""
        if view_type not in {"details", "mitigation"}:
            raise AppError("RISK_VIEW_INVALID", "The requested risk view is not supported.", 400)
        normalized_risk_id = risk_id.strip() if isinstance(risk_id, str) else ""
        if not normalized_risk_id:
            raise AppError("RISK_ID_INVALID", "risk_id must be a non-empty string.", 422)

        context = TeamsContext.from_activity(turn_context.activity)
        if not context.tenant_id or not context.team_id or not context.channel_id:
            raise AppError(
                "RISK_VIEW_CONTEXT_INVALID",
                "The Teams activity has incomplete channel context.",
                422,
            )
        destination_id = build_destination_id(
            context.tenant_id, context.team_id, context.channel_id
        )
        notification_id = str(uuid4())
        await self.repository.create({
            "notification_id": notification_id,
            "destination_id": destination_id,
            "risk_id": normalized_risk_id,
            "tenant_id": context.tenant_id,
            "team_id": context.team_id,
            "channel_id": context.channel_id,
            "notification_type": "risk_view",
            "view_type": view_type,
            "card": card,
            "status": "pending",
        })
        try:
            result = await self.conversation_client.send_card_in_context(turn_context, card)
            await self.repository.mark_sent(notification_id, self._message_id(result))
            return notification_id
        except Exception as exc:
            await self.repository.mark_failed(notification_id, self._safe_error(exc))
            raise

    @staticmethod
    def _message_id(result: Any) -> str | None:
        """Extract only a real provider response ID when one is returned."""
        message_id = getattr(result, "id", None)
        if message_id is None and isinstance(result, dict):
            message_id = result.get("id")
        return message_id

    @staticmethod
    def _safe_error(exc: Exception) -> str:
        """Persist an error class without provider secrets or raw credentials."""
        return f"{type(exc).__name__}: outbound notification failed"
