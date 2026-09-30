"""Microsoft Teams SDK calls used by domain services."""

from __future__ import annotations

from typing import Any

try:
    from botbuilder.core.teams import TeamsInfo
except ImportError:  # pragma: no cover - keeps disabled local imports lightweight.
    TeamsInfo = None  # type: ignore[assignment,misc]


class TeamsClient:
    """Thin wrapper around Bot Framework TeamsInfo operations."""

    async def get_team_channels(self, turn_context: Any, team_id: str | None = None) -> list[Any]:
        """Return all channels visible to the authenticated bot installation."""
        if TeamsInfo is None:
            return []
        return await TeamsInfo.get_team_channels(turn_context, team_id or "")
