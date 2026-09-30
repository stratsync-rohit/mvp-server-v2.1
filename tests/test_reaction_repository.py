"""Regression tests for reaction timestamp preservation."""

from datetime import datetime, timezone

import pytest

from src.repositories.reaction_repository import ReactionRepository


class ReactionCollection:
    """Small Mongo update double that applies $setOnInsert only on insert."""

    def __init__(self):
        self.documents = {}
        self.updates = []

    async def update_one(self, query, update, upsert=False):
        self.updates.append(update)
        key = tuple(sorted(query.items()))
        if key not in self.documents and upsert:
            self.documents[key] = dict(update.get("$setOnInsert", {}))
        self.documents[key].update(update.get("$set", {}))


@pytest.mark.asyncio
async def test_reaction_state_transitions_preserve_created_at(monkeypatch):
    timestamps = iter(
        datetime(2026, 1, day, 12, tzinfo=timezone.utc) for day in (1, 2, 3)
    )
    monkeypatch.setattr("src.repositories.reaction_repository.utcnow", lambda: next(timestamps))

    collection = ReactionCollection()
    repository = ReactionRepository(collection=collection)
    reaction = {
        "notification_id": "notification-1",
        "reaction": "like",
        "user_aad_id": "user-1",
        "teams_message_id": "message-1",
        "is_active": True,
    }

    await repository.set_state(reaction)
    first = next(iter(collection.documents.values())).copy()
    await repository.set_state({**reaction, "is_active": False})
    second = next(iter(collection.documents.values())).copy()
    await repository.set_state({**reaction, "is_active": True})
    third = next(iter(collection.documents.values())).copy()

    assert len(collection.documents) == 1
    assert first["created_at"] == datetime(2026, 1, 1, 12, tzinfo=timezone.utc)
    assert first["updated_at"] == first["created_at"]
    assert second["created_at"] == first["created_at"]
    assert second["updated_at"] == datetime(2026, 1, 2, 12, tzinfo=timezone.utc)
    assert second["is_active"] is False
    assert third["created_at"] == first["created_at"]
    assert third["updated_at"] == datetime(2026, 1, 3, 12, tzinfo=timezone.utc)
    assert third["is_active"] is True

    first_update, second_update, third_update = collection.updates
    assert "created_at" not in first_update["$set"]
    assert "created_at" not in second_update["$set"]
    assert "created_at" not in third_update["$set"]
    assert first_update["$setOnInsert"]["created_at"] == first["created_at"]
    assert first_update["$set"]["updated_at"] == first["updated_at"]
