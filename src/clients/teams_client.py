"""Microsoft Teams SDK calls used by domain services."""

from __future__ import annotations

import logging
from typing import Any

try:
    from botbuilder.core.teams import TeamsInfo
except ImportError:  # pragma: no cover - keeps disabled local imports lightweight.
    TeamsInfo = None  # type: ignore[assignment,misc]

from src.bot.diagnostics.activity_logger import sanitize_activity


logger = logging.getLogger(__name__)


class TeamsClient:
    """Thin wrapper around Bot Framework TeamsInfo operations."""

    async def get_team_channels(self, turn_context: Any, team_id: str | None = None) -> list[Any]:
        """Return all channels visible to the authenticated bot installation."""
        if TeamsInfo is None:
            return []
        channels = await TeamsInfo.get_team_channels(turn_context, team_id or "")
        logger.debug(
            "teams_info_team_channels_returned",
            extra={
                "team_id": team_id,
                "channel_count": len(channels or []),
                "raw_channel_fields": [sanitize_activity(channel) for channel in (channels or [])],
            },
        )
        return channels
