"""Persistence for notification reaction state."""

from typing import Any

from src.repositories._base import MongoRepository, maybe_await, utcnow


class ReactionRepository(MongoRepository):
    """Upsert add/remove state for a user reaction."""

    collection_name = "notification_reactions"

    _READ_FIELDS = {
        "notification_id": 1,
        "reaction": 1,
        "user_aad_id": 1,
        "is_active": 1,
        "teams_message_id": 1,
        "created_at": 1,
        "updated_at": 1,
        "_id": 0,
    }

    async def set_state(self, reaction: dict[str, Any]) -> None:
        """Persist active or inactive reaction state."""
        data = dict(reaction)
        now = utcnow()
        data.pop("created_at", None)
        data["updated_at"] = now
        key = {field: data.get(field) for field in (
            "notification_id", "reaction", "user_aad_id"
        )}
        await maybe_await(self.collection.update_one(
            key,
            {"$set": data, "$setOnInsert": {"created_at": now}},
            upsert=True,
        ))

    async def list_by_notification_id(
        self, notification_id: str, *, include_inactive: bool = False
    ) -> list[dict[str, Any]]:
        """Return reaction state records for one notification."""
        query: dict[str, Any] = {"notification_id": notification_id}
        if not include_inactive:
            query["is_active"] = True
        return await self._find_many(query)

    async def list_active_for_notification_ids(
        self, notification_ids: list[str]
    ) -> list[dict[str, Any]]:
        """Return active reaction states for a notification page in one query."""
        if not notification_ids:
            return []
        return await self._find_many({
            "notification_id": {"$in": notification_ids},
            "is_active": True,
        })

    async def _find_many(self, query: dict[str, Any]) -> list[dict[str, Any]]:
        try:
            cursor = self.collection.find(query, self._READ_FIELDS)
        except TypeError:
            cursor = self.collection.find(query)
        cursor = await maybe_await(cursor)
        return await self._collect(cursor)

    @staticmethod
    async def _collect(cursor: Any) -> list[dict[str, Any]]:
        if hasattr(cursor, "to_list"):
            return list(await maybe_await(cursor.to_list(length=None)))
        if hasattr(cursor, "__aiter__"):
            return [document async for document in cursor]
        return list(cursor)
