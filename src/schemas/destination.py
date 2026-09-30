"""Destination contracts used by outbound notification routing."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Destination(BaseModel):
    """Persisted outbound destination and provider routing metadata."""

    model_config = ConfigDict(extra="ignore")

    destination_id: str
    tenant_id: str
    team_id: str
    channel_id: str
    team_name: str | None = None
    channel_name: str | None = None
    conversation_id: str | None = None
    conversation_reference: dict[str, Any] | None = None
    service_url: str | None = None
    recipient_id: str | None = None
    is_active: bool = True
    created_at: datetime | None = None
    updated_at: datetime | None = None


def build_destination_id(tenant_id: str, team_id: str, channel_id: str) -> str:
    """Build a stable, tenant-isolated logical destination identifier."""
    return f"{tenant_id}:{team_id}:{channel_id}"


class DestinationResolveRequest(BaseModel):
    """Client input identifying one already-discovered Teams channel."""

    tenant_id: str = Field(min_length=1)
    team_id: str = Field(min_length=1)
    channel_id: str = Field(min_length=1)

    @field_validator("tenant_id", "team_id", "channel_id", mode="before")
    @classmethod
    def reject_blank_identifier(cls, value: object) -> str:
        """Normalize identifiers and reject whitespace-only values."""
        if not isinstance(value, str) or not value.strip():
            raise ValueError("must be a non-empty string")
        return value.strip()


class DestinationApiResponse(BaseModel):
    """Safe destination metadata returned to API clients."""

    model_config = ConfigDict(extra="ignore")

    destination_id: str
    tenant_id: str
    team_id: str
    team_name: str | None = None
    channel_id: str
    channel_name: str | None = None
    is_active: bool = True


class DestinationResolveResponse(BaseModel):
    """Response envelope for destination resolution."""

    success: bool
    data: DestinationApiResponse | None = None
    error: object | None = None
