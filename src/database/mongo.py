"""Async MongoDB lifecycle management."""

from __future__ import annotations

import logging
from typing import Any

from src.config.settings import Settings
from src.exceptions import PersistenceError

logger = logging.getLogger(__name__)

try:  # Motor is optional for dependency-free unit tests and disabled local runs.
    from motor.motor_asyncio import AsyncIOMotorClient
except ImportError:  # pragma: no cover - exercised only without installed extras.
    AsyncIOMotorClient = None  # type: ignore[assignment,misc]


class MongoManager:
    """Own one async Mongo client and its application database."""

    def __init__(self, settings: Settings, client: Any | None = None) -> None:
        self.settings = settings
        self.client = client
        self.database: Any | None = None

    @property
    def enabled(self) -> bool:
        """Whether MongoDB was configured for this process."""
        return bool(self.settings.mongodb_url)

    async def start(self) -> None:
        """Create the client and database handle without forcing a network call."""
        if not self.enabled:
            return
        if self.client is None:
            if AsyncIOMotorClient is None:
                raise PersistenceError("motor is required when MONGODB_URL is configured")
            self.client = AsyncIOMotorClient(
                self.settings.mongodb_url,
                serverSelectionTimeoutMS=self.settings.mongodb_server_selection_timeout_ms,
            )
        self.database = self.client[self.settings.mongodb_database]
        await self.ensure_indexes()

    async def close(self) -> None:
        """Close the client safely during application shutdown."""
        if self.client is not None and hasattr(self.client, "close"):
            self.client.close()
        self.client = None
        self.database = None

    async def ping(self) -> bool:
        """Return whether MongoDB is reachable, or true for disabled local mode."""
        if not self.enabled:
            return True
        if self.client is None:
            await self.start()
        try:
            await self.client.admin.command("ping")
            return True
        except Exception:
            logger.warning("mongodb_ping_failed", exc_info=True)
            return False

    def collection(self, name: str) -> Any:
        """Return a named collection from the configured application database."""
        if self.database is None:
            raise PersistenceError("MongoManager has not been started")
        return self.database[name]

    async def ensure_indexes(self) -> None:
        """Create only application indexes; existing data is preserved."""
        if self.database is None:
            return
        indexes = {
            "teams_installations": [[("tenant_id", 1), ("team_id", 1)]],
            "teams_discovered_channels": [[("tenant_id", 1), ("team_id", 1), ("channel_id", 1)]],
            "destinations": [[("destination_id", 1)], [("tenant_id", 1), ("team_id", 1), ("channel_id", 1)]],
            "notifications": [[("teams_message_id", 1)], [("destination_id", 1), ("created_at", -1)]],
            "notification_reactions": [[("notification_id", 1), ("reaction", 1), ("user_aad_id", 1)]],
            "processed_activities": [[("activity_id", 1)]],
        }
        for collection_name, collection_indexes in indexes.items():
            collection = self.database[collection_name]
            for index in collection_indexes:
                unique = collection_name in {
                    "teams_installations", "teams_discovered_channels", "destinations", "processed_activities"
                }
                try:
                    await collection.create_index(index, background=True, unique=unique)
                except Exception as exc:
                    # Existing deployments may have the same key pattern with
                    # older options. Never drop/rebuild an index during startup;
                    # preserving the volume is safer than destructive migration.
                    if getattr(exc, "code", None) in {85, 86, 11000}:
                        logger.warning(
                            "mongodb_index_preserved",
                            extra={"collection": collection_name},
                        )
                        continue
                    raise
