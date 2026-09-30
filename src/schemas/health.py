"""Health and readiness response models."""

from pydantic import BaseModel


class HealthResponse(BaseModel):
    """Liveness response."""

    status: str


class ReadyResponse(BaseModel):
    """Readiness response."""

    status: str
    mongodb: str | None = None
