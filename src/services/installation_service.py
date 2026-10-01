"""Installation lifecycle business logic."""

from __future__ import annotations

from typing import Any

from src.repositories.team_installation_repository import TeamInstallationRepository
from src.repositories.discovered_channel_repository import DiscoveredChannelRepository
from src.schemas.installation import DiscoveredChannelResponse, InstallationResponse
from src.schemas.teams import TeamInstallation, TeamsContext
from src.services.teams_service import TeamsService


class InstallationService:
    """Persist authenticated installation events and trigger discovery."""

    def __init__(self, repository: TeamInstallationRepository, teams_service: TeamsService,
                 channel_repository: DiscoveredChannelRepository | None = None) -> None:
        self.repository = repository
        self.teams_service = teams_service
        self.channel_repository = channel_repository

    async def list_installations(self) -> list[InstallationResponse]:
        """Aggregate safe installation DTOs with tenant/team-matched channels."""
        installations = await self.repository.list_active()
        results: list[InstallationResponse] = []
        for installation in installations:
            tenant_id = installation.get("tenant_id")
            team_id = installation.get("team_id")
            if not tenant_id or not team_id:
                continue
            channel_documents = []
            if self.channel_repository is not None:
                channel_documents = await self.channel_repository.list_for_team(
                    tenant_id, team_id
                )
            channels = [DiscoveredChannelResponse(
                channel_id=channel["channel_id"],
                channel_name=channel.get("channel_name"),
                team_id=channel["team_id"],
                team_name=channel.get("team_name"),
                tenant_id=channel["tenant_id"],
                conversation_id=channel.get("conversation_id"),
                service_url=channel.get("service_url"),
                available=channel.get("available", True),
                discovered_at=channel.get("discovered_at"),
                updated_at=channel.get("updated_at"),
            ) for channel in channel_documents]
            results.append(InstallationResponse(
                tenant_id=tenant_id,
                team_id=team_id,
                team_name=installation.get("team_name"),
                conversation_id=installation.get("conversation_id"),
                service_url=installation.get("service_url"),
                is_active=installation.get("is_active", True),
                installed_at=installation.get("installed_at"),
                updated_at=installation.get("updated_at"),
                uninstalled_at=installation.get("uninstalled_at"),
                channels=channels,
            ))
        return results

    async def add(self, turn_context: Any) -> None:
        """Upsert installation metadata, then discover its channels."""
        context = TeamsContext.from_activity(turn_context.activity)
        if not context.tenant_id or not context.team_id:
            return
        await self.repository.upsert(TeamInstallation(
            tenant_id=context.tenant_id,
            team_id=context.team_id,
            team_name=context.team_name,
            conversation_id=context.conversation_id,
            conversation_type=context.conversation_type,
            service_url=context.service_url,
            bot_id=context.recipient_id,
        ))
        await self.teams_service.discover_channels(turn_context, context)

    async def remove(self, turn_context: Any) -> None:
        """Soft-deactivate an installation from an authenticated activity."""
        context = TeamsContext.from_activity(turn_context.activity)
        if context.tenant_id and context.team_id:
            await self.repository.mark_inactive(context.tenant_id, context.team_id)
