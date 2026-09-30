"""Internal notification reaction contracts."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from src.schemas.notification import ReactionSummary


class NotificationReaction(BaseModel):
    """Current add/remove state for a Teams reaction."""

    model_config = ConfigDict(extra="ignore")

    notification_id: str
    destination_id: str | None = None
    tenant_id: str
    teams_message_id: str
    user_aad_id: str | None = None
    reaction: str
    is_active: bool
    created_at: datetime | None = None
    updated_at: datetime | None = None


class ReactionReadItem(BaseModel):
    """Safe reaction state returned to the internal frontend."""

    reaction: str
    user_aad_id: str | None = None
    is_active: bool
    teams_message_id: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class NotificationReactionsData(BaseModel):
    """Reaction records and an active-only summary for one notification."""

    notification_id: str
    summary: ReactionSummary
    reactions: list[ReactionReadItem] = Field(default_factory=list)


class NotificationReactionsResponse(BaseModel):
    """Response envelope for notification reactions."""

    success: bool
    data: NotificationReactionsData | None = None
    error: object | None = None
