"""Retry-safe activity claim state."""

from datetime import timedelta
from typing import Any

from src.repositories._base import MongoRepository, maybe_await, utcnow

try:
    from pymongo import ReturnDocument
except ImportError:  # pragma: no cover
    ReturnDocument = type("ReturnDocument", (), {"AFTER": True})


class ProcessedActivityRepository(MongoRepository):
    """Claim activities atomically and complete them only after successful handling."""

    collection_name = "processed_activities"

    async def claim(self, activity_id: str, activity_type: str | None = None, *, stale_after_seconds: int = 300) -> bool:
        """Claim a new/stale/failed activity; completed or live claims are skipped."""
        now = utcnow()
        eligible = {"activity_id": activity_id, "$or": [
            {"status": {"$exists": False}},
            {"status": "failed"},
            {"status": "processing", "claimed_at": {"$lt": now - timedelta(seconds=stale_after_seconds)}},
        ]}
        # Motor's conditional find-and-update makes the claim one atomic
        # operation, so concurrent webhook retries cannot both execute.
        atomic_claim = getattr(self.collection, "find_one_and_update", None)
        if atomic_claim is not None:
            try:
                result = await maybe_await(atomic_claim(
                    eligible,
                    {"$set": {"activity_id": activity_id, "activity_type": activity_type,
                              "status": "processing", "claimed_at": now, "updated_at": now},
                     "$setOnInsert": {"created_at": now}},
                    upsert=True,
                    return_document=ReturnDocument.AFTER,
                ))
                return result is not None
            except Exception as exc:
                # Duplicate-key means another worker inserted the same activity
                # between the filter and upsert; it owns the claim.
                if exc.__class__.__name__ == "DuplicateKeyError":
                    return False
                raise

        # Small in-memory test doubles may not implement find_one_and_update.
        existing = await maybe_await(self.collection.find_one({"activity_id": activity_id}))
        if existing and existing.get("status") == "completed":
            return False
        if existing and existing.get("status") == "processing":
            claimed_at = existing.get("claimed_at")
            if claimed_at and now - claimed_at < timedelta(seconds=stale_after_seconds):
                return False
        result = await maybe_await(self.collection.update_one(
            {"activity_id": activity_id},
            {"$set": {"activity_id": activity_id, "activity_type": activity_type,
                      "status": "processing", "claimed_at": now, "updated_at": now},
             "$setOnInsert": {"created_at": now}},
            upsert=True,
        ))
        return bool(getattr(result, "acknowledged", True))

    async def mark_completed(self, activity_id: str) -> None:
        """Mark an activity complete after all handler work succeeds."""
        await maybe_await(self.collection.update_one(
            {"activity_id": activity_id}, {"$set": {"status": "completed", "updated_at": utcnow()}}
        ))

    async def mark_failed(self, activity_id: str, error: str) -> None:
        """Keep failure state visible and eligible for a future retry."""
        await maybe_await(self.collection.update_one(
            {"activity_id": activity_id},
            {"$set": {"status": "failed", "error": error, "updated_at": utcnow()}},
        ))
