"""Typed internal contracts for authenticated Teams activity context."""

from __future__ import annotations

from datetime import datetime
from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, ConfigDict


def _as_mapping(value: Any) -> Mapping[str, Any]:
    """Convert Bot Framework models and mappings into safe field mappings."""
    if isinstance(value, Mapping):
        return value
    if hasattr(value, "serialize"):
        serialized = value.serialize()
        if isinstance(serialized, Mapping):
            return serialized
    if hasattr(value, "to_dict"):
        converted = value.to_dict()
        if isinstance(converted, Mapping):
            return converted
    if hasattr(value, "__dict__"):
        return {key: item for key, item in vars(value).items() if not key.startswith("_")}
    return {}


class TeamsContext(BaseModel):
    """Trusted routing context extracted after Bot Framework authentication."""

    model_config = ConfigDict(extra="ignore")

    tenant_id: str | None = None
    team_id: str | None = None
    team_name: str | None = None
    channel_id: str | None = None
    channel_name: str | None = None
    conversation_id: str | None = None
    conversation_type: str | None = None
    service_url: str | None = None
    recipient_id: str | None = None
    sender_id: str | None = None

    @classmethod
    def from_activity(cls, activity: Any) -> "TeamsContext":
        """Extract Teams routing metadata from an SDK activity or raw mapping."""
        data = _as_mapping(activity)
        channel_data = _as_mapping(data.get("channelData") or data.get("channel_data"))
        conversation = _as_mapping(data.get("conversation"))
        sender = _as_mapping(data.get("from") or data.get("from_property"))
        recipient = _as_mapping(data.get("recipient"))
        tenant = _as_mapping(channel_data.get("tenant"))
        team = _as_mapping(channel_data.get("team"))
        channel = _as_mapping(channel_data.get("channel"))
        return cls(
            tenant_id=tenant.get("id") or conversation.get("tenantId"),
            team_id=team.get("id"),
            team_name=team.get("name"),
            channel_id=channel.get("id"),
            channel_name=channel.get("name"),
            conversation_id=conversation.get("id"),
            conversation_type=conversation.get("conversationType"),
            service_url=data.get("serviceUrl") or data.get("service_url"),
            recipient_id=recipient.get("id"),
            sender_id=sender.get("id"),
        )


class TeamInstallation(BaseModel):
    """Persisted lifecycle state for one Teams bot installation."""

    model_config = ConfigDict(extra="ignore")

    tenant_id: str
    team_id: str
    team_name: str | None = None
    conversation_id: str | None = None
    conversation_type: str | None = None
    service_url: str | None = None
    bot_id: str | None = None
    is_active: bool = True
    installed_at: datetime | None = None
    updated_at: datetime | None = None
    uninstalled_at: datetime | None = None


class DiscoveredChannel(BaseModel):
    """A channel discovered from a trusted team installation."""

    model_config = ConfigDict(extra="ignore")

    tenant_id: str
    team_id: str
    channel_id: str
    team_name: str | None = None
    channel_name: str | None = None
    conversation_id: str | None = None
    service_url: str | None = None
    available: bool = True
    discovered_at: datetime | None = None
    updated_at: datetime | None = None
