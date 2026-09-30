"""Persistence for notification send state."""

from typing import Any

from src.repositories._base import MongoRepository, maybe_await, utcnow


class NotificationRepository(MongoRepository):
    """Persist pending, sent, and failed notifications."""

    collection_name = "notifications"

    async def create(self, notification: dict[str, Any]) -> None:
        """Insert a pending notification record."""
        data = dict(notification)
        now = utcnow()
        data.setdefault("created_at", now)
        data["updated_at"] = now
        await maybe_await(self.collection.insert_one(data))

    async def mark_sent(self, notification_id: str, teams_message_id: str | None) -> None:
        """Record successful provider delivery."""
        await self._mark(notification_id, "sent", teams_message_id=teams_message_id, error=None)

    async def mark_failed(self, notification_id: str, error: str) -> None:
        """Record a failed delivery without hiding the retryable failure."""
        await self._mark(notification_id, "failed", error=error)

    async def _mark(self, notification_id: str, status: str, **values: Any) -> None:
        values.update({"status": status, "updated_at": utcnow()})
        await maybe_await(self.collection.update_one(
            {"notification_id": notification_id}, {"$set": values}
        ))

    async def get_by_message_id(self, teams_message_id: str, tenant_id: str | None = None) -> dict[str, Any] | None:
        """Resolve a notification from a tenant-scoped Teams message ID."""
        query: dict[str, Any] = {"teams_message_id": teams_message_id}
        if tenant_id:
            query["tenant_id"] = tenant_id
        return await maybe_await(self.collection.find_one(query))
