"""Dependency-free liveness and readiness routes."""

from fastapi import APIRouter, Request

from src.schemas.health import HealthResponse, ReadyResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
async def health() -> dict[str, str]:
    """Return process liveness without checking external dependencies."""
    return {"status": "ok"}


@router.get("/ready", response_model=ReadyResponse, response_model_exclude_none=True)
async def ready(request: Request) -> dict[str, str]:
    """Return process readiness and Mongo connectivity when Mongo is enabled."""
    mongo = getattr(getattr(request.app.state, "container", None), "mongo", None)
    if mongo is None or not mongo.enabled:
        return {"status": "ready"}
    connected = await mongo.ping()
    if not connected:
        return {"status": "not_ready", "mongodb": "disconnected"}
    return {"status": "ready", "mongodb": "connected"}
