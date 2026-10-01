"""Team channel discovery business logic."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from src.clients.teams_client import TeamsClient
from src.repositories.discovered_channel_repository import DiscoveredChannelRepository
from src.repositories.team_installation_repository import TeamInstallationRepository
from src.schemas.teams import DiscoveredChannel, TeamsContext, _as_mapping

logger = logging.getLogger(__name__)


def _value(item: Any, *names: str) -> Any:
    """Read a field from an SDK object or mapping."""
    for name in names:
        if isinstance(item, Mapping) and name in item:
            return item[name]
        if hasattr(item, name):
            return getattr(item, name)
    return None


def _resolve_channel_name(channel: Any, channel_id: str, team_id: str) -> str | None:
    """Resolve SDK channel name variants and the Teams General-channel fallback."""
    value = _value(channel, "name", "display_name", "displayName")
    channel_name = value.strip() if isinstance(value, str) else None
    if not channel_name and channel_id == team_id:
        return "General"
    return channel_name or None


class TeamsService:
    """Discover and persist channels through the Teams client boundary."""

    def __init__(self, client: TeamsClient, channel_repository: DiscoveredChannelRepository,
                 installation_repository: TeamInstallationRepository | None = None) -> None:
        self.client = client
        self.channel_repository = channel_repository
        self.installation_repository = installation_repository

    async def _resolve_team_name(self, context: TeamsContext) -> str | None:
        """Resolve a missing team name from the persisted installation context."""
        if isinstance(context.team_name, str) and context.team_name.strip():
            return context.team_name
        if self.installation_repository is None or not context.tenant_id or not context.team_id:
            return None
        installation = await self.installation_repository.get(context.tenant_id, context.team_id)
        team_name = installation.get("team_name") if installation else None
        return team_name if isinstance(team_name, str) and team_name.strip() else None

    async def discover_channels(self, turn_context: Any, context: TeamsContext) -> list[DiscoveredChannel]:
        """Discover every channel and upsert by tenant/team/channel identity."""
        if not context.tenant_id or not context.team_id:
            return []
        team_name = await self._resolve_team_name(context)
        logger.info(
            "teams_channel_discovery_started",
            extra={
                "tenant_id": context.tenant_id,
                "team_id": context.team_id,
            },
        )
        channels = await self.client.get_team_channels(turn_context, context.team_id)
        channels = channels or []
        logger.info(
            "teams_channel_discovery_completed",
            extra={
                "tenant_id": context.tenant_id,
                "team_id": context.team_id,
                "channel_count": len(channels),
            },
        )
        discovered: list[DiscoveredChannel] = []
        for channel in channels:
            channel_id = _value(channel, "id")
            if not channel_id:
                continue
            channel_name = _resolve_channel_name(channel, channel_id, context.team_id)
            logger.info(
                "teams_channel_discovered",
                extra={
                    "tenant_id": context.tenant_id,
                    "team_id": context.team_id,
                    "channel_id": channel_id,
                    "channel_name": channel_name,
                },
            )
            model = DiscoveredChannel(
                tenant_id=context.tenant_id,
                team_id=context.team_id,
                channel_id=channel_id,
                team_name=team_name,
                channel_name=channel_name,
                conversation_id=context.conversation_id,
                service_url=context.service_url,
                available=True,
            )
            await self.channel_repository.upsert(model)
            discovered.append(model)
        return discovered

    async def register_channel_from_activity(
        self, turn_context: Any
    ) -> DiscoveredChannel | None:
        """Register one channel from a genuine channel-scoped activity."""
        activity = turn_context.activity
        activity_data = _as_mapping(activity)
        activity_type = activity_data.get("type") or getattr(activity, "type", None)
        context = TeamsContext.from_activity(activity)
        channel_data = _as_mapping(
            activity_data.get("channelData") or activity_data.get("channel_data")
        )
        channel_is_scoped = (
            bool(channel_data.get("channel"))
            and isinstance(context.conversation_type, str)
            and context.conversation_type.lower() == "channel"
        )
        if (
            activity_type == "installationUpdate"
            or not channel_is_scoped
            or not context.tenant_id
            or not context.team_id
            or not context.channel_id
        ):
            return None

        team_name = await self._resolve_team_name(context)
        channel_name = _resolve_channel_name(
            {"name": context.channel_name}, context.channel_id, context.team_id
        )
        channel = DiscoveredChannel(
            tenant_id=context.tenant_id,
            team_id=context.team_id,
            channel_id=context.channel_id,
            team_name=team_name,
            channel_name=channel_name,
            conversation_id=context.conversation_id,
            service_url=context.service_url,
            available=True,
        )
        await self.channel_repository.upsert(channel)
        logger.info(
            "teams_channel_activity_registered",
            extra={
                "tenant_id": channel.tenant_id,
                "team_id": channel.team_id,
                "channel_id": channel.channel_id,
                "channel_name": channel.channel_name,
            },
        )
        return channel

    async def handle_conversation_update(self, turn_context: Any) -> DiscoveredChannel | None:
        """Handle channel-created and team-deleted Teams lifecycle events."""
        activity = turn_context.activity
        activity_data = _as_mapping(activity)
        activity_type = activity_data.get("type") or getattr(activity, "type", None)
        channel_data = _as_mapping(
            activity_data.get("channelData") or activity_data.get("channel_data")
        )
        event_type = channel_data.get("eventType") or channel_data.get("event_type")
        if activity_type != "conversationUpdate":
            return None

        context = TeamsContext.from_activity(activity)
        if event_type == "teamDeleted":
            if not context.tenant_id or not context.team_id:
                logger.info(
                    "teams_team_deleted_skipped",
                    extra={
                        "tenant_id": context.tenant_id,
                        "team_id": context.team_id,
                        "team_name": context.team_name,
                    },
                )
                return None
            logger.info(
                "teams_team_deleted",
                extra={
                    "tenant_id": context.tenant_id,
                    "team_id": context.team_id,
                    "team_name": context.team_name,
                },
            )
            if self.installation_repository is not None:
                await self.installation_repository.mark_inactive(
                    context.tenant_id, context.team_id
                )
            return None

        if event_type != "channelCreated":
            return None

        if not context.tenant_id or not context.team_id or not context.channel_id:
            logger.info(
                "teams_channel_created_skipped",
                extra={
                    "tenant_id": context.tenant_id,
                    "team_id": context.team_id,
                    "channel_id": context.channel_id,
                },
            )
            return None

        logger.info(
            "teams_channel_created_received",
            extra={
                "tenant_id": context.tenant_id,
                "team_id": context.team_id,
                "channel_id": context.channel_id,
            },
        )
        team_name = await self._resolve_team_name(context)
        channel_data = _as_mapping(
            _as_mapping(activity_data.get("channelData") or activity_data.get("channel_data")).get("channel")
        )
        channel_name = _resolve_channel_name(
            channel_data, context.channel_id, context.team_id
        )
        channel = DiscoveredChannel(
            tenant_id=context.tenant_id,
            team_id=context.team_id,
            channel_id=context.channel_id,
            team_name=team_name,
            channel_name=channel_name,
            conversation_id=context.conversation_id,
            service_url=context.service_url,
            available=True,
        )
        await self.channel_repository.upsert(channel)
        logger.info(
            "teams_discovered_channel_upserted",
            extra={
                "tenant_id": channel.tenant_id,
                "team_id": channel.team_id,
                "channel_id": channel.channel_id,
            },
        )
        return channel
