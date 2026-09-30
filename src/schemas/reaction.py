"""Internal notification reaction contracts."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict


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

