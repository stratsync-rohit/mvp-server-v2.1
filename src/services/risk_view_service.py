"""Server-side risk view selection for Adaptive Card actions."""

from __future__ import annotations

from typing import Any

from src.exceptions import AppError
from src.renderers.teams_risk_card_renderer import TeamsRiskCardRenderer
from src.services.risk_service import RiskService


class RiskViewService:
    """Reload the latest risk before rendering an allowlisted view."""

    _ALLOWED_VIEWS = {"details", "mitigation"}

    def __init__(self, risk_service: RiskService, renderer: TeamsRiskCardRenderer) -> None:
        self.risk_service = risk_service
        self.renderer = renderer

    async def render(self, risk_id: str, view_name: str) -> dict[str, Any]:
        """Return a freshly rendered details or mitigation card."""
        normalized_view = view_name.strip() if isinstance(view_name, str) else ""
        if normalized_view not in self._ALLOWED_VIEWS:
            raise AppError("RISK_VIEW_INVALID", "The requested risk view is not supported.", 400)
        risk = await self.risk_service.get(risk_id)
        views = risk.get("views") if isinstance(risk, dict) else None
        if not isinstance(views, dict) or not isinstance(views.get(normalized_view), dict):
            raise AppError("RISK_VIEW_NOT_FOUND", "The requested risk view was not found.", 404)
        return self.renderer.render_view(risk, normalized_view)
