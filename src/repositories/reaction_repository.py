"""Persistence for notification reaction state."""

from typing import Any

from src.repositories._base import MongoRepository, maybe_await, utcnow


class ReactionRepository(MongoRepository):
    """Upsert add/remove state for a user reaction."""

    collection_name = "notification_reactions"

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
