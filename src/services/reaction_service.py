"""Reaction lifecycle handling."""

from __future__ import annotations

from typing import Any

from src.repositories.notification_repository import NotificationRepository
from src.repositories.reaction_repository import ReactionRepository
from src.schemas.teams import TeamsContext


class ReactionService:
    """Resolve reactions by Teams message ID and persist add/remove state."""

    def __init__(self, repository: ReactionRepository, notification_repository: NotificationRepository) -> None:
        self.repository = repository
        self.notification_repository = notification_repository

    async def handle(self, turn_context: Any) -> None:
        """Handle both added and removed reactions from one activity."""
        activity = turn_context.activity
        data = activity.serialize() if hasattr(activity, "serialize") else vars(activity)
        message_id = data.get("replyToId") or data.get("reply_to_id") or data.get("id")
        if not message_id:
            return
        context = TeamsContext.from_activity(activity)
        notification = await self.notification_repository.get_by_message_id(
            message_id, context.tenant_id
        )
        if not notification:
            return
        sender = data.get("from") or data.get("from_property") or {}
        user_id = sender.get("aadObjectId") or sender.get("id")
        for key, active in (("reactionsAdded", True), ("reactionsRemoved", False)):
            for reaction in data.get(key) or []:
                reaction_name = reaction.get("type") if isinstance(reaction, dict) else getattr(reaction, "type", None)
                if not reaction_name:
                    continue
                await self.repository.set_state({
                    "notification_id": notification["notification_id"],
                    "destination_id": notification.get("destination_id"),
                    "tenant_id": context.tenant_id or notification.get("tenant_id", ""),
                    "teams_message_id": message_id, "user_aad_id": user_id,
                    "reaction": reaction_name, "is_active": active,
                })
