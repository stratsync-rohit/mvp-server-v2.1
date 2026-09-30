"""Internal notification card construction and delivery."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from src.clients.teams_conversation_client import TeamsConversationClient
from src.exceptions import AppError
from src.repositories.notification_repository import NotificationRepository
from src.repositories.reaction_repository import ReactionRepository
from src.schemas.destination import build_destination_id
from src.schemas.notification import (
    NotificationDetail,
    NotificationListItem,
    ReactionSummary,
)
from src.schemas.reaction import NotificationReactionsData, ReactionReadItem
from src.schemas.teams import TeamsContext
from src.services.destination_service import DestinationService


class NotificationService:
    """Send cards to exact resolved destinations and persist send state."""

    def __init__(self, repository: NotificationRepository, destination_service: DestinationService,
                 conversation_client: TeamsConversationClient,
                 reaction_repository: ReactionRepository | None = None) -> None:
        self.repository = repository
        self.destination_service = destination_service
        self.conversation_client = conversation_client
        self.reaction_repository = reaction_repository

    async def list_notifications(
        self,
        *,
        risk_id: str | None = None,
        destination_id: str | None = None,
        status: str | None = None,
        notification_type: str | None = None,
        view_type: str | None = None,
        limit: int = 50,
    ) -> list[NotificationListItem]:
        """Load safe notification metadata and batch its active reactions."""
        if status is not None and status not in {"pending", "sent", "failed"}:
            raise AppError("NOTIFICATION_STATUS_INVALID", "status is not supported.", 422)
        documents = await self.repository.list(
            risk_id=self._filter_value(risk_id, "risk_id"),
            destination_id=self._filter_value(destination_id, "destination_id"),
            status=status,
            notification_type=self._filter_value(notification_type, "notification_type"),
            view_type=self._filter_value(view_type, "view_type"),
            limit=limit,
        )
        summaries = await self._summaries([document.get("notification_id") for document in documents])
        return [
            NotificationListItem.model_validate({
                **document,
                "reaction_summary": summaries.get(document.get("notification_id"), ReactionSummary()),
            })
            for document in documents
        ]

    async def get_notification(self, notification_id: str) -> NotificationDetail:
        """Load one safe notification or raise a public 404."""
        normalized_id = notification_id.strip() if isinstance(notification_id, str) else ""
        if not normalized_id:
            raise AppError("NOTIFICATION_NOT_FOUND", "The notification was not found.", 404)
        document = await self.repository.get_by_notification_id(normalized_id)
        if document is None:
            raise AppError("NOTIFICATION_NOT_FOUND", "The notification was not found.", 404)
        summaries = await self._summaries([normalized_id])
        return NotificationDetail.model_validate({
            **document,
            "reaction_summary": summaries.get(normalized_id, ReactionSummary()),
        })

    async def get_reactions(
        self, notification_id: str, *, include_inactive: bool = False
    ) -> NotificationReactionsData:
        """Load reaction states, with an active-only summary."""
        notification = await self.get_notification(notification_id)
        records = []
        if self.reaction_repository is not None:
            records = await self.reaction_repository.list_by_notification_id(
                notification.notification_id, include_inactive=include_inactive
            )
        if not include_inactive:
            records = [record for record in records if record.get("is_active") is True]
        return NotificationReactionsData(
            notification_id=notification.notification_id,
            summary=notification.reaction_summary,
            reactions=[ReactionReadItem.model_validate(record) for record in records],
        )

    async def _summaries(self, notification_ids: list[str | None]) -> dict[str, ReactionSummary]:
        ids = [notification_id for notification_id in notification_ids if notification_id]
        if self.reaction_repository is None or not ids:
            return {}
        records = await self.reaction_repository.list_active_for_notification_ids(ids)
        summaries = {notification_id: ReactionSummary() for notification_id in ids}
        for record in records:
            if record.get("is_active") is not True:
                continue
            notification_id = record.get("notification_id")
            reaction = record.get("reaction")
            if notification_id not in summaries or not reaction:
                continue
            summary = summaries[notification_id]
            summary.counts[reaction] = summary.counts.get(reaction, 0) + 1
            summary.total += 1
        return summaries

    @staticmethod
    def _filter_value(value: str | None, field: str) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise AppError("NOTIFICATION_FILTER_INVALID", f"{field} must not be blank.", 422)
        return normalized

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
