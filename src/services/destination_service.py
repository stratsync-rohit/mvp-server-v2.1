"""Outbound destination resolution."""

from __future__ import annotations

from typing import Any

from src.clients.teams_conversation_client import TeamsConversationClient
from src.exceptions import AppError
from src.repositories.discovered_channel_repository import DiscoveredChannelRepository
from src.repositories.destination_repository import DestinationRepository
from src.schemas.destination import Destination, build_destination_id


class DestinationService:
    """Resolve a provider route before persisting a destination."""

    def __init__(self, repository: DestinationRepository, conversation_client: TeamsConversationClient,
                 discovered_channel_repository: DiscoveredChannelRepository | None = None) -> None:
        self.repository = repository
        self.conversation_client = conversation_client
        self.discovered_channel_repository = discovered_channel_repository

    async def resolve_discovered_channel(self, tenant_id: str, team_id: str,
                                         channel_id: str) -> Destination:
        """Resolve one trusted discovered channel into an idempotent destination."""
        if self.discovered_channel_repository is None:
            raise AppError("DESTINATION_CONFIGURATION_ERROR", "Channel discovery is not configured.", 500)
        channel = await self.discovered_channel_repository.get(tenant_id, team_id, channel_id)
        if channel is None:
            raise AppError("DISCOVERED_CHANNEL_NOT_FOUND", "The Teams channel was not discovered.", 404)
        if not channel.get("available", True):
            raise AppError("DISCOVERED_CHANNEL_UNAVAILABLE", "The Teams channel is unavailable.", 409)

        reference = self.conversation_client.build_channel_reference(
            tenant_id=channel.get("tenant_id", ""),
            channel_id=channel.get("channel_id", ""),
            service_url=channel.get("service_url", ""),
        )
        if reference is None:
            raise AppError("DESTINATION_ROUTE_INVALID", "The discovered channel has incomplete routing metadata.", 422)
        resolved = await self.conversation_client.resolve_conversation(reference)
        if resolved is None:
            raise AppError("DESTINATION_ROUTE_INVALID", "The Teams channel route could not be prepared.", 502)

        destination = Destination(
            destination_id=build_destination_id(tenant_id, team_id, channel_id),
            tenant_id=tenant_id,
            team_id=team_id,
            channel_id=channel_id,
            team_name=channel.get("team_name"),
            channel_name=channel.get("channel_name"),
            conversation_id=resolved.get("conversation", {}).get("id"),
            conversation_reference=resolved,
            service_url=channel.get("service_url"),
            is_active=True,
        )
        await self.repository.upsert(destination)
        return destination

    async def resolve(self, route: dict[str, Any]) -> Destination | None:
        """Resolve and persist a destination only when routing metadata is valid."""
        required = ("tenant_id", "team_id", "channel_id")
        if any(not route.get(field) for field in required):
            return None
        reference = route.get("conversation_reference") or {
            "serviceUrl": route.get("service_url"),
            "conversation": {"id": route.get("conversation_id")},
            "channelId": "msteams",
        }
        resolved = await self.conversation_client.resolve_conversation(reference)
        if not resolved:
            return None
        data = dict(route)
        data["destination_id"] = build_destination_id(*(data[field] for field in required))
        data["conversation_reference"] = resolved
        data.setdefault("conversation_id", resolved.get("conversation", {}).get("id"))
        destination = Destination(**data)
        await self.repository.upsert(destination)
        return destination

    async def get(self, destination_id: str) -> Destination | None:
        """Load a previously resolved destination."""
        data = await self.repository.get(destination_id)
        return Destination(**data) if data else None
