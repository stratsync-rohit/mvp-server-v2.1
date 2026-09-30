"""Authenticated Microsoft Bot Framework activity endpoint."""

import logging

from botbuilder.schema import Activity
from fastapi import APIRouter, Request, Response, status
from fastapi.responses import JSONResponse

from src.exceptions import AppError
from src.bot.diagnostics.activity_logger import log_activity

logger = logging.getLogger(__name__)
router = APIRouter(tags=["bot"])


@router.post("/api/messages")
async def bot_messages(request: Request) -> Response:
    """Deserialize and authenticate one Bot Framework activity."""
    if "application/json" not in request.headers.get("content-type", "").lower():
        raise AppError("UNSUPPORTED_MEDIA_TYPE", "Content-Type must be application/json.", 415)
    body = await request.json()
    settings = getattr(request.app.state, "settings", None)
    log_activity(body, debug=bool(getattr(settings, "teams_debug_activity_logging", False)))
    activity = Activity().deserialize(body)
    auth_header = request.headers.get("authorization", "")
    container = request.app.state.container
    try:
        invoke_response = await container.adapter.process_activity(
            auth_header, activity, container.bot.on_turn
        )
    except Exception:
        logger.exception(
            "bot_activity_failed",
            extra={"activity_id": activity.id, "activity_type": activity.type},
        )
        raise
    if invoke_response:
        return JSONResponse(
            status_code=invoke_response.status,
            content=invoke_response.body,
        )
    return Response(status_code=status.HTTP_201_CREATED)
