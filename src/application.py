"""FastAPI application factory and dependency composition root."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from src.api.bot_routes import router as bot_router
from src.api.dependencies import Container
from src.api.health_routes import router as health_router
from src.api.installation_routes import router as installation_router
from src.api.destination_routes import router as destination_router
from src.api.notification_routes import router as notification_router
from src.bot.adapter import create_adapter
from src.bot.handlers.risk_bot import RiskBot
from src.config.settings import get_settings
from src.clients.teams_client import TeamsClient
from src.clients.teams_conversation_client import TeamsConversationClient
from src.database.mongo import MongoManager
from src.exceptions import AppError
from src.middleware.request_logging import RequestLoggingMiddleware
from src.repositories.destination_repository import DestinationRepository
from src.repositories.discovered_channel_repository import DiscoveredChannelRepository
from src.repositories.notification_repository import NotificationRepository
from src.repositories.processed_activity_repository import ProcessedActivityRepository
from src.repositories.reaction_repository import ReactionRepository
from src.repositories.team_installation_repository import TeamInstallationRepository
from src.repositories.risk_repository import RiskRepository
from src.renderers.teams_risk_card_renderer import TeamsRiskCardRenderer
from src.services.destination_service import DestinationService
from src.services.installation_service import InstallationService
from src.services.notification_service import NotificationService
from src.services.risk_service import RiskService
from src.services.risk_view_service import RiskViewService
from src.services.reaction_service import ReactionService
from src.services.teams_service import TeamsService
from src.utils.logger import configure_logging

logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    """Create the FastAPI application and wire its runtime dependencies."""

    settings = get_settings()
    configure_logging(settings.log_level)
    app_settings = settings

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        """Create the authenticated adapter, persistence, services, and bot."""
        mongo = MongoManager(settings)
        await mongo.start()
        adapter = create_adapter(settings)
        channel_repository = DiscoveredChannelRepository(mongo=mongo)
        installation_repository = TeamInstallationRepository(mongo=mongo)
        teams_service = TeamsService(
            TeamsClient(), channel_repository, installation_repository
        )
        installation_service = InstallationService(
            repository=installation_repository,
            teams_service=teams_service,
            channel_repository=channel_repository,
        )
        conversation_client = TeamsConversationClient(adapter, settings.microsoft_app_id)
        destination_service = DestinationService(
            DestinationRepository(mongo=mongo), conversation_client, channel_repository
        )
        # NotificationService is an internal dependency of domain callers; the
        # inbound bot only needs installation, reaction, and idempotency routes.
        notification_repository = NotificationRepository(mongo=mongo)
        reaction_repository = ReactionRepository(mongo=mongo)
        notification_service = NotificationService(
            repository=notification_repository,
            destination_service=destination_service,
            conversation_client=conversation_client,
            reaction_repository=reaction_repository,
        )
        risk_service = RiskService(RiskRepository(mongo=mongo))
        risk_card_renderer = TeamsRiskCardRenderer()
        risk_view_service = RiskViewService(risk_service, risk_card_renderer)
        reaction_service = ReactionService(
            reaction_repository, notification_repository
        )
        bot = RiskBot(
            installation_service=installation_service,
            teams_service=teams_service,
            reaction_service=reaction_service,
            risk_view_service=risk_view_service,
            notification_service=notification_service,
            processed_activity_repository=ProcessedActivityRepository(mongo=mongo),
            debug_activity_logging=settings.teams_debug_activity_logging,
        )
        app.state.container = Container(
            adapter=adapter,
            bot=bot,
            mongo=mongo,
            installation_service=installation_service,
            destination_service=destination_service,
            notification_service=notification_service,
            risk_service=risk_service,
            risk_card_renderer=risk_card_renderer,
            risk_view_service=risk_view_service,
        )
        app.state.settings = settings
        logger.info("application_started")
        try:
            yield
        finally:
            await mongo.close()
            logger.info("application_stopped")

    app = FastAPI(
        title="Enterprise Risk Notification Bot",
        version="1.0.0",
        lifespan=lifespan,
    )
    app.state.settings = app_settings
    app.add_middleware(RequestLoggingMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
    )

    @app.exception_handler(AppError)
    async def app_error_handler(_: Request, exc: AppError) -> JSONResponse:
        """Serialize safe application errors into the public API envelope."""
        return JSONResponse(
            status_code=exc.status_code,
            content={"success": False, "data": None, "error": {"code": exc.code, "message": exc.message}},
        )

    @app.exception_handler(Exception)
    async def unhandled_error_handler(
        _: Request, exc: Exception
    ) -> JSONResponse:
        """Log unexpected failures and return a generic client error."""
        logger.exception("unhandled_http_error", exc_info=exc)
        return JSONResponse(
            status_code=500,
            content={"success": False, "data": None, "error": {"code": "INTERNAL_ERROR", "message": "An internal error occurred."}},
        )

    app.include_router(health_router)
    app.include_router(bot_router)
    app.include_router(installation_router)
    app.include_router(destination_router)
    app.include_router(notification_router)
    return app
