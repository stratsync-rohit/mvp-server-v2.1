"""Persistence for notification send state."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from src.repositories._base import MongoRepository, maybe_await, utcnow


class NotificationRepository(MongoRepository):
    """Persist pending, sent, and failed notifications."""

    collection_name = "notifications"

    _READ_FIELDS = {
        "notification_id": 1,
        "destination_id": 1,
        "risk_id": 1,
        "tenant_id": 1,
        "team_id": 1,
        "channel_id": 1,
        "notification_type": 1,
        "view_type": 1,
        "status": 1,
        "teams_message_id": 1,
        "created_at": 1,
        "updated_at": 1,
        "_id": 0,
    }

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

    async def list(
        self,
        *,
        risk_id: str | None = None,
        destination_id: str | None = None,
        status: str | None = None,
        notification_type: str | None = None,
        view_type: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Return safe notification fields newest first."""
        query: dict[str, Any] = {}
        for field, value in (
            ("risk_id", risk_id),
            ("destination_id", destination_id),
            ("status", status),
            ("notification_type", notification_type),
            ("view_type", view_type),
        ):
            if value is not None:
                query[field] = value

        try:
            cursor = self.collection.find(query, self._READ_FIELDS)
        except TypeError:
            # Keep small repository doubles useful when they only accept query.
            cursor = self.collection.find(query)
        cursor = await maybe_await(cursor)
        cursor_sortable = not isinstance(cursor, list) and hasattr(cursor, "sort")
        if cursor_sortable:
            cursor = cursor.sort("created_at", -1)
        if hasattr(cursor, "limit"):
            cursor = cursor.limit(limit)
        cursor = await maybe_await(cursor)
        documents = await self._collect(cursor)
        if not cursor_sortable:
            documents.sort(key=lambda item: self._sort_timestamp(item.get("created_at")), reverse=True)
        return documents[:limit]

    async def get_by_notification_id(self, notification_id: str) -> dict[str, Any] | None:
        """Return one notification using only frontend-safe fields."""
        query = {"notification_id": notification_id}
        try:
            document = self.collection.find_one(query, self._READ_FIELDS)
        except TypeError:
            document = self.collection.find_one(query)
        document = await maybe_await(document)
        if document is None:
            return None
        return {field: document[field] for field in self._READ_FIELDS if field != "_id" and field in document}

    @staticmethod
    async def _collect(cursor: Any) -> list[dict[str, Any]]:
        if hasattr(cursor, "to_list"):
            return list(await maybe_await(cursor.to_list(length=None)))
        if hasattr(cursor, "__aiter__"):
            return [document async for document in cursor]
        return list(cursor)

    @staticmethod
    def _sort_timestamp(value: Any) -> float:
        if isinstance(value, datetime):
            return value.timestamp()
        return float("-inf")
