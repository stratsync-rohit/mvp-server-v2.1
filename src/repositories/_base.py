"""Small helpers shared by async Mongo repositories."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from src.exceptions import PersistenceError


def utcnow() -> datetime:
    """Return a timezone-aware UTC timestamp."""
    return datetime.now(timezone.utc)


async def maybe_await(value: Any) -> Any:
    """Await Motor results while also supporting simple test doubles."""
    if hasattr(value, "__await__"):
        return await value
    return value


class MongoRepository:
    """Base class allowing an injected collection or Mongo manager."""

    collection_name = ""

    def __init__(self, mongo: Any | None = None, collection: Any | None = None) -> None:
        self.mongo = mongo
        self._collection = collection

    @property
    def collection(self) -> Any:
        """Resolve the collection lazily so composition does not perform I/O."""
        if self._collection is not None:
            return self._collection
        if self.mongo is None:
            raise PersistenceError("A Mongo manager or collection is required")
        return self.mongo.collection(self.collection_name)
