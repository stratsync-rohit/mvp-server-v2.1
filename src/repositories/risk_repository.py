"""Persistence boundary for database-driven risks."""

from typing import Any

from src.repositories._base import MongoRepository, maybe_await


class RiskRepository(MongoRepository):
    """Load active risks from the shared application database."""

    collection_name = "risks"

    async def list_active(self) -> list[dict[str, Any]]:
        """Return active risks without exposing Mongo's internal ID."""
        cursor = self.collection.find({"is_active": True})
        if hasattr(cursor, "to_list"):
            documents = await maybe_await(cursor.to_list(length=None))
        elif hasattr(cursor, "__aiter__"):
            documents = [document async for document in cursor]
        else:
            documents = await maybe_await(cursor)

        return [self._without_mongo_id(document) for document in (documents or [])]

    async def get_by_risk_id(self, risk_id: str) -> dict[str, Any] | None:
        """Return one active risk without exposing Mongo's internal ID."""
        document = await maybe_await(self.collection.find_one({
            "risk_id": risk_id,
            "is_active": True,
        }))
        if document is None:
            return None
        return self._without_mongo_id(document)

    @staticmethod
    def _without_mongo_id(document: dict[str, Any]) -> dict[str, Any]:
        """Copy a persistence document while omitting Mongo's internal ID."""
        safe_document = dict(document)
        safe_document.pop("_id", None)
        return safe_document
