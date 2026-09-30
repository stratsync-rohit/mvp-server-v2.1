"""Persistence for channels discovered through trusted Teams APIs."""

from typing import Any

from src.repositories._base import MongoRepository, maybe_await, utcnow
from src.schemas.teams import DiscoveredChannel


class DiscoveredChannelRepository(MongoRepository):
    """Upsert discovered channels using tenant/team/channel identity."""

    collection_name = "teams_discovered_channels"

    async def upsert(self, channel: DiscoveredChannel | dict[str, Any]) -> None:
        """Persist channel metadata without using conversation ID as identity."""
        data = channel.model_dump() if isinstance(channel, DiscoveredChannel) else dict(channel)
        now = utcnow()
        discovered_at = data.pop("discovered_at", None) or now
        data = {key: value for key, value in data.items() if value is not None}
        data["updated_at"] = now
        await maybe_await(self.collection.update_one(
            {key: data[key] for key in ("tenant_id", "team_id", "channel_id")},
            {"$set": data, "$setOnInsert": {"discovered_at": discovered_at}},
            upsert=True,
        ))

    async def get(self, tenant_id: str, team_id: str, channel_id: str) -> dict[str, Any] | None:
        """Fetch a channel by its logical identity."""
        return await maybe_await(self.collection.find_one({
            "tenant_id": tenant_id, "team_id": team_id, "channel_id": channel_id,
        }))

    async def list_for_team(self, tenant_id: str, team_id: str) -> list[dict[str, Any]]:
        """Fetch only channels belonging to one tenant-isolated team."""
        cursor = self.collection.find({"tenant_id": tenant_id, "team_id": team_id})
        if hasattr(cursor, "to_list"):
            return await cursor.to_list(length=None)
        if hasattr(cursor, "__aiter__"):
            return [document async for document in cursor]
        result = await maybe_await(cursor)
        return list(result or [])
