"""Persistence for Teams installation lifecycle state."""

from typing import Any

from src.repositories._base import MongoRepository, maybe_await, utcnow
from src.schemas.teams import TeamInstallation


class TeamInstallationRepository(MongoRepository):
    """Upsert and soft-delete Teams installations."""

    collection_name = "teams_installations"

    async def upsert(self, installation: TeamInstallation | dict[str, Any]) -> None:
        """Create or update an installation without deleting history."""
        data = installation.model_dump() if isinstance(installation, TeamInstallation) else dict(installation)
        now = utcnow()
        installed_at = data.pop("installed_at", None) or now
        data["updated_at"] = now
        data["is_active"] = True
        data["uninstalled_at"] = None
        await maybe_await(self.collection.update_one(
            {"tenant_id": data["tenant_id"], "team_id": data["team_id"]},
            {"$set": data, "$setOnInsert": {"installed_at": installed_at}},
            upsert=True,
        ))

    async def mark_inactive(self, tenant_id: str, team_id: str) -> None:
        """Mark an installation inactive while retaining its record."""
        now = utcnow()
        await maybe_await(self.collection.update_one(
            {"tenant_id": tenant_id, "team_id": team_id},
            {"$set": {"is_active": False, "uninstalled_at": now, "updated_at": now}},
        ))

    async def get(self, tenant_id: str, team_id: str) -> dict[str, Any] | None:
        """Fetch one tenant-isolated installation."""
        return await maybe_await(self.collection.find_one({"tenant_id": tenant_id, "team_id": team_id}))

    async def list_all(self) -> list[dict[str, Any]]:
        """Fetch all installation documents without exposing persistence objects."""
        cursor = self.collection.find({})
        if hasattr(cursor, "to_list"):
            return await cursor.to_list(length=None)
        if hasattr(cursor, "__aiter__"):
            return [document async for document in cursor]
        result = await maybe_await(cursor)
        return list(result or [])
