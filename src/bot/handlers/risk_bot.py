"""Thin Microsoft Teams activity router."""

import logging
from typing import Any

from botbuilder.core import TurnContext
from botbuilder.core.teams import TeamsActivityHandler
from botbuilder.schema import AdaptiveCardInvokeResponse

from src.bot.diagnostics.activity_logger import log_activity
from src.exceptions import AppError

logger = logging.getLogger(__name__)


class RiskBot(TeamsActivityHandler):
    """Route authenticated activities to injected application services."""

    def __init__(self, installation_service: Any | None = None,
                 teams_service: Any | None = None,
                 reaction_service: Any | None = None,
                 risk_view_service: Any | None = None,
                 notification_service: Any | None = None,
                 processed_activity_repository: Any | None = None,
                 *, debug_activity_logging: bool = False) -> None:
        super().__init__()
        self.installation_service = installation_service
        self.teams_service = teams_service
        self.reaction_service = reaction_service
        self.risk_view_service = risk_view_service
        self.notification_service = notification_service
        self.processed_activity_repository = processed_activity_repository
        self.debug_activity_logging = debug_activity_logging

    async def on_turn(self, turn_context: TurnContext) -> None:
        """Log safe activity metadata, then use the SDK's normal dispatch."""
        activity = turn_context.activity
        activity_id = getattr(activity, "id", None)
        claimed = True
        if self.processed_activity_repository is not None and activity_id:
            claimed = await self.processed_activity_repository.claim(
                activity_id, getattr(activity, "type", None)
            )
        if not claimed:
            logger.info("bot_activity_duplicate_skipped", extra={"activity_id": activity_id})
            return
        log_activity(activity, debug=self.debug_activity_logging)
        try:
            await super().on_turn(turn_context)
        except Exception as exc:
            if self.processed_activity_repository is not None and activity_id:
                await self.processed_activity_repository.mark_failed(activity_id, str(exc))
            raise
        else:
            if self.processed_activity_repository is not None and activity_id:
                await self.processed_activity_repository.mark_completed(activity_id)

    async def on_installation_update_add(self, turn_context: TurnContext) -> None:
        """Persist an installation and initiate channel discovery."""
        logger.info("teams_installation_added")
        if self.installation_service is not None:
            await self.installation_service.add(turn_context)

    async def on_installation_update_remove(self, turn_context: TurnContext) -> None:
        """Soft-deactivate an installation."""
        logger.info("teams_installation_removed")
        if self.installation_service is not None:
            await self.installation_service.remove(turn_context)

    async def on_conversation_update_activity(self, turn_context: TurnContext) -> None:
        """Delegate conversation lifecycle handling to the Teams service."""
        logger.info("teams_conversation_updated")
        if self.teams_service is not None:
            await self.teams_service.handle_conversation_update(turn_context)

    async def on_message_activity(self, turn_context: TurnContext) -> None:
        """Observe a message while leaving domain behavior in services."""
        logger.info("teams_message_received")

    async def on_message_reaction_activity(self, turn_context: TurnContext) -> None:
        """Delegate reaction add/remove state to the reaction service."""
        logger.info("teams_message_reaction_received")
        if self.reaction_service is not None:
            await self.reaction_service.handle(turn_context)

    async def on_adaptive_card_invoke(
        self, turn_context: TurnContext, invoke_value: Any
    ) -> AdaptiveCardInvokeResponse:
        """Validate an identifier-only risk-view action and render its latest view."""
        action = getattr(invoke_value, "action", None)
        if not isinstance(action, dict) or action.get("type") != "Action.Execute":
            return self._invoke_error(400, "BAD_RISK_VIEW_ACTION", "Unsupported card action.")
        data = action.get("data")
        if (
            not isinstance(data, dict)
            or action.get("verb") != "show_risk_view"
            or data.get("action") != "show_risk_view"
        ):
            return self._invoke_error(400, "BAD_RISK_VIEW_ACTION", "Unsupported card action.")
        risk_id = data.get("risk_id")
        view_name = data.get("view")
        if not isinstance(risk_id, str) or not risk_id.strip() or not isinstance(view_name, str):
            return self._invoke_error(400, "BAD_RISK_VIEW_ACTION", "Invalid risk view identifiers.")
        if view_name not in {"details", "mitigation"}:
            return self._invoke_error(400, "RISK_VIEW_INVALID", "The requested risk view is not supported.")
        if self.risk_view_service is None:
            return self._invoke_error(500, "RISK_VIEW_UNAVAILABLE", "Risk views are not configured.")
        if self.notification_service is None:
            return self._invoke_error(500, "RISK_VIEW_UNAVAILABLE", "Notification sending is not configured.")
        try:
            card = await self.risk_view_service.render(risk_id, view_name)
            await self.notification_service.send_in_context(
                turn_context,
                card,
                risk_id=risk_id,
                view_type=view_name,
            )
        except AppError as exc:
            return self._invoke_error(exc.status_code, exc.code, exc.message)
        return AdaptiveCardInvokeResponse(
            status_code=200,
            type="application/vnd.microsoft.activity.message",
            value={"text": ""},
        )

    @staticmethod
    def _invoke_error(status_code: int, code: str, message: str) -> AdaptiveCardInvokeResponse:
        """Return a safe Adaptive Card invoke error response."""
        return AdaptiveCardInvokeResponse(
            status_code=status_code,
            type="application/vnd.microsoft.error",
            value={"code": code, "message": message},
        )
