"""Official Bot Framework authentication and CloudAdapter wiring."""

import logging

from botbuilder.core import TurnContext
from botbuilder.integration.aiohttp import (
    CloudAdapter,
    ConfigurationBotFrameworkAuthentication,
)

from src.config.settings import Settings

logger = logging.getLogger(__name__)


class BotFrameworkConfig:
    """Attribute names expected by ConfigurationBotFrameworkAuthentication."""

    def __init__(self, settings: Settings) -> None:
        missing = [
            name
            for name, value in (
                ("MICROSOFT_APP_ID", settings.microsoft_app_id),
                ("MICROSOFT_APP_PASSWORD", settings.microsoft_app_password),
                ("MICROSOFT_APP_TENANT_ID", settings.microsoft_app_tenant_id),
            )
            if not value or not value.strip()
        ]
        if missing:
            raise ValueError(
                "Missing required Microsoft Bot Framework setting(s): "
                + ", ".join(missing)
            )
        if settings.microsoft_app_type != "SingleTenant":
            raise ValueError(
                "MICROSOFT_APP_TYPE must be 'SingleTenant' for this bot."
            )

        self.APP_ID = settings.microsoft_app_id
        self.APP_PASSWORD = settings.microsoft_app_password
        self.APP_TYPE = settings.microsoft_app_type
        self.APP_TENANTID = settings.microsoft_app_tenant_id


def create_adapter(settings: Settings) -> CloudAdapter:
    """Create the authenticated CloudAdapter with safe turn error handling."""
    adapter = CloudAdapter(
        ConfigurationBotFrameworkAuthentication(BotFrameworkConfig(settings))
    )

    async def on_error(turn_context: TurnContext, error: Exception) -> None:
        """Log safe activity metadata and send a generic user-facing error."""
        logger.exception(
            "bot_turn_error",
            exc_info=error,
            extra={
                "activity_id": getattr(turn_context.activity, "id", None),
                "activity_type": getattr(turn_context.activity, "type", None),
            },
        )
        await turn_context.send_activity("The risk bot could not process this request.")

    adapter.on_turn_error = on_error
    return adapter
