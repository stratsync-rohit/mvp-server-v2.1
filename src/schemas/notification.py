"""Internal notification contracts."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Notification(BaseModel):
    """Notification send state persisted independently of provider mechanics."""

    model_config = ConfigDict(extra="ignore")

    notification_id: str
    destination_id: str
    risk_id: str | None = None
    notification_type: str | None = None
    view_type: str | None = None
    card: dict[str, Any]
    status: Literal["pending", "sent", "failed"] = "pending"
    teams_message_id: str | None = None
    error: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class NotificationSendRequest(BaseModel):
    """Client input for rendering a stored risk through a trusted destination."""

    model_config = ConfigDict(extra="ignore")

    destination_id: str = Field(min_length=1)
    risk_id: str = Field(min_length=1)

    @field_validator("destination_id", "risk_id", mode="before")
    @classmethod
    def reject_blank_required_text(cls, value: object) -> str:
        """Normalize required text and reject whitespace-only values."""
        if not isinstance(value, str) or not value.strip():
            raise ValueError("must be a non-empty string")
        return value.strip()


class NotificationSendResponseData(BaseModel):
    """Safe metadata returned after a successful send."""

    notification_id: str
    destination_id: str
    status: Literal["sent"]


class NotificationSendResponse(BaseModel):
    """Response envelope for notification sends."""

    success: bool
    data: NotificationSendResponseData | None = None
    error: object | None = None
