"""Persistence boundary for database-driven risks."""

from typing import Any

from src.repositories._base import MongoRepository, maybe_await


class RiskRepository(MongoRepository):
    """Load active risks from the shared application database."""

    collection_name = "risks"

    async def get_by_risk_id(self, risk_id: str) -> dict[str, Any] | None:
        """Return one active risk without exposing Mongo's internal ID."""
        document = await maybe_await(self.collection.find_one({
            "risk_id": risk_id,
            "is_active": True,
        }))
        if document is None:
            return None
        safe_document = dict(document)
        safe_document.pop("_id", None)
        return safe_document
