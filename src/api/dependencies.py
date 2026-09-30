"""FastAPI dependency boundaries."""

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from botbuilder.integration.aiohttp import CloudAdapter

    from src.bot.handlers.risk_bot import RiskBot
    from src.database.mongo import MongoManager
    from src.services.installation_service import InstallationService
    from src.services.destination_service import DestinationService
    from src.services.notification_service import NotificationService
    from src.services.risk_service import RiskService
    from src.renderers.teams_risk_card_renderer import TeamsRiskCardRenderer
    from src.services.risk_view_service import RiskViewService


@dataclass
class Container:
    """Application-owned dependency container attached to FastAPI state."""

    adapter: "CloudAdapter"
    bot: "RiskBot"
    mongo: "MongoManager | None" = None
    installation_service: "InstallationService | None" = None
    destination_service: "DestinationService | None" = None
    notification_service: "NotificationService | None" = None
    risk_service: "RiskService | None" = None
    risk_card_renderer: "TeamsRiskCardRenderer | None" = None
    risk_view_service: "RiskViewService | None" = None
